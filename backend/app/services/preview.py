"""Fetch a link's preview: Open Graph / Twitter Card tags, or oEmbed for X and YouTube.

Every outbound request goes through the `httpx.AsyncClient` from `build_http_client`, which
sets a browser User-Agent and timeouts. Failures are sorted into two exceptions so the
worker knows what to do next:

- `DeadLinkError`: the page is gone (404, 410, unknown host). Don't retry.
- `RetryableFetchError`: anything else (timeout, 5xx, 403, connection refused). Retry later.
"""

import json
import socket
from dataclasses import dataclass, replace
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

import httpx

from app.models import ContentType
from app.services.classify import classify
from app.services.normalize import SHORT_LINK_HOSTS

# A current desktop Chrome UA: many sites serve bots an empty page or a 403.
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)
TIMEOUT = httpx.Timeout(10.0, connect=5.0)
# The <head> is almost always in the first few hundred KB; never download a whole video.
MAX_PAGE_BYTES = 1_000_000
MAX_SHORT_LINK_HOPS = 5

YOUTUBE_OEMBED_URL = "https://www.youtube.com/oembed"
X_OEMBED_URL = "https://publish.twitter.com/oembed"

_DEAD_STATUSES = frozenset({404, 410})
_TITLE_LIMIT = 300
_DESCRIPTION_LIMIT = 1000


class FetchError(Exception):
    """Base class for preview failures."""


class DeadLinkError(FetchError):
    """The link will never work again (404/410/unknown host)."""


class RetryableFetchError(FetchError):
    """A failure that may go away (timeout, 5xx, blocked, network trouble)."""


@dataclass(frozen=True)
class Preview:
    title: str | None = None
    description: str | None = None
    image_url: str | None = None
    site_name: str | None = None
    og_type: str | None = None


def build_http_client(max_connections: int) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        headers={"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"},
        timeout=TIMEOUT,
        limits=httpx.Limits(max_connections=max_connections),
    )


# --- error mapping ---


def is_unknown_host(exc: BaseException) -> bool:
    """True if DNS says the host doesn't exist (not "DNS is unreachable right now")."""
    # httpx wraps the socket error; walk the whole chain (it can contain cycles).
    pending: list[BaseException] = [exc]
    seen: set[int] = set()
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        if isinstance(current, socket.gaierror):
            # EAI_AGAIN ("temporary failure") is what we get when we're offline; only
            # EAI_NONAME means the name really doesn't exist.
            return current.errno == socket.EAI_NONAME
        pending.extend(e for e in (current.__cause__, current.__context__) if e is not None)
    return False


def _transport_error(url: str, exc: httpx.HTTPError, *, dns_means_dead: bool) -> FetchError:
    if isinstance(exc, httpx.UnsupportedProtocol) or (dns_means_dead and is_unknown_host(exc)):
        return DeadLinkError(f"{url}: {exc!r}")
    return RetryableFetchError(f"{url}: {exc!r}")


def _status_error(url: str, response: httpx.Response) -> FetchError | None:
    if response.status_code in _DEAD_STATUSES:
        return DeadLinkError(f"{url} returned {response.status_code}")
    if response.is_error:
        return RetryableFetchError(f"{url} returned {response.status_code}")
    return None


# --- text helpers ---


def _clean(value: str | None, limit: int) -> str | None:
    if value is None:
        return None
    value = " ".join(value.split())
    if len(value) > limit:
        value = value[: limit - 1].rstrip() + "…"
    return value or None


def _absolute_http_url(value: str | None, base_url: str) -> str | None:
    if not value or not value.strip():
        return None
    absolute = urljoin(base_url, value.strip())
    return absolute if urlsplit(absolute).scheme in {"http", "https"} else None


def site_label(url: str) -> str:
    """Fallback site name: the host without "www.", e.g. "example.com"."""
    host = (urlsplit(url).hostname or "").lower()
    return host.removeprefix("www.")


# --- HTML parsing ---


class _HeadParser(HTMLParser):
    """Collects <meta property|name=… content=…> tags and the first <title>."""

    def __init__(self) -> None:
        # convert_charrefs turns "&amp;" into "&" in both text and attribute values.
        super().__init__(convert_charrefs=True)
        self.meta: dict[str, str] = {}
        self.title: str | None = None
        self._title_parts: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "meta":
            attributes = dict(attrs)
            key = (attributes.get("property") or attributes.get("name") or "").strip().lower()
            content = attributes.get("content")
            # First one wins: pages sometimes repeat og:image for several sizes.
            if key and content and key not in self.meta:
                self.meta[key] = content
        elif tag == "title" and self.title is None:
            self._title_parts = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "title" and self._title_parts is not None:
            self.title = "".join(self._title_parts)
            self._title_parts = None

    def handle_data(self, data: str) -> None:
        if self._title_parts is not None:
            self._title_parts.append(data)


def parse_html(html: str, base_url: str) -> Preview:
    """Extract a preview from a page. Relative image URLs are resolved against `base_url`."""
    parser = _HeadParser()
    parser.feed(html)
    parser.close()
    meta = parser.meta

    def first(*keys: str) -> str | None:
        return next((meta[key] for key in keys if meta.get(key, "").strip()), None)

    return Preview(
        title=_clean(first("og:title", "twitter:title") or parser.title, _TITLE_LIMIT),
        description=_clean(
            first("og:description", "twitter:description", "description"), _DESCRIPTION_LIMIT
        ),
        image_url=_absolute_http_url(
            first("og:image", "og:image:url", "og:image:secure_url", "twitter:image"),
            base_url,
        ),
        site_name=_clean(first("og:site_name", "application-name"), _TITLE_LIMIT),
        og_type=_clean(first("og:type"), 50),
    )


