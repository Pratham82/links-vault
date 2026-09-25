"""Enrichment worker: claims pending links from Postgres and fills in their previews.

A plain loop, no Redis or task queue: claim a batch, enrich it concurrently, repeat; sleep
WORKER_POLL_SECONDS when nothing is due. A batch holds up to PREVIEW_CONCURRENCY live links
plus up to IMPORT_PREVIEW_CONCURRENCY imported ones, each of those from a site the worker
hasn't fetched from in the last IMPORT_DOMAIN_DELAY_SECONDS.

Run it with `python -m app.worker`.
"""

import asyncio
import logging
import signal
import time
import uuid
from collections.abc import Callable

import httpx
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings, get_settings
from app.db import get_sessionmaker
from app.services.enrich import claim_due_import_links, claim_due_links, enrich_link
from app.services.preview import build_http_client

logger = logging.getLogger(__name__)


class DomainThrottle:
    """Remembers when the worker last started fetching an imported link from each host.

    Kept in memory: there is one worker process, and after a restart the worst case is one
    early request per site.
    """

    def __init__(self, delay_seconds: float, clock: Callable[[], float] = time.monotonic):
        self._delay = delay_seconds
        self._clock = clock
        self._last_fetch: dict[str, float] = {}

    def busy_hosts(self) -> list[str]:
        """Hosts fetched too recently to be fetched again now."""
        now = self._clock()
        # Forget hosts whose delay is over, so the dict doesn't grow forever.
        self._last_fetch = {
            host: at for host, at in self._last_fetch.items() if now - at < self._delay
        }
        return list(self._last_fetch)

    def mark(self, host: str) -> None:
        self._last_fetch[host] = self._clock()


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
    sessionmaker: async_sessionmaker[AsyncSession],
    http: httpx.AsyncClient,
    settings: Settings,
    throttle: DomainThrottle,
) -> int:
    """Claim and enrich one batch. Returns how many links were claimed."""
    async with sessionmaker() as session:
        link_ids = await claim_due_links(session, settings.preview_concurrency)
        imported = await claim_due_import_links(
            session, settings.import_preview_concurrency, skip_hosts=throttle.busy_hosts()
        )
    for link_id, host in imported:
        throttle.mark(host)
        link_ids.append(link_id)
    await asyncio.gather(*(_enrich_one(sessionmaker, http, i, settings) for i in link_ids))
    return len(link_ids)


async def run_forever(settings: Settings) -> None:
    sessionmaker = get_sessionmaker()
    throttle = DomainThrottle(settings.import_domain_delay_seconds)
    max_connections = settings.preview_concurrency + settings.import_preview_concurrency
    async with build_http_client(max_connections) as http:
        while True:
            try:
                claimed = await run_once(sessionmaker, http, settings, throttle)
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
        "Worker started: concurrency %d (imports %d, %gs apart per site), thumbnails in %s",
        settings.preview_concurrency,
        settings.import_preview_concurrency,
        settings.import_domain_delay_seconds,
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
