"""`POST /import/whatsapp` and `GET /imports`: reports, idempotency, bad uploads."""

import io
import uuid
import zipfile
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Import, Link, LinkStatus, SourceChannel
from app.services import imports
from tests.test_whatsapp_parser import FIXTURES


def fixture_bytes(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def zipped(files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return buffer.getvalue()


async def upload(client: AsyncClient, content: bytes, filename: str = "chat.txt", **params: str):
    return await client.post("/import/whatsapp", files={"file": (filename, content)}, params=params)


async def import_ok(client: AsyncClient, content: bytes, **kwargs) -> dict:
    response = await upload(client, content, **kwargs)
    assert response.status_code == 201, response.text
    return response.json()


async def count(session: AsyncSession, model: type) -> int:
    return await session.scalar(select(func.count()).select_from(model))


def report_numbers(report: dict) -> dict:
    keys = ("messages", "links_found", "created", "duplicates", "unparseable_lines")
    return {key: report[key] for key in keys}


async def test_import_android_export(client: AsyncClient, db_session: AsyncSession) -> None:
    report = await import_ok(client, fixture_bytes("android.txt"), filename="WhatsApp Chat.txt")

    assert report["filename"] == "WhatsApp Chat.txt"
    assert report_numbers(report) == {
        "messages": 5,
        "links_found": 5,
        "created": 5,
        "duplicates": 0,
        "unparseable_lines": 0,
    }
    assert report["sample_errors"] == []

    links = (await db_session.scalars(select(Link).order_by(Link.shared_at, Link.url))).all()
    assert [link.normalized_url for link in links] == [
        "https://github.com/astral-sh/uv",
        "https://example.com/post",
        "https://x.com/someone/status/123",
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://example.com/caption",
    ]
    first = links[0]
    assert first.source_channel is SourceChannel.WHATSAPP_IMPORT
    assert first.sender == "Prathamesh"
    assert first.note == "check this"
    assert first.status is LinkStatus.PENDING
    # 10:15 pm in Kolkata (UTC+5:30), stored in UTC.
    assert first.shared_at == datetime(2026, 9, 24, 16, 45, tzinfo=UTC)
    assert links[1].note == "two links in one message and worth reading later"
    assert links[3].sender == "+91 98765 43210"


async def test_reimport_creates_no_rows(client: AsyncClient, db_session: AsyncSession) -> None:
    await import_ok(client, fixture_bytes("android.txt"))
    before = await count(db_session, Link)

    report = await import_ok(client, fixture_bytes("android.txt"))

    assert report["created"] == 0
    assert report["duplicates"] == 5
    assert await count(db_session, Link) == before
    # Every upload is still recorded.
    assert await count(db_session, Import) == 2
    # A repeat changes nothing about the stored link.
    shares = (await db_session.scalars(select(Link.share_count))).all()
    assert set(shares) == {1}


async def test_overlapping_export_only_adds_new_messages(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await import_ok(client, fixture_bytes("android.txt"))
    later_export = (
        fixture_bytes("android.txt")
        + ("26/09/2026, 9:00\u202fam - Prathamesh: new one https://example.com/new\n").encode()
    )

    report = await import_ok(client, later_export)

    assert (report["created"], report["duplicates"]) == (1, 5)
    assert await count(db_session, Link) == 6


async def test_same_link_on_another_day_is_a_new_row(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    text = (
        "24/09/2026, 10:15 - A: https://example.com/a\n"
        "25/09/2026, 10:15 - A: again https://example.com/a?utm_source=x\n"
        "25/09/2026, 10:15 - B: https://example.com/a\n"
    )
    report = await import_ok(client, text.encode())

    # Same URL and same minute as the previous message counts as the same share.
    assert (report["created"], report["duplicates"]) == (2, 1)
    assert await count(db_session, Link) == 2


async def test_import_ios_zip(client: AsyncClient, db_session: AsyncSession) -> None:
    content = zipped(
        {
            "_chat.txt": fixture_bytes("ios.txt"),
            "__MACOSX/._chat.txt": b"\x00\x05\x16\x07",
            "00000012-PHOTO-2026-09-24-22-17-30.jpg": b"\xff\xd8\xff",
        }
    )
    report = await import_ok(client, content, filename="WhatsApp Chat - Links.zip")

    assert report_numbers(report) == {
        "messages": 4,
        "links_found": 4,
        "created": 4,
        "duplicates": 0,
        "unparseable_lines": 0,
    }
    link = await db_session.scalar(
        select(Link).where(Link.normalized_url == "https://github.com/astral-sh/uv")
    )
    assert link is not None
    assert link.shared_at == datetime(2026, 9, 24, 16, 45, 32, tzinfo=UTC)


async def test_import_reports_unparseable_lines(client: AsyncClient) -> None:
    report = await import_ok(client, fixture_bytes("android_24h.txt"))

    assert report_numbers(report) == {
        "messages": 2,
        "links_found": 2,
        "created": 2,
        "duplicates": 0,
        "unparseable_lines": 3,
    }
    assert report["sample_errors"][1] == "line 3: 30/02/26 is not a valid date"


async def test_sample_errors_are_capped(client: AsyncClient) -> None:
    junk = "".join(f"31/31/2026, 10:{i:02d} - A: x\n" for i in range(15))
    report = await import_ok(client, (junk + "24/09/2026, 10:15 - A: https://a.com\n").encode())

    assert report["unparseable_lines"] == 15
    assert len(report["sample_errors"]) == imports.SAMPLE_ERRORS


async def test_wrong_date_order_imports_nothing(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    response = await upload(client, fixture_bytes("android_mdy.txt"))

    assert response.status_code == 422
    assert "date_order=MDY" in response.json()["detail"]
    assert await count(db_session, Link) == 0
    assert await count(db_session, Import) == 0


async def test_date_order_param(client: AsyncClient, db_session: AsyncSession) -> None:
    report = await import_ok(client, fixture_bytes("android_mdy.txt"), date_order="MDY")

    assert report["created"] == 2
    dates = (await db_session.scalars(select(Link.shared_at).order_by(Link.shared_at))).all()
    assert [d.date().isoformat() for d in dates] == ["2026-09-05", "2026-09-24"]


async def test_timezone_param(client: AsyncClient, db_session: AsyncSession) -> None:
    text = b"24/09/2026, 10:15 - A: https://a.com\n"
    await import_ok(client, text, timezone="Europe/London")

    link = await db_session.scalar(select(Link))
    assert link is not None
    assert link.shared_at == datetime(2026, 9, 24, 9, 15, tzinfo=UTC)


@pytest.mark.parametrize(
    ("params", "detail"),
    [
        ({"timezone": "Mars/Olympus"}, "Unknown timezone"),
        ({"date_order": "dmy"}, None),
    ],
)
async def test_bad_params_are_422(client: AsyncClient, params: dict, detail: str | None) -> None:
    response = await upload(client, fixture_bytes("android.txt"), **params)
    assert response.status_code == 422
    if detail:
        assert detail in response.json()["detail"]


@pytest.mark.parametrize(
    ("content", "detail"),
    [
        (b"just some notes\nnot a chat\n", "No WhatsApp messages found"),
        (b"", "No WhatsApp messages found"),
        (b"\x89PNG\r\n\x1a\n\x00\x00", "not a text file"),
        (zipped({"photo.jpg": b"\xff\xd8\xff"}), "exactly one chat .txt"),
        (zipped({"a.txt": b"x", "b.txt": b"y"}), "exactly one chat .txt"),
        (b"PK\x03\x04 truncated zip", "Could not read the zip"),
    ],
)
async def test_unreadable_uploads_are_422(
    client: AsyncClient, db_session: AsyncSession, content: bytes, detail: str
) -> None:
    response = await upload(client, content)

    assert response.status_code == 422
    assert detail in response.json()["detail"]
    assert await count(db_session, Import) == 0


async def test_upload_without_file_is_422(client: AsyncClient) -> None:
    response = await client.post("/import/whatsapp")
    assert response.status_code == 422


async def test_too_large_upload_is_413(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(imports, "MAX_UPLOAD_BYTES", 100)
    response = await upload(client, fixture_bytes("android.txt"))
    assert response.status_code == 413


async def test_too_large_chat_inside_zip_is_413(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(imports, "MAX_CHAT_BYTES", 100)
    response = await upload(client, zipped({"_chat.txt": fixture_bytes("android.txt")}))
    assert response.status_code == 413


async def test_import_requires_api_key(client: AsyncClient) -> None:
    response = await client.post(
        "/import/whatsapp",
        files={"file": ("chat.txt", fixture_bytes("android.txt"))},
        headers={"X-API-Key": "wrong"},
    )
    assert response.status_code == 401
    assert (await client.get("/imports", headers={"X-API-Key": "wrong"})).status_code == 401


async def test_imports_do_not_touch_live_links(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    body = {"text": "https://github.com/astral-sh/uv", "source_channel": "api", "sender": "me"}
    live = (await client.post("/links", json=body)).json()["created"][0]

    await import_ok(client, fixture_bytes("android.txt"))

    stored = await db_session.get(Link, live["id"])
    assert stored is not None
    await db_session.refresh(stored)
    assert stored.share_count == 1
    # The imported copy is its own row, with its original date.
    assert await count(db_session, Link) == 6


async def test_list_imports_newest_first(client: AsyncClient, db_session: AsyncSession) -> None:
    first = await import_ok(client, fixture_bytes("android.txt"), filename="old.txt")
    second = await import_ok(client, fixture_bytes("android.txt"), filename="new.txt")
    # Both uploads ran in the test's one transaction, so they share now(); backdate one.
    await db_session.execute(
        update(Import)
        .where(Import.id == uuid.UUID(first["id"]))
        .values(created_at=datetime(2026, 1, 1, tzinfo=UTC))
    )
    await db_session.commit()

    response = await client.get("/imports")

    assert response.status_code == 200
    items = response.json()
    assert [item["id"] for item in items] == [second["id"], first["id"]]
    latest = items[0]
    assert latest["source"] == "whatsapp"
    assert latest["filename"] == "new.txt"
    assert latest["stats"] == {
        "messages": 5,
        "links_found": 5,
        "created": 0,
        "duplicates": 5,
        "unparseable_lines": 0,
        "sample_errors": [],
    }


async def test_list_imports_empty(client: AsyncClient) -> None:
    response = await client.get("/imports")
    assert response.status_code == 200
    assert response.json() == []


async def test_post_links_with_import_channel_uses_import_dedupe(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    body = {
        "text": "https://example.com/a",
        "source_channel": "whatsapp_import",
        "sender": "me",
        "shared_at": "2026-09-24T10:00:00+00:00",
    }
    assert len((await client.post("/links", json=body)).json()["created"]) == 1
    assert len((await client.post("/links", json=body)).json()["duplicates"]) == 1
    other_day = {**body, "shared_at": "2026-09-25T10:00:00+00:00"}
    assert len((await client.post("/links", json=other_day)).json()["created"]) == 1
    assert await count(db_session, Link) == 2


async def test_reimport_after_short_link_was_resolved(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    text = b"24/09/2026, 10:15 - A: https://t.co/abc\n"
    await import_ok(client, text)
    # What the worker does once it has followed the redirect.
    link = await db_session.scalar(select(Link))
    assert link is not None
    link.normalized_url = "https://example.com/target"
    await db_session.commit()

    report = await import_ok(client, text)

    assert (report["created"], report["duplicates"]) == (0, 1)
    assert await count(db_session, Link) == 1
