import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
import respx
from httpx import AsyncClient

from app.config import get_settings
from app.services.preview import build_http_client
from app.services.thumbnails import MAX_THUMBNAIL_BYTES, cache_thumbnail

IMAGE_URL = "https://cdn.example.com/cover"
LINK_ID = uuid.UUID("12345678-1234-5678-1234-567812345678")


@pytest.fixture
async def http() -> AsyncIterator[httpx.AsyncClient]:
    async with build_http_client(max_connections=2) as client:
        yield client


# --- cache_thumbnail ---


@respx.mock
async def test_cache_thumbnail_saves_file(http: httpx.AsyncClient, tmp_path: Path) -> None:
    respx.get(IMAGE_URL).respond(
        200, content=b"jpeg-bytes", headers={"Content-Type": "image/jpeg; charset=binary"}
    )
    directory = tmp_path / "nested" / "thumbs"

    assert await cache_thumbnail(http, IMAGE_URL, directory, LINK_ID) == (
        f"/thumbnails/{LINK_ID}.jpg"
    )
    assert (directory / f"{LINK_ID}.jpg").read_bytes() == b"jpeg-bytes"


@respx.mock
@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(404),
        httpx.Response(200, content=b"<html>", headers={"Content-Type": "text/html"}),
        httpx.Response(200, content=b"<svg/>", headers={"Content-Type": "image/svg+xml"}),
        httpx.Response(
            200, content=b"x" * (MAX_THUMBNAIL_BYTES + 1), headers={"Content-Type": "image/png"}
        ),
    ],
    ids=["404", "html", "svg", "too-big"],
)
async def test_cache_thumbnail_rejects(
    http: httpx.AsyncClient, tmp_path: Path, response: httpx.Response
) -> None:
    respx.get(IMAGE_URL).mock(return_value=response)
    assert await cache_thumbnail(http, IMAGE_URL, tmp_path, LINK_ID) is None
    assert not (tmp_path / f"{LINK_ID}.png").exists()


@respx.mock
async def test_cache_thumbnail_network_error(http: httpx.AsyncClient, tmp_path: Path) -> None:
    respx.get(IMAGE_URL).mock(side_effect=httpx.ConnectTimeout("slow"))
    assert await cache_thumbnail(http, IMAGE_URL, tmp_path, LINK_ID) is None


@respx.mock
async def test_cache_thumbnail_unwritable_directory(
    http: httpx.AsyncClient, tmp_path: Path
) -> None:
    respx.get(IMAGE_URL).respond(200, content=b"png", headers={"Content-Type": "image/png"})
    blocker = tmp_path / "file"
    blocker.write_text("not a directory")
    assert await cache_thumbnail(http, IMAGE_URL, blocker, LINK_ID) is None


# --- GET /thumbnails/{filename} ---


@pytest.fixture
def thumbnail_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(get_settings(), "thumbnail_dir", tmp_path)
    return tmp_path


async def test_serve_thumbnail(client: AsyncClient, thumbnail_dir: Path) -> None:
    (thumbnail_dir / f"{LINK_ID}.png").write_bytes(b"png-bytes")

    response = await client.get(f"/thumbnails/{LINK_ID}.png")

    assert response.status_code == 200
    assert response.content == b"png-bytes"
    assert response.headers["content-type"] == "image/png"
    assert "immutable" in response.headers["cache-control"]


async def test_serve_thumbnail_requires_api_key(client: AsyncClient, thumbnail_dir: Path) -> None:
    (thumbnail_dir / f"{LINK_ID}.png").write_bytes(b"png-bytes")
    response = await client.get(f"/thumbnails/{LINK_ID}.png", headers={"X-API-Key": "wrong"})
    assert response.status_code == 401


@pytest.mark.parametrize(
    "filename",
    [f"{LINK_ID}.jpg", "secret.txt", f"{LINK_ID}.png.part"],
)
async def test_serve_thumbnail_404s(
    client: AsyncClient, thumbnail_dir: Path, filename: str
) -> None:
    (thumbnail_dir / f"{LINK_ID}.png").write_bytes(b"png-bytes")
    (thumbnail_dir / "secret.txt").write_text("nope")
    (thumbnail_dir / f"{LINK_ID}.png.part").write_bytes(b"half")

    response = await client.get(f"/thumbnails/{filename}")
    assert response.status_code == 404
    assert response.json() == {"detail": "Thumbnail not found"}


@pytest.mark.parametrize("path", ["/thumbnails/..%2Fsecret.txt", "/thumbnails/../secret.txt"])
async def test_serve_thumbnail_blocks_path_traversal(
    client: AsyncClient, thumbnail_dir: Path, path: str
) -> None:
    (thumbnail_dir.parent / "secret.txt").write_text("nope")
    response = await client.get(path)
    assert response.status_code == 404
    assert b"nope" not in response.content
