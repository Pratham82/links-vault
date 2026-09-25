"""Deterministic content-type rules (README "Content type rules"). No network, no LLM."""

import re
from urllib.parse import urlsplit

from app.models import ContentType

# github.com/<first segment> values that are GitHub pages, not user or org names.
_GITHUB_RESERVED = frozenset(
    {
        "about",
        "apps",
        "collections",
        "customer-stories",
        "enterprise",
        "events",
        "explore",
        "features",
        "login",
        "marketplace",
        "new",
        "notifications",
        "orgs",
        "pricing",
        "readme",
        "search",
        "security",
        "settings",
        "site",
        "sponsors",
        "topics",
        "trending",
        "users",
    }
)
# amazon.com, amazon.in, amazon.co.uk, smile.amazon.com…
_AMAZON_RE = re.compile(r"(^|\.)amazon\.[a-z.]+$")
_SHOP_HOSTS = frozenset({"flipkart.com", "myntra.com", "etsy.com"})


def _host_matches(host: str, domain: str) -> bool:
    return host == domain or host.endswith(f".{domain}")


def classify(url: str, og_type: str | None = None) -> ContentType:
    """Pick a content type from the (normalized) URL, then from the page's `og:type`."""
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    segments = [segment for segment in parts.path.split("/") if segment]

    if host in {"x.com", "twitter.com"} and "status" in segments:
        return ContentType.TWEET
    if _host_matches(host, "instagram.com") and segments[:1] in (["p"], ["reel"], ["reels"]):
        return ContentType.INSTAGRAM
    if host == "youtu.be" or (
        _host_matches(host, "youtube.com")
        and (parts.path == "/watch" or segments[:1] == ["shorts"])
    ):
        return ContentType.YOUTUBE
    if host in {"github.com", "www.github.com"} and (
        len(segments) >= 2 and segments[0].lower() not in _GITHUB_RESERVED
    ):
        return ContentType.GITHUB_REPO
    # "developer." also covers MDN (developer.mozilla.org).
    if host.endswith(".readthedocs.io") or host.startswith(("docs.", "developer.")):
        return ContentType.DOCS
    if _AMAZON_RE.search(host) or any(_host_matches(host, shop) for shop in _SHOP_HOSTS):
        return ContentType.PRODUCT
    if og_type is not None and og_type.strip().lower() == "article":
        return ContentType.ARTICLE
    return ContentType.OTHER
