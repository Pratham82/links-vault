import socket
from collections.abc import AsyncIterator
from pathlib import Path

import httpcore
import httpx
import pytest
import respx

from app.services import preview as preview_module
from app.services.preview import (
    X_OEMBED_URL,
    YOUTUBE_OEMBED_URL,
    DeadLinkError,
    Preview,
    RetryableFetchError,
    build_http_client,
    fetch_preview,
    is_unknown_host,
    parse_html,
    resolve_short_link,
)

HTML_DIR = Path(__file__).parent / "fixtures" / "html"


def fixture_html(name: str) -> str:
    return (HTML_DIR / name).read_text()


def dns_error(errno: int) -> httpx.ConnectError:
    """The exception chain real httpx raises when DNS lookup fails."""
    try:
        try:
            raise socket.gaierror(errno, "DNS says no")
        except socket.gaierror as exc:
            raise httpcore.ConnectError(str(exc)) from exc
    except httpcore.ConnectError as exc:
        try:
            raise httpx.ConnectError(str(exc)) from exc
        except httpx.ConnectError as wrapped:
            return wrapped


@pytest.fixture
async def http() -> AsyncIterator[httpx.AsyncClient]:
    async with build_http_client(max_connections=2) as client:
        yield client


# --- parse_html (no network) ---


def test_parse_open_graph_article() -> None:
    preview = parse_html(fixture_html("og_article.html"), "https://blog.example.com/posts/rsc")
    assert preview == Preview(
        title="Server Components & You",
        description="A long look at React Server Components.",
        # Relative og:image is resolved; the first og:image wins.
        image_url="https://blog.example.com/images/cover.jpg",
        site_name="Example Blog",
        og_type="article",
    )


def test_parse_twitter_card_fallback() -> None:
    preview = parse_html(fixture_html("twitter_card.html"), "https://example.com")
    assert preview.title == "Only Twitter Card tags"
    assert preview.description == "Described by twitter:description."
    assert preview.image_url == "https://img.example.com/card.png"
    assert preview.site_name is None
    assert preview.og_type is None


def test_parse_title_only_page() -> None:
    preview = parse_html(fixture_html("title_only.html"), "https://example.com")
    assert preview.title == "Just a <title> tag"
    assert preview.description is None
    # Non-http(s) image URLs are dropped.
    assert preview.image_url is None


def test_parse_instagram_reel() -> None:
    preview = parse_html(fixture_html("instagram_reel.html"), "https://www.instagram.com/reel/C9")
    assert preview.title == 'Chef Asha on Instagram: "15-minute dal tadka"'
    assert (
        preview.image_url == "https://scontent.cdninstagram.com/v/t51/reel.jpg?stp=dst-jpg&oh=abc"
    )
    assert preview.site_name == "Instagram"
    assert preview.og_type == "video.other"


def test_parse_truncates_long_titles() -> None:
    html = f"<title>{'word ' * 200}</title>"
    title = parse_html(html, "https://example.com").title
    assert title is not None
    assert len(title) == 300
    assert title.endswith("…")


def test_parse_garbage_does_not_raise() -> None:
    assert parse_html("<<<not html at all", "https://example.com") == Preview()


# --- fetch_preview: Open Graph pages ---


@respx.mock
async def test_fetch_page_preview(http: httpx.AsyncClient) -> None:
    route = respx.get("https://blog.example.com/posts/rsc").respond(
        200, html=fixture_html("og_article.html")
    )
    preview = await fetch_preview(http, "https://blog.example.com/posts/rsc")

    assert preview.title == "Server Components & You"
    assert preview.og_type == "article"
    request = route.calls.last.request
    assert request.headers["user-agent"].startswith("Mozilla/5.0")


@respx.mock
async def test_fetch_follows_redirects_and_resolves_images_against_final_url(
    http: httpx.AsyncClient,
) -> None:
    respx.get("https://example.com/old").respond(
        301, headers={"Location": "https://new.example.com/a/"}
    )
    respx.get("https://new.example.com/a/").respond(
        200, html='<meta property="og:image" content="img.png"><title>Moved</title>'
    )
    preview = await fetch_preview(http, "https://example.com/old")
    assert preview.title == "Moved"
    assert preview.image_url == "https://new.example.com/a/img.png"


@respx.mock
async def test_fetch_falls_back_to_host_as_site_name(http: httpx.AsyncClient) -> None:
    respx.get("https://www.example.com/x").respond(200, html="<title>Hi</title>")
    preview = await fetch_preview(http, "https://www.example.com/x")
    assert preview.site_name == "example.com"


@respx.mock
async def test_fetch_non_html_is_fine_but_empty(http: httpx.AsyncClient) -> None:
    respx.get("https://example.com/paper.pdf").respond(
        200, content=b"%PDF-1.7", headers={"Content-Type": "application/pdf"}
    )
    preview = await fetch_preview(http, "https://example.com/paper.pdf")
    assert preview == Preview(site_name="example.com")


