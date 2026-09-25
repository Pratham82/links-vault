"""Enrichment worker: claims pending links from Postgres and fills in their previews.

A plain loop, no Redis or task queue: claim a batch (up to PREVIEW_CONCURRENCY links),
enrich them concurrently, repeat; sleep WORKER_POLL_SECONDS when nothing is due.

Run it with `python -m app.worker`.
"""

import asyncio
import logging
import signal
import uuid

import httpx
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings, get_settings
from app.db import get_sessionmaker
from app.services.enrich import claim_due_links, enrich_link
from app.services.preview import build_http_client

logger = logging.getLogger(__name__)


async def _enrich_one(
    sessionmaker: async_sessionmaker[AsyncSession],
    http: httpx.AsyncClient,
    link_id: uuid.UUID,
    settings: Settings,
) -> None:
    # One session per link, like one session per request in the API.
    try:
        async with sessionmaker() as session:
            await enrich_link(session, http, link_id, thumbnail_dir=settings.thumbnail_dir)
    except Exception:
        # One broken link must not stop the others; its lease expires and it's retried.
        logger.exception("Enriching link %s crashed", link_id)


async def run_once(
    sessionmaker: async_sessionmaker[AsyncSession], http: httpx.AsyncClient, settings: Settings
) -> int:
    """Claim and enrich one batch. Returns how many links were claimed."""
    async with sessionmaker() as session:
        link_ids = await claim_due_links(session, settings.preview_concurrency)
    await asyncio.gather(*(_enrich_one(sessionmaker, http, i, settings) for i in link_ids))
    return len(link_ids)


async def run_forever(settings: Settings) -> None:
    sessionmaker = get_sessionmaker()
    async with build_http_client(settings.preview_concurrency) as http:
        while True:
            try:
                claimed = await run_once(sessionmaker, http, settings)
            except (SQLAlchemyError, OSError) as exc:
                # E.g. Postgres restarting, or migrations not applied yet. Try again soon.
                logger.warning("Could not claim links: %r", exc)
                claimed = 0
            if claimed == 0:
                await asyncio.sleep(settings.worker_poll_seconds)


async def _main() -> None:
    settings = get_settings()
    # `docker compose stop` sends SIGTERM; cancel the loop so we exit right away. Links
    # that were mid-fetch are picked up again once their lease expires.
    task = asyncio.current_task()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, task.cancel)  # type: ignore[union-attr]
    logger.info(
        "Worker started: concurrency %d, thumbnails in %s",
        settings.preview_concurrency,
        settings.thumbnail_dir,
    )
    try:
        await run_forever(settings)
    except asyncio.CancelledError:
        logger.info("Worker stopped")


def main() -> None:
    logging.basicConfig(
        format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO
    )
    # httpx logs every request at INFO; our own log lines already say what matters.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    asyncio.run(_main())


if __name__ == "__main__":
    main()
