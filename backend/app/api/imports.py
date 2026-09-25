from typing import Annotated
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import require_api_key
from app.db import get_session
from app.schemas import ImportOut, ImportReport
from app.services import imports
from app.services.whatsapp_parser import DateOrder, DateOrderError

router = APIRouter(tags=["imports"], dependencies=[Depends(require_api_key)])

SessionDep = Annotated[AsyncSession, Depends(get_session)]

# WhatsApp writes times in the phone's local time, without saying which zone that is.
DEFAULT_TIMEZONE = "Asia/Kolkata"


def _zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Unknown timezone {name!r}; use an IANA name like Asia/Kolkata",
        ) from exc


@router.post("/import/whatsapp", status_code=status.HTTP_201_CREATED)
async def import_whatsapp(
    file: UploadFile,
    session: SessionDep,
    date_order: Annotated[
        DateOrder, Query(description="How the export writes dates: DMY is 24/09/2026")
    ] = DateOrder.DMY,
    timezone: Annotated[
        str, Query(description="IANA timezone of the phone that exported the chat")
    ] = DEFAULT_TIMEZONE,
) -> ImportReport:
    tz = _zone(timezone)
    data = await file.read(imports.MAX_UPLOAD_BYTES + 1)
    if len(data) > imports.MAX_UPLOAD_BYTES:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE,
            detail=f"Uploads are limited to {imports.MAX_UPLOAD_BYTES // (1024 * 1024)} MB",
        )
    filename = (file.filename or "upload").rsplit("/", 1)[-1][:255]
    try:
        record, stats = await imports.import_whatsapp(
            session, filename=filename, data=data, date_order=date_order, tz=tz
        )
    except imports.ImportTooLargeError as exc:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, detail=str(exc)) from exc
    except (imports.ImportFileError, DateOrderError) as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    return ImportReport(
        id=record.id,
        filename=record.filename,
        messages=stats.messages,
        links_found=stats.links_found,
        created=stats.created,
        duplicates=stats.duplicates,
        unparseable_lines=stats.unparseable_lines,
        sample_errors=stats.sample_errors,
    )


@router.get("/imports")
async def read_imports(session: SessionDep) -> list[ImportOut]:
    return [ImportOut.model_validate(record) for record in await imports.list_imports(session)]
