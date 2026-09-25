import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import AwareDatetime
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import require_api_key
from app.config import Settings, get_settings
from app.db import get_session
from app.models import ContentType, SourceChannel
from app.schemas import IngestResult, LinkIngest, LinkOut, LinkPage, LinkUpdate
from app.services import ingest
from app.services.links import LinkFilters, delete_link, get_link, list_links, update_link

router = APIRouter(prefix="/links", tags=["links"], dependencies=[Depends(require_api_key)])

SessionDep = Annotated[AsyncSession, Depends(get_session)]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_links(body: LinkIngest, session: SessionDep) -> IngestResult:
    try:
        outcome = await ingest.ingest_message(
            session,
            text=body.text,
            source_channel=body.source_channel,
            sender=body.sender,
            shared_at=body.shared_at,
        )
    except ingest.NoUrlsFoundError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    return IngestResult(
        created=[LinkOut.model_validate(link) for link in outcome.created],
        duplicates=[LinkOut.model_validate(link) for link in outcome.duplicates],
    )


@router.get("")
async def read_links(
    session: SessionDep,
    type: Annotated[ContentType | None, Query()] = None,
    tag: Annotated[str | None, Query()] = None,
    source: Annotated[SourceChannel | None, Query()] = None,
    shared_from: Annotated[
        AwareDatetime | None, Query(alias="from", description="Inclusive, by shared_at")
    ] = None,
    shared_to: Annotated[
        AwareDatetime | None, Query(alias="to", description="Exclusive, by shared_at")
    ] = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> LinkPage:
    filters = LinkFilters(
        content_type=type,
        tag=tag,
        source=source,
        shared_from=shared_from,
        shared_to=shared_to,
        q=q,
    )
    items, total = await list_links(session, filters, limit=limit, offset=offset)
    return LinkPage(
        items=[LinkOut.model_validate(link) for link in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{link_id}")
async def read_link(link_id: uuid.UUID, session: SessionDep) -> LinkOut:
    link = await get_link(session, link_id)
    if link is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Link not found")
    return LinkOut.model_validate(link)


@router.patch("/{link_id}")
async def edit_link(link_id: uuid.UUID, body: LinkUpdate, session: SessionDep) -> LinkOut:
    changes = body.model_dump(exclude_unset=True)
    for field in ("tags", "content_type"):
        if field in changes and changes[field] is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, detail=f"{field} cannot be null"
            )
    link = await update_link(session, link_id, changes)
    if link is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Link not found")
    return LinkOut.model_validate(link)


@router.delete("/{link_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_link(
    link_id: uuid.UUID,
    session: SessionDep,
    settings: Annotated[Settings, Depends(get_settings)],
) -> Response:
    if not await delete_link(session, link_id, thumbnail_dir=settings.thumbnail_dir):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Link not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
