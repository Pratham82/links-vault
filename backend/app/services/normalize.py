"""URL normalization: the dedupe key for every link.

Pure string work, no network. Short links that need an HTTP request to resolve (t.co,
bit.ly…) keep their short form here; the worker resolves them later so ingestion never
waits on the network. `youtu.be` is the exception: its target is in the URL itself.
"""

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# Query parameters that only say where a click came from, never what the page is.
_TRACKING_PARAMS = frozenset(
    {
        "fbclid",
        "gclid",
        "dclid",
        "msclkid",
        "yclid",
        "twclid",
        "mc_cid",
        "mc_eid",
        "igsh",
        "igshid",
        "si",
        "s",
        "ref",
        "ref_src",
        "ref_url",
        "feature",
        "_ga",
    }
)
_TRACKING_PREFIXES = ("utm_",)

# Different hostnames for the same site, mapped to the one we store.
_HOST_ALIASES = {
    "twitter.com": "x.com",
    "www.twitter.com": "x.com",
    "mobile.twitter.com": "x.com",
    "mobile.x.com": "x.com",
    "www.x.com": "x.com",
    "youtube.com": "www.youtube.com",
    "m.youtube.com": "www.youtube.com",
    "music.youtube.com": "www.youtube.com",
    "instagram.com": "www.instagram.com",
    "m.instagram.com": "www.instagram.com",
}

# Sites whose query strings are all tracking (?s=20&t=…, ?igsh=…), so we drop them whole.
_DROP_ALL_QUERY_HOSTS = frozenset({"x.com", "www.instagram.com"})

# Redirect-only hosts; the worker follows them to the real URL.
SHORT_LINK_HOSTS = frozenset(
    {"t.co", "bit.ly", "buff.ly", "tinyurl.com", "ow.ly", "amzn.to", "amzn.in", "lnkd.in"}
)

_DEFAULT_PORTS = {"http": 80, "https": 443}


def _is_tracking(key: str) -> bool:
    key = key.lower()
    return key in _TRACKING_PARAMS or key.startswith(_TRACKING_PREFIXES)


def normalize_url(url: str) -> str:
    """Return the canonical form of `url` used for dedupe.

    Lowercases scheme and host, drops default ports, fragments, tracking params and
    trailing slashes, unifies host aliases (twitter.com → x.com) and expands youtu.be.
    """
    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower()
    host = (parts.hostname or "").lower()
    host = _HOST_ALIASES.get(host, host)
    path = parts.path
    params = parse_qsl(parts.query, keep_blank_values=True)

    if host in _DROP_ALL_QUERY_HOSTS:
        kept: list[tuple[str, str]] = []
    else:
        kept = [(key, value) for key, value in params if not _is_tracking(key)]
    # Re-encode only when something was removed, so untouched URLs keep their exact query.
    query = parts.query if len(kept) == len(params) else urlencode(kept)

    if host == "youtu.be" and path.strip("/"):
        # youtu.be/ID?t=42 → www.youtube.com/watch?v=ID&t=42
        video_id = path.strip("/").split("/")[0]
        host, path = "www.youtube.com", "/watch"
        query = urlencode([("v", video_id), *kept])

    try:
        port = parts.port
    except ValueError:  # "example.com:abc" — keep going rather than reject the whole message
        port = None
    netloc = host
    if port is not None and port != _DEFAULT_PORTS.get(scheme):
        netloc = f"{host}:{port}"
    # userinfo (user:pass@) is dropped on purpose: it's never part of a page's identity.

    path = path.rstrip("/")
    return urlunsplit((scheme, netloc, path, query, ""))


def is_short_link(url: str) -> bool:
    return (urlsplit(url).hostname or "").lower() in SHORT_LINK_HOSTS