@respx.mock
async def test_fetch_decodes_declared_charset(http: httpx.AsyncClient) -> None:
    respx.get("https://example.com/latin").respond(
        200,
        content="<title>Café</title>".encode("latin-1"),
        headers={"Content-Type": "text/html; charset=iso-8859-1"},
    )
    assert (await fetch_preview(http, "https://example.com/latin")).title == "Café"


@respx.mock
@pytest.mark.parametrize("status", [404, 410])
async def test_fetch_gone_page_is_dead(http: httpx.AsyncClient, status: int) -> None:
    respx.get("https://example.com/gone").respond(status)
    with pytest.raises(DeadLinkError):
        await fetch_preview(http, "https://example.com/gone")


@respx.mock
@pytest.mark.parametrize("status", [500, 503, 429, 403])
async def test_fetch_other_errors_are_retryable(http: httpx.AsyncClient, status: int) -> None:
    respx.get("https://example.com/flaky").respond(status)
    with pytest.raises(RetryableFetchError):
        await fetch_preview(http, "https://example.com/flaky")


@respx.mock
async def test_fetch_timeout_is_retryable(http: httpx.AsyncClient) -> None:
    respx.get("https://example.com/slow").mock(side_effect=httpx.ReadTimeout("slow"))
    with pytest.raises(RetryableFetchError):
        await fetch_preview(http, "https://example.com/slow")


def test_unknown_host_detection() -> None:
    # respx rewrites exception chains, so check the real httpx chain directly.
    assert is_unknown_host(dns_error(socket.EAI_NONAME))
    # EAI_AGAIN is what we see when our own internet is down: that must not kill links.
    assert not is_unknown_host(dns_error(socket.EAI_AGAIN))
    assert not is_unknown_host(httpx.ConnectError("Connection refused"))


def test_unknown_host_detection_survives_cyclic_chains() -> None:
    first, second = ValueError("a"), ValueError("b")
    first.__context__, second.__context__ = second, first
    assert not is_unknown_host(first)


