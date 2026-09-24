import asyncio
import os
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import make_url
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession, create_async_engine

# Must be set before app settings are first read.
os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://linkvault:linkvault@localhost:5432/linkvault_test"
)
os.environ.setdefault("API_KEY", "test-api-key")

from alembic.config import Config

from alembic import command
from app.config import get_settings
from app.db import get_session
from app.main import create_app

BACKEND_DIR = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session")
def settings():
    return get_settings()


async def _check_database(url: str) -> None:
    engine = create_async_engine(url)
    try:
        async with engine.connect():
            pass
    finally:
        await engine.dispose()


@pytest.fixture(scope="session")
def migrated_db(settings) -> Iterator[None]:
    """Rebuild the schema from migrations once per test run, so migrations are tested too."""
    try:
        asyncio.run(_check_database(settings.database_url))
    except Exception as exc:
        # Stop the whole run with one readable message instead of an error per test.
        host = make_url(settings.database_url).render_as_string(hide_password=True)
        pytest.exit(
            f"Cannot connect to the test database at {host}: {exc!r}\n"
            "Start Postgres (e.g. `docker compose up -d db`) or set DATABASE_URL.",
            returncode=1,
        )

    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.attributes["database_url"] = settings.database_url
    config.attributes["configure_logger"] = False
    command.downgrade(config, "base")
    command.upgrade(config, "head")
    yield


@pytest.fixture(scope="session")
async def engine(settings, migrated_db) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(settings.database_url)
    yield engine
    await engine.dispose()


@pytest.fixture
async def connection(engine: AsyncEngine) -> AsyncIterator[AsyncConnection]:
    """A connection inside an outer transaction that is rolled back after each test."""
    async with engine.connect() as conn:
        transaction = await conn.begin()
        yield conn
        await transaction.rollback()


@pytest.fixture
async def db_session(connection: AsyncConnection) -> AsyncIterator[AsyncSession]:
    # "create_savepoint": session.commit() only releases a SAVEPOINT, so the outer
    # transaction (and therefore the rollback) still wraps everything the test did.
    session = AsyncSession(
        bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False
    )
    yield session
    await session.close()


@pytest.fixture
async def client(db_session: AsyncSession, settings) -> AsyncIterator[AsyncClient]:
    app = create_app()

    async def _override_session() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_session] = _override_session
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://test", headers={"X-API-Key": settings.api_key}
    ) as c:
        yield c
