"""Read-side queries for links."""

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ContentType, Link, SourceChannel


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
