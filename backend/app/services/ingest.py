"""Shared ingestion path for every adapter (API, Telegram, WhatsApp import).

extract → normalize → dedupe → save as `pending`. No network calls happen here: the worker
fetches previews (and resolves short links) later, so ingestion always returns quickly.

Dedupe depends on the channel. Live captures dedupe on `normalized_url` and a repeat share
bumps `share_count`. WhatsApp imports dedupe on `(normalized_url, shared_at)` and a repeat
changes nothing, so importing the same export twice is a no-op.
"""

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import case, func, literal_column, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import IMPORTED_LINKS, LIVE_LINKS, Link, SourceChannel
from app.services.classify import classify
from app.services.normalize import normalize_url

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


async def _upsert_live_link(
    session: AsyncSession,
    *,
    url: str,
    normalized_url: str,
    source_channel: SourceChannel,
    sender: str,
    note: str | None,
    shared_at: datetime,
) -> tuple[Link, bool]:
    """Insert a link, or bump the existing one with the same normalized_url.

    One `INSERT … ON CONFLICT DO UPDATE` statement, so two shares of the same URL arriving
    at the same moment can't both insert: Postgres serializes them on the unique index.
    Returns the row and whether it was newly inserted.
    """
    stmt = insert(Link).values(
        url=url,
        normalized_url=normalized_url,
        source_channel=source_channel,
        sender=sender,
        note=note,
        shared_at=shared_at,
        content_type=classify(normalized_url),
    )
    # `excluded` is the row we tried to insert; `Link.*` is the row already in the table.
    new_note = stmt.excluded.note
    stmt = stmt.on_conflict_do_update(
        index_elements=[Link.normalized_url],
        index_where=LIVE_LINKS,
        set_={
            "share_count": Link.share_count + 1,
            # Append the new note on its own line, unless it's empty or already there.
            "note": case(
                (or_(new_note.is_(None), Link.note == new_note), Link.note),
                (Link.note.is_(None), new_note),
                else_=Link.note + "\n" + new_note,
            ),
            "updated_at": func.now(),
        },
    )
    # xmax is a Postgres system column that is 0 for a freshly inserted row and non-zero
    # for one this statement updated, which tells created and duplicate apart.
    stmt = stmt.returning(Link, literal_column("xmax = 0").label("inserted"))
    # populate_existing: refresh the Link object if this session already holds it.
    result = await session.execute(stmt, execution_options={"populate_existing": True})
    link, inserted = result.one()
    return link, inserted


async def _insert_imported_link(
    session: AsyncSession,
    *,
    url: str,
    normalized_url: str,
    sender: str,
    note: str | None,
    shared_at: datetime,
) -> tuple[Link, bool]:
    """Insert an imported link unless the same link from the same moment is already stored.

    Returns the row and whether it was newly inserted. A repeat is left untouched.
    """
    # Matching on `url` too catches a short link the worker has resolved since the last
    # import: its normalized_url is now the target, but its url is still the t.co link.
    existing = await session.scalar(
        select(Link)
        .where(
            IMPORTED_LINKS,
            Link.shared_at == shared_at,
            or_(Link.normalized_url == normalized_url, Link.url == url),
        )
        .limit(1)
    )
    if existing is not None:
        return existing, False

    stmt = (
        insert(Link)
        .values(
            url=url,
            normalized_url=normalized_url,
            source_channel=SourceChannel.WHATSAPP_IMPORT,
            sender=sender,
            note=note,
            shared_at=shared_at,
            content_type=classify(normalized_url),
        )
        # The unique index is the real guarantee: if a concurrent import inserted the row
        # after our check, this inserts nothing instead of failing.
        .on_conflict_do_nothing(
            index_elements=[Link.normalized_url, Link.shared_at], index_where=IMPORTED_LINKS
        )
        .returning(Link)
    )
    result = await session.execute(stmt, execution_options={"populate_existing": True})
    link = result.scalar_one_or_none()
    if link is not None:
        return link, True
    existing = await session.scalar(
        select(Link).where(
            IMPORTED_LINKS, Link.normalized_url == normalized_url, Link.shared_at == shared_at
        )
    )
    assert existing is not None
    return existing, False


async def stage_message(
    session: AsyncSession,
    *,
    text: str,
    source_channel: SourceChannel,
    sender: str,
    shared_at: datetime | None = None,
) -> IngestOutcome:
    """Store every URL in `text` as a pending link, or match its duplicate. Doesn't commit.

    The WhatsApp import stages every message of an export this way and commits once, so a
    failed import leaves nothing behind.
    """
    extracted = extract(text)
    if not extracted.urls:
        raise NoUrlsFoundError("No http(s) URLs found in text")

    shared_at = (shared_at or datetime.now(UTC)).astimezone(UTC)
    # Two spellings of one URL in the same message (with/without utm_…) count once.
    by_normalized: dict[str, str] = {}
    for url in extracted.urls:
        by_normalized.setdefault(normalize_url(url), url)

    outcome = IngestOutcome()
    for normalized_url, url in by_normalized.items():
        if source_channel is SourceChannel.WHATSAPP_IMPORT:
            link, inserted = await _insert_imported_link(
                session,
                url=url,
                normalized_url=normalized_url,
                sender=sender,
                note=extracted.note,
                shared_at=shared_at,
            )
        else:
            link, inserted = await _upsert_live_link(
                session,
                url=url,
                normalized_url=normalized_url,
                source_channel=source_channel,
                sender=sender,
                note=extracted.note,
                shared_at=shared_at,
            )
        (outcome.created if inserted else outcome.duplicates).append(link)
    return outcome


async def ingest_message(
    session: AsyncSession,
    *,
    text: str,
    source_channel: SourceChannel,
    sender: str,
    shared_at: datetime | None = None,
) -> IngestOutcome:
    """Store every URL in `text` as a pending link, or match its duplicate. Commits."""
    outcome = await stage_message(
        session, text=text, source_channel=source_channel, sender=sender, shared_at=shared_at
    )
    await session.commit()
    return outcome
