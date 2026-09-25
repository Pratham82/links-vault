"""Queries and edits for stored links (everything except ingestion and enrichment)."""

import asyncio
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ContentType, Link, SourceChannel
from app.services.thumbnails import FILENAME_RE, URL_PREFIX


@dataclass
class LinkFilters:
    content_type: ContentType | None = None
    tag: str | None = None
    source: SourceChannel | None = None
    shared_from: datetime | None = None
    shared_to: datetime | None = None
    q: str | None = None


def _apply_filters(stmt: Select, filters: LinkFilters) -> Select:
    if filters.content_type is not None:
        stmt = stmt.where(Link.content_type == filters.content_type)
    if filters.tag is not None:
        stmt = stmt.where(Link.tags.any(filters.tag))
    if filters.source is not None:
        stmt = stmt.where(Link.source_channel == filters.source)
    if filters.shared_from is not None:
        stmt = stmt.where(Link.shared_at >= filters.shared_from)
    if filters.shared_to is not None:
        stmt = stmt.where(Link.shared_at < filters.shared_to)
    if filters.q:
        # Escape LIKE wildcards so a search for "100%" matches literally.
        escaped = filters.q.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")
        pattern = f"%{escaped}%"
        stmt = stmt.where(
            or_(
                *(
                    column.ilike(pattern, escape="\\")
                    for column in (Link.url, Link.title, Link.description, Link.note)
                )
            )
        )
    return stmt


async def list_links(
    session: AsyncSession, filters: LinkFilters, *, limit: int, offset: int
) -> tuple[list[Link], int]:
    """Return one page of links (newest `shared_at` first) and the total matching count."""
    total_stmt = _apply_filters(select(func.count()).select_from(Link), filters)
    total = (await session.execute(total_stmt)).scalar_one()

    page_stmt = (
        _apply_filters(select(Link), filters)
        .order_by(Link.shared_at.desc(), Link.id)
        .limit(limit)
        .offset(offset)
    )
    items = list((await session.scalars(page_stmt)).all())
    return items, total


async def get_link(session: AsyncSession, link_id: uuid.UUID) -> Link | None:
    return await session.get(Link, link_id)


async def update_link(
    session: AsyncSession, link_id: uuid.UUID, changes: dict[str, Any]
) -> Link | None:
    """Apply `changes` (note / tags / content_type) to a link. Commits. None if not found."""
    link = await session.get(Link, link_id)
    if link is None:
        return None
    for field, value in changes.items():
        setattr(link, field, value)
    await session.commit()
    # Reload so updated_at (set by the database) is current.
    await session.refresh(link)
    return link


def _cached_thumbnail(link: Link, thumbnail_dir: Path) -> Path | None:
    if not link.image_url or not link.image_url.startswith(URL_PREFIX):
        return None
    filename = link.image_url.removeprefix(URL_PREFIX)
    return thumbnail_dir / filename if FILENAME_RE.fullmatch(filename) else None


async def delete_link(session: AsyncSession, link_id: uuid.UUID, *, thumbnail_dir: Path) -> bool:
    """Delete a link and its cached thumbnail. Commits. False if not found."""
    link = await session.get(Link, link_id)
    if link is None:
        return False
    thumbnail = _cached_thumbnail(link, thumbnail_dir)
    await session.delete(link)
    await session.commit()
    if thumbnail is not None:
        # After the commit: a leftover file is harmless, a link pointing at a missing one isn't.
        await asyncio.to_thread(thumbnail.unlink, missing_ok=True)
    return True
