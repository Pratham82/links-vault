"""Shared ingestion path for every adapter (API, Telegram, WhatsApp import).

Phase 0 implements extract → save. Normalization and dedupe arrive in Phase 2 and plug in
here, so adapters never need to change.
"""

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Link, SourceChannel

# Anything that starts with http(s):// up to the next whitespace.
_URL_RE = re.compile(r"https?://[^\s<>\"]+", re.IGNORECASE)
# Punctuation that usually belongs to the sentence, not the URL ("see https://x.com/a.").
_TRAILING_PUNCTUATION = ".,;:!?'\"*"
_BRACKET_PAIRS = {")": "(", "]": "[", "}": "{"}


class NoUrlsFoundError(ValueError):
    """Raised when a message contains no http(s) URLs."""


@dataclass
class ExtractedMessage:
    urls: list[str]
    note: str | None


@dataclass
class IngestOutcome:
    created: list[Link] = field(default_factory=list)
    duplicates: list[Link] = field(default_factory=list)


def _strip_trailing(url: str) -> str:
    while url:
        last = url[-1]
        if last in _TRAILING_PUNCTUATION:
            url = url[:-1]
        elif last in _BRACKET_PAIRS and url.count(last) > url.count(_BRACKET_PAIRS[last]):
            # Drop an unbalanced closing bracket: "(see https://a.com/x)" → "https://a.com/x",
            # but keep "https://en.wikipedia.org/wiki/Foo_(bar)".
            url = url[:-1]
        else:
            break
    return url


def extract(text: str) -> ExtractedMessage:
    """Split a message into its URLs (in order, de-duplicated) and the leftover note text."""
    urls: list[str] = []
    for match in _URL_RE.finditer(text):
        url = _strip_trailing(match.group(0))
        if url and url not in urls:
            urls.append(url)

    remainder = text
    for url in urls:
        remainder = remainder.replace(url, " ")
    note = " ".join(remainder.split()) or None
    return ExtractedMessage(urls=urls, note=note)


async def ingest_message(
    session: AsyncSession,
    *,
    text: str,
    source_channel: SourceChannel,
    sender: str,
    shared_at: datetime | None = None,
) -> IngestOutcome:
    """Store every URL in `text` as a pending link. Commits the session."""
    extracted = extract(text)
    if not extracted.urls:
        raise NoUrlsFoundError("No http(s) URLs found in text")

    shared_at = (shared_at or datetime.now(UTC)).astimezone(UTC)
    outcome = IngestOutcome()
    for url in extracted.urls:
        link = Link(
            url=url,
            # Phase 2 replaces this with real normalization (tracking params, short links…).
            normalized_url=url,
            source_channel=source_channel,
            sender=sender,
            note=extracted.note,
            shared_at=shared_at,
        )
        session.add(link)
        outcome.created.append(link)

    await session.commit()
    for link in outcome.created:
        # Load server-generated columns (created_at, updated_at) after the INSERT.
        await session.refresh(link)
    return outcome
