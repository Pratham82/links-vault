from collections.abc import AsyncIterator

from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.db import get_session
from app.main import create_app


async def test_health_ok(client: AsyncClient) -> None:
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


async def test_health_does_not_require_api_key(client: AsyncClient) -> None:
    response = await client.get("/health", headers={"X-API-Key": ""})
    assert response.status_code == 200


async def test_health_reports_unreachable_database() -> None:
    # Nothing listens on port 1, so the connection is refused.
    engine = create_async_engine("postgresql+asyncpg://nobody:nothing@127.0.0.1:1/none")

    async def _broken_session() -> AsyncIterator[AsyncSession]:
        async with AsyncSession(engine) as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_session] = _broken_session
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/health")
    await engine.dispose()

    assert response.status_code == 503
    assert response.json() == {"status": "error", "database": "unreachable"}
