import pytest
from httpx import ASGITransport, AsyncClient

from app.config import Settings
from app.main import create_app

DOC_PATHS = ["/docs", "/redoc", "/openapi.json"]


@pytest.mark.parametrize("path", DOC_PATHS)
async def test_docs_are_served_by_default(client: AsyncClient, path: str) -> None:
    response = await client.get(path)
    assert response.status_code == 200


@pytest.mark.parametrize("path", DOC_PATHS)
async def test_docs_can_be_disabled(settings: Settings, path: str) -> None:
    app = create_app(settings.model_copy(update={"docs_enabled": False}))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(path)
    assert response.status_code == 404
