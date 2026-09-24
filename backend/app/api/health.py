from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.schemas import Health

router = APIRouter(tags=["health"])


@router.get("/health", response_model=Health)
async def health(session: Annotated[AsyncSession, Depends(get_session)]) -> Health | JSONResponse:
    try:
        await session.execute(text("SELECT 1"))
    except (SQLAlchemyError, OSError):
        return JSONResponse(
            status_code=503,
            content=Health(status="error", database="unreachable").model_dump(),
        )
    return Health(status="ok", database="ok")
