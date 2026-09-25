import pytest

from app.models import ContentType
from app.services.classify import classify


@pytest.mark.parametrize(
    ("url", "og_type", "expected"),
    [
        ("https://x.com/jack/status/20", None, ContentType.TWEET),
        ("https://twitter.com/jack/status/20", None, ContentType.TWEET),
        ("https://x.com/jack", None, ContentType.OTHER),
        ("https://www.instagram.com/p/C9abc", None, ContentType.INSTAGRAM),
        ("https://www.instagram.com/reel/C9abc", None, ContentType.INSTAGRAM),
        ("https://www.instagram.com/chefasha", None, ContentType.OTHER),
        ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", None, ContentType.YOUTUBE),
        ("https://youtu.be/dQw4w9WgXcQ", None, ContentType.YOUTUBE),
        ("https://www.youtube.com/shorts/abc123", None, ContentType.YOUTUBE),
        ("https://www.youtube.com/@channel", None, ContentType.OTHER),
        ("https://github.com/astral-sh/uv", None, ContentType.GITHUB_REPO),
        ("https://github.com/astral-sh/uv/issues/12", None, ContentType.GITHUB_REPO),
        ("https://github.com/astral-sh", None, ContentType.OTHER),
        ("https://github.com/features/actions", None, ContentType.OTHER),
        ("https://gist.github.com/a/b", None, ContentType.OTHER),
        ("https://requests.readthedocs.io/en/latest", None, ContentType.DOCS),
        ("https://docs.python.org/3/library/asyncio.html", None, ContentType.DOCS),
        ("https://developer.mozilla.org/en-US/docs/Web", None, ContentType.DOCS),
        ("https://developer.apple.com/documentation", None, ContentType.DOCS),
        ("https://www.amazon.in/dp/B0C123", None, ContentType.PRODUCT),
        ("https://amazon.co.uk/dp/B0C123", None, ContentType.PRODUCT),
        ("https://www.flipkart.com/item/p/itm123", None, ContentType.PRODUCT),
        ("https://notamazon.example.com/x", None, ContentType.OTHER),
        # Domain rules win over og:type; og:type only decides "article".
        ("https://github.com/astral-sh/uv", "article", ContentType.GITHUB_REPO),
        ("https://example.com/post", "article", ContentType.ARTICLE),
        ("https://example.com/post", " Article ", ContentType.ARTICLE),
        ("https://example.com/post", "website", ContentType.OTHER),
        ("https://example.com/post", None, ContentType.OTHER),
    ],
)
def test_classify(url: str, og_type: str | None, expected: ContentType) -> None:
    assert classify(url, og_type) is expected
