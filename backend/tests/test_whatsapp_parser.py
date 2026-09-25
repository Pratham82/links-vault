"""WhatsApp export parsing: both platforms, clocks, system lines and date order."""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from app.services.whatsapp_parser import DateOrder, DateOrderError, parse_chat
from tests.conftest import BACKEND_DIR

FIXTURES = BACKEND_DIR / "tests" / "fixtures" / "whatsapp"
KOLKATA = ZoneInfo("Asia/Kolkata")


def fixture(name: str) -> str:
    # newline="" keeps the CRLF fixture's line endings as they are in a real export.
    with open(FIXTURES / name, encoding="utf-8-sig", newline="") as file:
        return file.read()


def parse(text: str, date_order: DateOrder = DateOrder.DMY, tz: ZoneInfo = KOLKATA):
    return parse_chat(text, date_order=date_order, tz=tz)


def summary(text: str, **kwargs) -> list[tuple[str, str, str]]:
    return [(m.sent_at.isoformat(), m.sender, m.text) for m in parse(text, **kwargs).messages]


def test_android_export() -> None:
    result = parse(fixture("android.txt"))

    assert result.unparseable_lines == 0
    assert [(m.sent_at.isoformat(), m.sender, m.text) for m in result.messages] == [
        (
            "2026-09-24T22:15:00+05:30",
            "Prathamesh",
            "check this https://github.com/astral-sh/uv?utm_source=share",
        ),
        (
            "2026-09-24T22:16:00+05:30",
            "Prathamesh",
            "two links in one message\nhttps://x.com/someone/status/123?s=20\n"
            "and https://example.com/post\nworth reading later",
        ),
        ("2026-09-25T00:05:00+05:30", "Alex", "no link here, just chatting"),
        # "<This message was edited>" is dropped.
        (
            "2026-09-25T12:30:00+05:30",
            "+91 98765 43210",
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ&si=abc",
        ),
        # The attachment line goes, its caption stays.
        (
            "2026-09-25T13:02:00+05:30",
            "Prathamesh",
            "the caption has a link https://example.com/caption",
        ),
    ]
    # Line numbers point at the message's first line in the file.
    assert [m.line for m in result.messages] == [3, 4, 11, 12, 13]


def test_ios_export() -> None:
    result = parse(fixture("ios.txt"))

    assert result.unparseable_lines == 0
    assert [(m.sent_at.isoformat(), m.sender, m.text) for m in result.messages] == [
        (
            "2026-09-24T22:15:32+05:30",
            "Prathamesh",
            "check this https://github.com/astral-sh/uv?utm_source=share",
        ),
        (
            "2026-09-24T22:16:05+05:30",
            "Prathamesh",
            "two links in one message\nhttps://x.com/someone/status/123?s=20\n"
            "and https://example.com/post\nworth reading later",
        ),
        # "~ " (not in contacts) is stripped from the name.
        ("2026-09-25T00:05:00+05:30", "Alex", "no link here, just chatting"),
        # Directional marks around phone numbers are stripped.
        (
            "2026-09-25T12:30:45+05:30",
            "+91 98765 43210",
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ&si=abc",
        ),
    ]


def test_24_hour_clock_two_digit_years_and_unparseable_lines() -> None:
    result = parse(fixture("android_24h.txt"))

    assert [(m.sent_at.isoformat(), m.text) for m in result.messages] == [
        ("2026-09-24T22:15:00+05:30", "https://github.com/astral-sh/uv"),
        ("2026-09-25T00:05:00+05:30", "https://example.com/after-midnight"),
    ]
    # The leading junk line, the impossible date, and that message's continuation line.
    assert result.unparseable_lines == 3
    assert result.errors == [
        "line 1: no date, and not part of a message we could read",
        "line 3: 30/02/26 is not a valid date",
        "line 4: no date, and not part of a message we could read",
    ]


def test_dates_that_only_fit_another_order_stop_the_parse() -> None:
    with pytest.raises(DateOrderError, match=r"line 2: 09/24/2026 .* date_order=MDY"):
        parse(fixture("android_mdy.txt"))


def test_month_first_export_with_date_order_mdy() -> None:
    result = parse(fixture("android_mdy.txt"), date_order=DateOrder.MDY)
    assert [m.sent_at.date().isoformat() for m in result.messages] == ["2026-09-05", "2026-09-24"]


def test_date_order_decides_ambiguous_dates() -> None:
    text = "04/09/2026, 10:15 - A: https://a.com\n"
    assert summary(text)[0][0].startswith("2026-09-04")
    assert summary(text, date_order=DateOrder.MDY)[0][0].startswith("2026-04-09")


def test_year_first_dates() -> None:
    text = "2026-09-24, 22:15 - A: https://a.com\n"
    assert summary(text, date_order=DateOrder.YMD)[0][0] == "2026-09-24T22:15:00+05:30"
    # A four-digit first field can't be a day, so the error points at YMD.
    with pytest.raises(DateOrderError, match="date_order=YMD"):
        parse(text)


@pytest.mark.parametrize(
    ("clock", "expected"),
    [
        ("12:05 am", "00:05"),
        ("12:05 pm", "12:05"),
        ("1:05 PM", "13:05"),
        ("11:59\u202fp.m.", "23:59"),
        ("9:05\u202fa. m.", "09:05"),
        ("00:05", "00:05"),
        ("23:59", "23:59"),
    ],
)
def test_clock_formats(clock: str, expected: str) -> None:
    [(sent_at, _, _)] = summary(f"24/09/2026, {clock} - A: https://a.com\n")
    assert sent_at == f"2026-09-24T{expected}:00+05:30"


@pytest.mark.parametrize("clock", ["13:05 pm", "0:05 am", "24:00", "10:61"])
def test_impossible_times_are_unparseable(clock: str) -> None:
    result = parse(f"24/09/2026, {clock} - A: https://a.com\n")
    assert result.messages == []
    assert result.unparseable_lines == 1


def test_times_are_read_in_the_given_timezone() -> None:
    text = "24/09/2026, 10:15 pm - A: https://a.com\n"
    [message] = parse(text, tz=ZoneInfo("America/New_York")).messages
    assert message.sent_at.astimezone(UTC) == datetime(2026, 9, 25, 2, 15, tzinfo=UTC)


def test_continuation_lines_of_system_messages_are_ignored() -> None:
    text = (
        "24/09/2026, 10:15 - A changed the group description\n"
        "a description line\n"
        "24/09/2026, 10:16 - A: https://a.com\n"
    )
    result = parse(text)
    assert [m.text for m in result.messages] == ["https://a.com"]
    assert result.unparseable_lines == 0


def test_message_starting_on_the_next_line() -> None:
    text = "24/09/2026, 10:15 - A:\nhttps://a.com\n"
    assert summary(text) == [("2026-09-24T10:15:00+05:30", "A", "https://a.com")]


def test_blank_lines_are_kept_inside_messages_but_trimmed_at_the_end() -> None:
    text = "24/09/2026, 10:15 - A: first\n\nhttps://a.com\n\n"
    assert [m.text for m in parse(text).messages] == ["first\n\nhttps://a.com"]


def test_empty_file() -> None:
    result = parse("")
    assert result.messages == []
    assert result.unparseable_lines == 0