@respx.mock
async def test_fetch_unknown_host_is_dead(
    http: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(preview_module, "is_unknown_host", lambda exc: True)
    respx.get("https://no-such-site.example/").mock(side_effect=httpx.ConnectError("no"))
    with pytest.raises(DeadLinkError):
        await fetch_preview(http, "https://no-such-site.example/")


@respx.mock
async def test_oembed_provider_dns_failure_is_not_the_links_fault(
    http: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(preview_module, "is_unknown_host", lambda exc: True)
    respx.get(YOUTUBE_OEMBED_URL).mock(side_effect=httpx.ConnectError("no"))
    with pytest.raises(RetryableFetchError):
        await fetch_preview(http, "https://www.youtube.com/watch?v=dQw4w9WgXcQ")


@respx.mock
async def test_fetch_connection_refused_is_retryable(http: httpx.AsyncClient) -> None:
    respx.get("https://example.com/").mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(RetryableFetchError):
        await fetch_preview(http, "https://example.com/")


# --- fetch_preview: oEmbed ---

YOUTUBE_URL = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
TWEET_URL = "https://x.com/jack/status/20"


@respx.mock
async def test_youtube_uses_oembed(http: httpx.AsyncClient) -> None:
    route = respx.get(YOUTUBE_OEMBED_URL).respond(
        200,
        json={
            "title": "Never Gonna Give You Up",
            "author_name": "Rick Astley",
            "provider_name": "YouTube",
            "thumbnail_url": "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg",
        },
    )
    preview = await fetch_preview(http, YOUTUBE_URL)

    assert route.calls.last.request.url.params["url"] == YOUTUBE_URL
    assert preview == Preview(
        title="Never Gonna Give You Up",
        description="Rick Astley",
        image_url="https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg",
        site_name="YouTube",
    )


@respx.mock
async def test_youtube_removed_video_is_dead(http: httpx.AsyncClient) -> None:
    respx.get(YOUTUBE_OEMBED_URL).respond(404)
    with pytest.raises(DeadLinkError):
        await fetch_preview(http, YOUTUBE_URL)


@respx.mock
async def test_youtube_oembed_refusal_falls_back_to_page(http: httpx.AsyncClient) -> None:
    respx.get(YOUTUBE_OEMBED_URL).respond(401)
    respx.get(YOUTUBE_URL).respond(200, html='<meta property="og:title" content="From page">')
    assert (await fetch_preview(http, YOUTUBE_URL)).title == "From page"


@respx.mock
async def test_youtube_oembed_server_error_is_retryable(http: httpx.AsyncClient) -> None:
    respx.get(YOUTUBE_OEMBED_URL).respond(503)
    with pytest.raises(RetryableFetchError):
        await fetch_preview(http, YOUTUBE_URL)


TWEET_OEMBED = {
    "author_name": "jack",
    "author_url": "https://twitter.com/jack",
    "html": (
        '<blockquote class="twitter-tweet"><p lang="en" dir="ltr">just setting up my'
        " twttr<br>second line &amp; more</p>&mdash; jack (@jack) "
        '<a href="https://twitter.com/jack/status/20">March 21, 2006</a></blockquote>'
    ),
}


@respx.mock
async def test_tweet_uses_oembed_text_and_page_image(http: httpx.AsyncClient) -> None:
    route = respx.get(X_OEMBED_URL).respond(200, json=TWEET_OEMBED)
    respx.get(TWEET_URL).respond(
        200,
        html='<meta property="og:title" content="jack on X">'
        '<meta property="og:image" content="https://pbs.twimg.com/media/abc.jpg">',
    )
    preview = await fetch_preview(http, TWEET_URL)

    assert route.calls.last.request.url.params["url"] == TWEET_URL
    # Title and text from oEmbed, image from the page.
    assert preview == Preview(
        title="@jack: just setting up my twttr",
        description="just setting up my twttr second line & more",
        image_url="https://pbs.twimg.com/media/abc.jpg",
        site_name="X",
    )


@respx.mock
@pytest.mark.parametrize(
    "page",
    [httpx.Response(403), httpx.Response(404), httpx.Response(200, html="<title>X</title>")],
    ids=["blocked", "404", "no-image"],
)
async def test_tweet_without_page_image_still_has_oembed_text(
    http: httpx.AsyncClient, page: httpx.Response
) -> None:
    respx.get(X_OEMBED_URL).respond(200, json=TWEET_OEMBED)
    respx.get(TWEET_URL).mock(return_value=page)

    preview = await fetch_preview(http, TWEET_URL)
    assert preview.title == "@jack: just setting up my twttr"
    assert preview.image_url is None


@respx.mock
async def test_tweet_page_timeout_does_not_fail_the_tweet(http: httpx.AsyncClient) -> None:
    respx.get(X_OEMBED_URL).respond(200, json=TWEET_OEMBED)
    respx.get(TWEET_URL).mock(side_effect=httpx.ReadTimeout("slow"))
    assert (await fetch_preview(http, TWEET_URL)).title == "@jack: just setting up my twttr"


@respx.mock
async def test_oembed_follows_endpoint_redirects(http: httpx.AsyncClient) -> None:
    # publish.twitter.com answers every request with a 301 to publish.x.com.
    respx.get("https://publish.x.com/moved").respond(
        301, headers={"Location": X_OEMBED_URL + "?url=" + TWEET_URL}
    )
    respx.get(X_OEMBED_URL).respond(200, json=TWEET_OEMBED)
    data = await preview_module._fetch_oembed(
        http, "https://publish.x.com/moved", {"url": TWEET_URL}
    )
    assert data == TWEET_OEMBED


@respx.mock
async def test_deleted_tweet_is_dead(http: httpx.AsyncClient) -> None:
    respx.get(X_OEMBED_URL).respond(404)
    with pytest.raises(DeadLinkError):
        await fetch_preview(http, TWEET_URL)


# --- resolve_short_link ---


@respx.mock
async def test_resolve_short_link_stops_at_first_non_shortener(http: httpx.AsyncClient) -> None:
    respx.get("https://bit.ly/abc").respond(301, headers={"Location": "https://t.co/xyz"})
    respx.get("https://t.co/xyz").respond(
        301, headers={"Location": "https://example.com/post?utm_source=tw"}
    )
    # The target itself is never requested (respx would fail on an unmocked route).
    assert await resolve_short_link(http, "https://bit.ly/abc") == (
        "https://example.com/post?utm_source=tw"
    )


@respx.mock
async def test_resolve_short_link_without_redirect_keeps_url(http: httpx.AsyncClient) -> None:
    respx.get("https://bit.ly/landing").respond(200, html="<title>Bitly</title>")
    assert await resolve_short_link(http, "https://bit.ly/landing") == "https://bit.ly/landing"


@respx.mock
async def test_resolve_unknown_short_link_is_dead(http: httpx.AsyncClient) -> None:
    respx.get("https://bit.ly/nope").respond(404)
    with pytest.raises(DeadLinkError):
        await resolve_short_link(http, "https://bit.ly/nope")


@respx.mock
async def test_resolve_short_link_loop_is_retryable(http: httpx.AsyncClient) -> None:
    respx.get("https://bit.ly/a").respond(301, headers={"Location": "https://bit.ly/b"})
    respx.get("https://bit.ly/b").respond(301, headers={"Location": "https://bit.ly/a"})
    with pytest.raises(RetryableFetchError):
        await resolve_short_link(http, "https://bit.ly/a")
