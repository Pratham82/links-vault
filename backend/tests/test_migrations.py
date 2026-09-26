"""Data steps inside migrations, run against a throwaway database."""

import asyncio
from collections.abc import Iterator

import pytest
from alembic.config import Config
from sqlalchemy import make_url, text
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import command
from tests.conftest import BACKEND_DIR

BEFORE_PHASE_2 = "65d309536b27"
PHASE_2 = "e4e845be1e3b"
PHASE_3 = "2e626bfd3a4f"
REQUEUE_INSTAGRAM = "7b3f1c9d2a4e"


async def _execute(url: str, *statements: str) -> list:
    # CREATE/DROP DATABASE can't run inside a transaction, hence AUTOCOMMIT.
    engine = create_async_engine(url, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as conn:
            result = None
            for statement in statements:
                result = await conn.execute(text(statement))
            return list(result.all()) if result is not None and result.returns_rows else []
    finally:
        await engine.dispose()


@pytest.fixture
def scratch_db(settings) -> Iterator[str]:
    url = make_url(settings.database_url)
    name = f"{url.database}_migrations"
    admin = url.render_as_string(hide_password=False)
    drop = f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'
    asyncio.run(_execute(admin, drop, f'CREATE DATABASE "{name}"'))
    yield url.set(database=name).render_as_string(hide_password=False)
    asyncio.run(_execute(admin, drop))


def _alembic(url: str) -> Config:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.attributes["database_url"] = url
    config.attributes["configure_logger"] = False
    return config


def test_phase_2_migration_merges_existing_duplicates(scratch_db: str) -> None:
    config = _alembic(scratch_db)
    command.upgrade(config, BEFORE_PHASE_2)
    asyncio.run(
        _execute(
            scratch_db,
            """
            INSERT INTO links (url, normalized_url, source_channel, sender, note, shared_at)
            VALUES
              ('https://a.com', 'https://a.com', 'api', 'x', 'first', '2026-01-01Z'),
              ('https://a.com', 'https://a.com', 'telegram', 'x', NULL, '2026-01-02Z'),
              ('https://a.com', 'https://a.com', 'api', 'x', 'first', '2026-01-03Z'),
              ('https://a.com', 'https://a.com', 'api', 'x', 'second', '2026-01-04Z'),
              ('https://b.com', 'https://b.com', 'api', 'x', 'solo', '2026-01-01Z'),
              ('https://c.com', 'https://c.com', 'whatsapp_import', 'x', 'i1', '2026-01-01Z'),
              ('https://c.com', 'https://c.com', 'whatsapp_import', 'x', 'i2', '2026-01-02Z')
            """,
        )
    )

    command.upgrade(config, PHASE_2)

    rows = asyncio.run(
        _execute(
            scratch_db,
            "SELECT url, share_count, note, shared_at::date::text FROM links ORDER BY url, note",
        )
    )
    assert [tuple(row) for row in rows] == [
        # Earliest row kept, counts summed, each distinct note once in share order.
        ("https://a.com", 4, "first\nsecond", "2026-01-01"),
        ("https://b.com", 1, "solo", "2026-01-01"),
        # Imports are left alone: they dedupe on (normalized_url, shared_at) instead.
        ("https://c.com", 1, "i1", "2026-01-01"),
        ("https://c.com", 1, "i2", "2026-01-02"),
    ]
    command.downgrade(config, "base")


def test_phase_3_migration_drops_repeated_imports(scratch_db: str) -> None:
    config = _alembic(scratch_db)
    command.upgrade(config, PHASE_2)
    asyncio.run(
        _execute(
            scratch_db,
            """
            INSERT INTO links (url, normalized_url, source_channel, sender, note, shared_at,
                               created_at)
            VALUES
              ('https://c.com', 'https://c.com', 'whatsapp_import', 'x', 'kept',
               '2026-01-01Z', '2026-02-01Z'),
              ('https://c.com?utm_source=a', 'https://c.com', 'whatsapp_import', 'x', 'repeat',
               '2026-01-01Z', '2026-02-02Z'),
              ('https://c.com', 'https://c.com', 'whatsapp_import', 'x', 'other day',
               '2026-01-02Z', '2026-02-01Z'),
              ('https://c.com', 'https://c.com', 'api', 'x', 'live', '2026-01-01Z', '2026-02-01Z')
            """,
        )
    )

    command.upgrade(config, PHASE_3)

    rows = asyncio.run(_execute(scratch_db, "SELECT note FROM links ORDER BY note"))
    assert [row.note for row in rows] == ["kept", "live", "other day"]
    command.downgrade(config, "base")


def test_instagram_login_wall_previews_are_requeued(scratch_db: str) -> None:
    config = _alembic(scratch_db)
    command.upgrade(config, PHASE_3)
    asyncio.run(
        _execute(
            scratch_db,
            """
            INSERT INTO links (url, normalized_url, source_channel, sender, shared_at,
                               content_type, status, title, image_url, enrich_attempts)
            VALUES
              ('https://www.instagram.com/reel/a', 'https://www.instagram.com/reel/a', 'api',
               'x', '2026-01-01Z', 'instagram', 'enriched', 'Instagram', NULL, 1),
              ('https://www.instagram.com/reel/b', 'https://www.instagram.com/reel/b', 'api',
               'x', '2026-01-01Z', 'instagram', 'enriched', 'Chef on Instagram', '/t/b.jpg', 1),
              ('https://example.com/a', 'https://example.com/a', 'api',
               'x', '2026-01-01Z', 'article', 'enriched', 'Instagram', NULL, 1)
            """,
        )
    )

    command.upgrade(config, REQUEUE_INSTAGRAM)

    rows = asyncio.run(
        _execute(scratch_db, "SELECT url, status, title, enrich_attempts FROM links ORDER BY url")
    )
    assert [tuple(row) for row in rows] == [
        ("https://example.com/a", "enriched", "Instagram", 1),
        ("https://www.instagram.com/reel/a", "pending", None, 0),
        # A real preview is left alone.
        ("https://www.instagram.com/reel/b", "enriched", "Chef on Instagram", 1),
    ]
    command.downgrade(config, "base")
