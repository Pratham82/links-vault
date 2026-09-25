"""Parse a WhatsApp chat export ("Export chat → Without media") into messages.

Each platform writes its own line layout:

    Android: 24/09/2026, 10:15 pm - Name: message
    iOS:     [24/09/26, 10:15:32 PM] Name: message

A line that doesn't start with a timestamp continues the previous message. A timestamped
line without "Name: " (joins, leaves, the encryption notice) is a system line.

The timestamps carry no timezone, and whether 04/09 means 4 September or April 9 depends on
the phone's locale. The caller supplies both; the parser never guesses. If a date only makes
sense in another order (09/24/2026 read as DMY), it raises `DateOrderError` rather than
importing the rest of the file with day and month swapped.

Pure text processing: no database, no network.
"""

import enum
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

# Invisible marks WhatsApp sprinkles into exports: left-to-right/right-to-left marks,
# directional embeddings around phone numbers, and a byte-order mark at the top of the file.
_INVISIBLE = "\u200e\u200f\u202a\u202b\u202c\ufeff"
# iOS starts system messages and media placeholders with a left-to-right mark.
_IOS_SYSTEM_MARK = "\u200e"

_DATE = r"(?P<date>\d{1,4}[./-]\d{1,2}[./-]\d{1,4})"
_TIME = r"(?P<time>\d{1,2}:\d{2}(?::\d{2})?)"
# Newer exports put a narrow no-break space (\u202f) between the time and AM/PM.
_AM_PM = r"(?:[ \u202f\u00a0]?(?P<am_pm>[ap]\.?[ \u202f]?m\.?))?"
# Android separates the timestamp with " - " (some versions use an en dash).
_ANDROID_LINE = re.compile(rf"{_DATE},? {_TIME}{_AM_PM} [-\u2013] (?P<rest>.*)", re.IGNORECASE)
_IOS_LINE = re.compile(rf"\[{_DATE},? {_TIME}{_AM_PM}\] (?P<rest>.*)", re.IGNORECASE)

# Placeholder lines that stand in for something the text export doesn't contain.
_PLACEHOLDER_LINES = re.compile(
    r"<media omitted>|<attached: [^>]*>|.+ \(file attached\)"
    r"|(?:image|video|audio|sticker|gif|document|contact card) omitted"
    r"|this message was deleted|you deleted this message|waiting for this message|null",
    re.IGNORECASE,
)
_EDITED_MARKER = re.compile(r"\s*<this message was edited>", re.IGNORECASE)


class DateOrder(enum.StrEnum):
    """How the export writes dates: DMY is 24/09/2026, MDY is 09/24/2026."""

    DMY = "DMY"
    MDY = "MDY"
    YMD = "YMD"


class DateOrderError(ValueError):
    """The file's dates don't fit the requested day/month order."""


@dataclass
class ChatMessage:
    line: int
    sent_at: datetime
    sender: str
    text: str


@dataclass
class ParsedChat:
    messages: list[ChatMessage] = field(default_factory=list)
    unparseable_lines: int = 0
    # One human-readable reason per unparseable line, e.g. "line 3: 31/02/2026 is not a date".
    errors: list[str] = field(default_factory=list)


@dataclass
class _Draft:
    line: int
    sent_at: datetime
    sender: str
    lines: list[str]


def _parse_date(raw: str, order: DateOrder) -> date | None:
    first, second, third = re.split(r"[./-]", raw)
    match order:
        case DateOrder.DMY:
            day, month, year = first, second, third
        case DateOrder.MDY:
            month, day, year = first, second, third
        case DateOrder.YMD:
            # Year-first exports always write four digits (2026-09-24); requiring that
            # keeps 24/09/26 from also reading as a valid YMD date.
            year, month, day = first, second, third
            if len(year) != 4:
                return None
    if len(day) > 2 or len(month) > 2 or len(year) not in (2, 4):
        return None
    try:
        return date(int(year) + (2000 if len(year) == 2 else 0), int(month), int(day))
    except ValueError:
        return None


def _parse_time(raw: str, am_pm: str | None) -> time | None:
    hour, minute, *rest = (int(part) for part in raw.split(":"))
    second = rest[0] if rest else 0
    if am_pm:
        if not 1 <= hour <= 12:
            return None
        # 12:05 am is 00:05; 12:05 pm is 12:05.
        hour = hour % 12 + (12 if am_pm.lower().startswith("p") else 0)
    try:
        return time(hour, minute, second)
    except ValueError:
        return None


def _clean_sender(raw: str) -> str:
    sender = raw.strip().strip(_INVISIBLE)
    # iOS prefixes people who aren't in your contacts with "~ ".
    return sender.removeprefix("~").strip(" \u202f\u00a0" + _INVISIBLE)


def _message_text(lines: list[str]) -> str:
    """Join a message's lines, dropping media placeholders and system text."""
    kept: list[str] = []
    for line in lines:
        if line.startswith(_IOS_SYSTEM_MARK):
            continue
        line = _EDITED_MARKER.sub("", line)
        if _PLACEHOLDER_LINES.fullmatch(line.strip()):
            continue
        kept.append(line)
    return "\n".join(kept).strip()


def parse_chat(text: str, *, date_order: DateOrder, tz: ZoneInfo) -> ParsedChat:
    """Parse a whole export. Message times are read as local times in `tz`.

    Raises `DateOrderError` if a date is impossible in `date_order` but valid in another order.
    """
    result = ParsedChat()
    draft: _Draft | None = None
    # False before the first message, and after a timestamp line we couldn't read, so its
    # continuation lines are dropped with it instead of joining the previous message.
    in_message = False

    def finish() -> None:
        if draft is None:
            return
        body = _message_text(draft.lines)
        if body:
            result.messages.append(ChatMessage(draft.line, draft.sent_at, draft.sender, body))

    def reject(number: int, reason: str) -> None:
        result.unparseable_lines += 1
        result.errors.append(f"line {number}: {reason}")

    for number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.lstrip(_INVISIBLE)
        header = _ANDROID_LINE.fullmatch(line) or _IOS_LINE.fullmatch(line)
        if header is None:
            if draft is not None:
                draft.lines.append(raw_line)
            elif not in_message and raw_line.strip():
                reject(number, "no date, and not part of a message we could read")
            continue

        finish()
        draft = None
        in_message = False

        raw_date = header["date"]
        day = _parse_date(raw_date, date_order)
        if day is None:
            fits = [order for order in DateOrder if _parse_date(raw_date, order) is not None]
            if fits:
                raise DateOrderError(
                    f"line {number}: {raw_date} is not a valid {date_order} date, but is "
                    f"valid as {' or '.join(fits)}. Import again with date_order={fits[0]}."
                )
            reject(number, f"{raw_date} is not a valid date")
            continue
        clock = _parse_time(header["time"], header["am_pm"])
        if clock is None:
            reject(number, f"{header['time']} {header['am_pm'] or ''} is not a valid time")
            continue

        in_message = True
        rest = header["rest"]
        sender, separator, body = rest.partition(": ")
        if not separator and rest.endswith(":"):
            # "Alice:" with the text starting on the next line.
            sender, separator, body = rest[:-1], ":", ""
        if not separator:
            continue  # system line: "Alice joined using this group's invite link"
        draft = _Draft(
            line=number,
            sent_at=datetime.combine(day, clock, tzinfo=tz),
            sender=_clean_sender(sender),
            lines=[body],
        )

    finish()
    return result
