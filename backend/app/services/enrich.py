"""Enrichment: the work the worker does for each pending link.

The queue is the `links` table itself. A link is due when it is `pending` or `failed`, has
attempts left, and its `next_attempt_at` is empty or in the past.

Claiming uses a lease: in one short transaction the worker locks due rows with
`FOR UPDATE SKIP LOCKED`, bumps `enrich_attempts`, and pushes `next_attempt_at` a few
minutes out, then commits. The HTTP fetching happens after that, outside any transaction.
If the worker crashes mid-fetch, the lease simply expires and the link becomes due again.
"""

import logging
import uuid
from datetime import timedelta
from pathlib import Path

import httpx
from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import LIVE_LINKS, Link, LinkStatus
from app.services.classify import classify
from app.services.normalize import is_short_link, normalize_url
from app.services.preview import (
    DeadLinkError,
    FetchError,
    fetch_preview,
    resolve_short_link,
)
from app.services.thumbnails import cache_thumbnail

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 3
# How long a claimed link is reserved for the worker that claimed it.
LEASE = timedelta(minutes=5)
# Wait after the 1st and 2nd failure: 1 minute, then 5 minutes.
_RETRY_BASE = timedelta(minutes=1)
_RETRY_FACTOR = 5


def retry_delay(attempts: int) -> timedelta:
    return _RETRY_BASE * _RETRY_FACTOR ** (attempts - 1)


async def claim_due_links(session: AsyncSession, limit: int) -> list[uuid.UUID]:
    """Lease up to `limit` due links to this worker and return their ids. Commits."""
    due = (
        select(Link.id)
        .where(
            Link.status.in_([LinkStatus.PENDING, LinkStatus.FAILED]),
            Link.enrich_attempts < MAX_ATTEMPTS,
            or_(Link.next_attempt_at.is_(None), Link.next_attempt_at <= func.now()),
        )
        .order_by(Link.created_at)
        .limit(limit)
        # SKIP LOCKED: rows another worker is claiming right now are skipped instead of
        # waited on, so two workers never claim the same link.
        .with_for_update(skip_locked=True)
    )
    claim = (
        update(Link)
        .where(Link.id.in_(due.scalar_subquery()))
        .values(
            enrich_attempts=Link.enrich_attempts + 1,
            next_attempt_at=func.now() + LEASE,
        )
        .returning(Link.id)
        .execution_options(synchronize_session=False)
    )
    ids = list((await session.scalars(claim)).all())
    await session.commit()
    return ids


def _join_notes(first: str | None, second: str | None) -> str | None:
    if not second or second == first:
        return first
    if not first:
        return second
    return f"{first}\n{second}"


async def _merge_into_existing(session: AsyncSession, link: Link, normalized_url: str) -> bool:
    """If another live link already has `normalized_url`, fold `link` into it and delete it."""
    existing = await session.scalar(
        select(Link)
        .where(Link.normalized_url == normalized_url, LIVE_LINKS, Link.id != link.id)
        .with_for_update()
    )
    if existing is None:
        await session.commit()  # nothing to change; just release the connection
        return False
    existing.share_count += link.share_count
    existing.note = _join_notes(existing.note, link.note)
    existing.shared_at = min(existing.shared_at, link.shared_at)
    await session.delete(link)
    await session.commit()
    logger.info("Short link %s is a duplicate of link %s; merged", link.url, existing.id)
    return True


async def enrich_link(
    session: AsyncSession, http: httpx.AsyncClient, link_id: uuid.UUID, *, thumbnail_dir: Path
) -> None:
    """Resolve, fetch, classify and save one claimed link. Commits."""
    # populate_existing: always read the row fresh (the claim just changed enrich_attempts).
    link = await session.get(Link, link_id, populate_existing=True)
    if link is None:
        return
    # End the read transaction so no DB connection is held during the HTTP calls below.
    await session.commit()

    try:
        if is_short_link(link.normalized_url):
            target = normalize_url(await resolve_short_link(http, link.normalized_url))
            if target != link.normalized_url:
                if await _merge_into_existing(session, link, target):
                    return
                link.normalized_url = target
        preview = await fetch_preview(http, link.normalized_url)
    except DeadLinkError as exc:
        logger.info("Link %s is dead: %s", link.id, exc)
        link.status = LinkStatus.DEAD
        link.next_attempt_at = None
    except FetchError as exc:
        retry = link.enrich_attempts < MAX_ATTEMPTS
        logger.info(
            "Link %s failed (attempt %d/%d%s): %s",
            link.id,
            link.enrich_attempts,
            MAX_ATTEMPTS,
            ", will retry" if retry else ", giving up",
            exc,
        )
        link.status = LinkStatus.FAILED
        link.next_attempt_at = func.now() + retry_delay(link.enrich_attempts) if retry else None
    else:
        link.title = preview.title
        link.description = preview.description
        link.site_name = preview.site_name
        link.content_type = classify(link.normalized_url, preview.og_type)
        link.image_url = preview.image_url
        if preview.image_url:
            cached = await cache_thumbnail(http, preview.image_url, thumbnail_dir, link.id)
            link.image_url = cached or preview.image_url
        link.status = LinkStatus.ENRICHED
        link.next_attempt_at = None
    await session.commit()