class _TweetTextParser(HTMLParser):
    """Pulls the tweet text out of the <p> in X's oEmbed blockquote."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._depth = 0
        self._done = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "p" and not self._done:
            self._depth += 1
        elif tag == "br" and self._depth:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag == "p" and self._depth:
            self._depth -= 1
            self._done = self._depth == 0

    def handle_data(self, data: str) -> None:
        if self._depth:
            self.parts.append(data)


def _tweet_text(html: str) -> str:
    parser = _TweetTextParser()
    parser.feed(html)
    parser.close()
    return "".join(parser.parts).strip()


# --- fetching ---


async def resolve_short_link(client: httpx.AsyncClient, url: str) -> str:
    """Follow a short link's redirects until they leave the shortener; return the target.

    Redirects are followed by hand so we never download the target page here.
    """
    current = url
    for _ in range(MAX_SHORT_LINK_HOPS):
        try:
            response = await client.get(current, follow_redirects=False)
        except httpx.HTTPError as exc:
            raise _transport_error(current, exc, dns_means_dead=True) from exc
        if error := _status_error(current, response):
            raise error
        location = response.headers.get("location")
        if not response.is_redirect or not location:
            return current
        current = urljoin(current, location)
        if (urlsplit(current).hostname or "").lower() not in SHORT_LINK_HOSTS:
            return current
    raise RetryableFetchError(f"{url}: more than {MAX_SHORT_LINK_HOPS} short-link redirects")


async def _fetch_page(client: httpx.AsyncClient, url: str) -> Preview:
    try:
        async with client.stream("GET", url, follow_redirects=True) as response:
            if error := _status_error(url, response):
                raise error
            content_type = response.headers.get("content-type", "").lower()
            if content_type and "html" not in content_type:
                # A PDF, image, etc.: nothing to parse, but the link itself is fine.
                return Preview()
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body += chunk
                if len(body) >= MAX_PAGE_BYTES:
                    break
            final_url = str(response.url)
            encoding = response.encoding or "utf-8"
    except httpx.HTTPError as exc:
        raise _transport_error(url, exc, dns_means_dead=True) from exc

    try:
        html = body.decode(encoding, errors="replace")
    except LookupError:  # a charset Python doesn't know
        html = body.decode("utf-8", errors="replace")
    return parse_html(html, final_url)


async def _fetch_oembed(
    client: httpx.AsyncClient, endpoint: str, params: dict[str, str]
) -> dict | None:
    """Return the oEmbed JSON, or None if the provider won't give us one (fall back to OG)."""
    try:
        response = await client.get(endpoint, params=params)
    except httpx.HTTPError as exc:
        # The provider's own host failing to resolve says nothing about the link.
        raise _transport_error(endpoint, exc, dns_means_dead=False) from exc
    if response.status_code in _DEAD_STATUSES:
        # The provider says the video/tweet doesn't exist (deleted, or never did).
        raise DeadLinkError(f"{params['url']}: oEmbed returned {response.status_code}")
    if response.status_code >= 500:
        raise RetryableFetchError(f"{endpoint} returned {response.status_code}")
    if response.status_code != 200:
        # 401/403: embedding disabled or private. The page's OG tags may still work.
        return None
    try:
        data = response.json()
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


async def _youtube_preview(client: httpx.AsyncClient, url: str) -> Preview | None:
    data = await _fetch_oembed(client, YOUTUBE_OEMBED_URL, {"url": url, "format": "json"})
    if data is None:
        return None
    return Preview(
        title=_clean(data.get("title"), _TITLE_LIMIT),
        description=_clean(data.get("author_name"), _DESCRIPTION_LIMIT),
        image_url=_absolute_http_url(data.get("thumbnail_url"), url),
        site_name=_clean(data.get("provider_name"), _TITLE_LIMIT) or "YouTube",
    )


async def _tweet_preview(client: httpx.AsyncClient, url: str) -> Preview | None:
    data = await _fetch_oembed(
        client, X_OEMBED_URL, {"url": url, "omit_script": "true", "dnt": "true"}
    )
    if data is None:
        return None
    text = _tweet_text(str(data.get("html") or ""))
    handle = urlsplit(str(data.get("author_url") or "")).path.strip("/")
    author = f"@{handle}" if handle else data.get("author_name") or "X"
    first_line = text.splitlines()[0] if text else ""
    return Preview(
        title=_clean(f"{author}: {first_line}" if first_line else author, 120),
        description=_clean(text, _DESCRIPTION_LIMIT),
        site_name="X",
    )


async def fetch_preview(client: httpx.AsyncClient, url: str) -> Preview:
    """Fetch the preview for a normalized URL. Raises `DeadLinkError`/`RetryableFetchError`."""
    content_type = classify(url)
    preview: Preview | None = None
    if content_type is ContentType.YOUTUBE:
        preview = await _youtube_preview(client, url)
    elif content_type is ContentType.TWEET:
        preview = await _tweet_preview(client, url)
    # Instagram's oEmbed needs a Facebook app token, so Instagram uses the page's OG tags.
    if preview is None:
        preview = await _fetch_page(client, url)
    if preview.site_name is None:
        preview = replace(preview, site_name=site_label(url))
    return preview
