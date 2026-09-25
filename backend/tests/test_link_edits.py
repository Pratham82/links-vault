"""`PATCH /links/{id}` and `DELETE /links/{id}`: editing note, tags and type; deleting."""

import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Link, SourceChannel
from app.services.links import delete_link


async def create(client: AsyncClient, text: str = "nice https://example.com/post") -> dict:
    body = {"text": text, "source_channel": "api", "sender": "tester"}
    response = await client.post("/links", json=body)
    assert response.status_code == 201, response.text
    return response.json()["created"][0]


async def test_patch_note_tags_and_type(client: AsyncClient) -> None:
    link = await create(client)

    response = await client.patch(
        f"/links/{link['id']}",
        json={"note": "  read later  ", "tags": ["AI", "#tools"], "content_type": "article"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["note"] == "read later"
    assert data["tags"] == ["ai", "tools"]
    assert data["content_type"] == "article"
    assert data["updated_at"] >= link["updated_at"]
    # The change sticks.
    assert (await client.get(f"/links/{link['id']}")).json()["tags"] == ["ai", "tools"]


async def test_patch_only_changes_given_fields(client: AsyncClient) -> None:
    link = await create(client)
    await client.patch(f"/links/{link['id']}", json={"tags": ["react"]})

    data = (await client.patch(f"/links/{link['id']}", json={"content_type": "docs"})).json()

    assert data["note"] == "nice"
    assert data["tags"] == ["react"]
    assert data["content_type"] == "docs"


@pytest.mark.parametrize("note", [None, "", "   "])
async def test_patch_clears_note(client: AsyncClient, note: str | None) -> None:
    link = await create(client)
    data = (await client.patch(f"/links/{link['id']}", json={"note": note})).json()
    assert data["note"] is None


async def test_patch_cleans_tags(client: AsyncClient) -> None:
    link = await create(client)
    tags = ["React", "react", " #react ", "", "machine   learning"]
    data = (await client.patch(f"/links/{link['id']}", json={"tags": tags})).json()
    assert data["tags"] == ["react", "machine learning"]


async def test_patch_empty_tags_removes_all(client: AsyncClient) -> None:
    link = await create(client)
    await client.patch(f"/links/{link['id']}", json={"tags": ["a"]})
    data = (await client.patch(f"/links/{link['id']}", json={"tags": []})).json()
    assert data["tags"] == []


async def test_patch_empty_body_changes_nothing(client: AsyncClient) -> None:
    link = await create(client)
    response = await client.patch(f"/links/{link['id']}", json={})
    assert response.status_code == 200
    assert response.json()["note"] == "nice"


@pytest.mark.parametrize(
    "body",
    [
        {"tags": None},
        {"content_type": None},
        {"content_type": "podcast"},
        {"tags": ["x" * 51]},
        {"tags": [f"t{i}" for i in range(21)]},
        {"note": "x" * 10_001},
        {"url": "https://evil.com"},
        {"share_count": 99},
    ],
)
async def test_patch_rejects_bad_bodies(client: AsyncClient, body: dict) -> None:
    link = await create(client)
    response = await client.patch(f"/links/{link['id']}", json=body)
    assert response.status_code == 422, response.text


async def test_patch_missing_link_is_404(client: AsyncClient) -> None:
    response = await client.patch(f"/links/{uuid.uuid4()}", json={"note": "x"})
    assert response.status_code == 404


async def test_delete_link(client: AsyncClient) -> None:
    link = await create(client)

    response = await client.delete(f"/links/{link['id']}")

    assert response.status_code == 204
    assert response.content == b""
    assert (await client.get(f"/links/{link['id']}")).status_code == 404
    assert (await client.delete(f"/links/{link['id']}")).status_code == 404


async def test_edits_require_api_key(client: AsyncClient) -> None:
    link = await create(client)
    headers = {"X-API-Key": "wrong"}
    patch = await client.patch(f"/links/{link['id']}", json={"note": "x"}, headers=headers)
    delete = await client.delete(f"/links/{link['id']}", headers=headers)
    assert (patch.status_code, delete.status_code) == (401, 401)


async def test_delete_removes_cached_thumbnail(db_session: AsyncSession, tmp_path: Path) -> None:
    link_id = uuid.uuid4()
    thumbnail = tmp_path / f"{link_id}.jpg"
    thumbnail.write_bytes(b"\xff\xd8\xff")
    other = tmp_path / "keep.jpg"
    other.write_bytes(b"\xff\xd8\xff")
    db_session.add(
        Link(
            id=link_id,
            url="https://example.com",
            normalized_url="https://example.com",
            source_channel=SourceChannel.API,
            sender="tester",
            image_url=f"/thumbnails/{link_id}.jpg",
            shared_at=datetime.now(UTC),
        )
    )
    await db_session.commit()

    assert await delete_link(db_session, link_id, thumbnail_dir=tmp_path)

    assert not thumbnail.exists()
    assert other.exists()


async def test_delete_keeps_files_for_remote_images(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    link_id = uuid.uuid4()
    stray = tmp_path / f"{link_id}.jpg"
    stray.write_bytes(b"\xff\xd8\xff")
    db_session.add(
        Link(
            id=link_id,
            url="https://example.com",
            normalized_url="https://example.com",
            source_channel=SourceChannel.API,
            sender="tester",
            image_url="https://cdn.example.com/cover.jpg",
            shared_at=datetime.now(UTC),
        )
    )
    await db_session.commit()

    assert await delete_link(db_session, link_id, thumbnail_dir=tmp_path)
    assert stray.exists()
