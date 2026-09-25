import pytest

from app.services.normalize import is_short_link, normalize_url


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://example.com/post", "https://example.com/post"),
        # Case, default ports, fragments, trailing slashes.
        ("HTTPS://Example.COM:443/Post/#comments", "https://example.com/Post"),
        ("http://example.com:80/", "http://example.com"),
        ("http://example.com:8080/a", "http://example.com:8080/a"),
        ("https://user:secret@example.com/a", "https://example.com/a"),
        # Tracking params go, everything else stays in its original order.
        (
            "https://example.com/p?utm_source=x&id=7&UTM_Medium=y&fbclid=abc&gclid=1&ref=hn",
            "https://example.com/p?id=7",
        ),
        ("https://example.com/search?q=a%20b&page=2", "https://example.com/search?q=a%20b&page=2"),
        ("https://example.com/p?igsh=abc&igshid=def&si=ghi&s=20", "https://example.com/p"),
        ("https://example.com/p?", "https://example.com/p"),
        # X / Twitter: one host, no query string.
        ("https://twitter.com/jack/status/20?s=20&t=abc", "https://x.com/jack/status/20"),
        ("https://mobile.twitter.com/jack/status/20", "https://x.com/jack/status/20"),
        ("https://www.x.com/jack/status/20/", "https://x.com/jack/status/20"),
        # Instagram: one host, no query string.
        (
            "https://instagram.com/reel/C9abc/?igsh=MWx0&utm_source=ig_web",
            "https://www.instagram.com/reel/C9abc",
        ),
        # YouTube: youtu.be expands, the share `si` param goes, `t` stays.
        (
            "https://youtu.be/dQw4w9WgXcQ?si=XyZ&t=42",
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=42",
        ),
        ("https://youtu.be/dQw4w9WgXcQ", "https://www.youtube.com/watch?v=dQw4w9WgXcQ"),
        (
            "https://m.youtube.com/watch?v=dQw4w9WgXcQ&feature=share",
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        ),
        ("https://youtube.com/shorts/abc123?si=x", "https://www.youtube.com/shorts/abc123"),
        # Short links that need the network keep their form; the worker resolves them.
        ("https://t.co/AbC123?amp=1", "https://t.co/AbC123?amp=1"),
        ("https://bit.ly/3xyz", "https://bit.ly/3xyz"),
        # A broken port doesn't blow up ingestion.
        ("https://example.com:abc/x", "https://example.com/x"),
    ],
)
def test_normalize_url(url: str, expected: str) -> None:
    assert normalize_url(url) == expected


def test_normalize_url_is_idempotent() -> None:
    url = "https://youtu.be/dQw4w9WgXcQ?si=XyZ&t=42"
    assert normalize_url(normalize_url(url)) == normalize_url(url)


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://t.co/AbC123", True),
        ("https://BIT.LY/3xyz", True),
        ("https://amzn.to/3abc", True),
        ("https://youtu.be/dQw4w9WgXcQ", False),
        ("https://example.com/t.co", False),
    ],
)
def test_is_short_link(url: str, expected: bool) -> None:
    assert is_short_link(url) is expected
