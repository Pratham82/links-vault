from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse

from app.auth import require_api_key
from app.config import Settings, get_settings
from app.services.thumbnails import FILENAME_RE

router = APIRouter(
    prefix="/thumbnails", tags=["thumbnails"], dependencies=[Depends(require_api_key)]
)


@router.get("/{filename}", response_class=FileResponse)
async def read_thumbnail(
    filename: str, settings: Annotated[Settings, Depends(get_settings)]
) -> FileResponse:
    # Only names the worker generates, so "../" and friends never reach the filesystem.
    path = settings.thumbnail_dir / filename
    if not FILENAME_RE.fullmatch(filename) or not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Thumbnail not found")
    # A thumbnail never changes for a given name, so clients may cache it for a long time.
    return FileResponse(path, headers={"Cache-Control": "private, max-age=31536000, immutable"})
