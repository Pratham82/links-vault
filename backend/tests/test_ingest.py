import pytest

from app.services.ingest import extract


@pytest.mark.parametrize(
    ("text", "urls", "note"),
    [
        ("https://example.com", ["https://example.com"], None),
        (
            "great read https://example.com/post?a=1 must try",
            ["https://example.com/post?a=1"],
            "great read must try",
        ),
        ("see https://example.com/a.", ["https://example.com/a"], "see ."),
        ("(via https://example.com/a)", ["https://example.com/a"], "(via )"),
        (
            "https://en.wikipedia.org/wiki/Foo_(bar)",
            ["https://en.wikipedia.org/wiki/Foo_(bar)"],
            None,
        ),
        (
            "two: https://a.com/1\nhttp://b.com/2 and https://a.com/1 again",
            ["https://a.com/1", "http://b.com/2"],
            "two: and again",
        ),
        ("HTTPS://EXAMPLE.COM/x", ["HTTPS://EXAMPLE.COM/x"], None),
        ("no links here", [], "no links here"),
        ("ftp://example.com is not http", [], "ftp://example.com is not http"),
    ],
)
def test_extract(text: str, urls: list[str], note: str | None) -> None:
    result = extract(text)
    assert result.urls == urls
    assert result.note == note
