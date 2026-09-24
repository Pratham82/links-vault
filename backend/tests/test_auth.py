import pytest
from httpx import AsyncClient


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/links"),
        ("POST", "/links"),
        ("GET", "/links/00000000-0000-0000-0000-000000000000"),
    ],
)
async def test_missing_api_key_is_rejected(client: AsyncClient, method: str, path: str) -> None:
    client.headers.pop("X-API-Key")
    response = await client.request(method, path)
    assert response.status_code == 401
    assert response.json() == {"detail": "Missing or invalid X-API-Key header"}


async def test_wrong_api_key_is_rejected(client: AsyncClient) -> None:
    response = await client.get("/links", headers={"X-API-Key": "wrong"})
    assert response.status_code == 401
