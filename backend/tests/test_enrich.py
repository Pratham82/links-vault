"""The enrichment worker: claiming, retries, merging short links, saving previews."""

import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
import respx
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, async_sessionmaker

from app.config import Settings
from app.models import ContentType, Link, LinkStatus, SourceChannel
from app.services.enrich import (
    MAX_ATTEMPTS,
    claim_due_import_links,
    claim_due_links,
    enrich_link,
    retry_delay,
)
from app.services.normalize import normalize_url
from app.services.preview import X_OEMBED_URL, build_http_client
from app.worker import DomainThrottle, run_once

ARTICLE_HTML = """
<meta property="og:type" content="article">
<meta property="og:title" content="A great post">
<meta property="og:description" content="About things.">
<meta property="og:image" content="https://cdn.example.com/cover.jpg">
<meta property="og:site_name" content="Example">
"""
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


@pytest.fixture
async def http() -> AsyncIterator[httpx.AsyncClient]:
    async with build_http_client(max_connections=2) as client:
        yield client


async def add_link(session: AsyncSession, url: str, **fields) -> Link:
    link = Link(
        url=url,
        normalized_url=normalize_url(url),
        source_channel=fields.pop("source_channel", SourceChannel.API),
        sender="tester",
        shared_at=fields.pop("shared_at", datetime.now(UTC)),
        **fields,
    )
    session.add(link)
    await session.commit()
    return link


async def claim_and_enrich(
    session: AsyncSession, http: httpx.AsyncClient, link: Link, thumbnail_dir: Path
) -> Link:
    assert await claim_due_links(session, limit=10) == [link.id]
    await enrich_link(session, http, link.id, thumbnail_dir=thumbnail_dir)
    await session.refresh(link)
    return link


async def make_due_again(session: AsyncSession, link: Link) -> None:
    """Pretend the retry backoff has passed."""
    await session.execute(
        update(Link)
        .where(Link.id == link.id)
        .values(next_attempt_at=func.now() - timedelta(seconds=1))
    )
    await session.commit()


# --- claiming ---


async def test_claim_takes_only_due_links(db_session: AsyncSession) -> None:
    pending = await add_link(db_session, "https://a.com/pending")
    await add_link(db_session, "https://a.com/enriched", status=LinkStatus.ENRICHED)
    await add_link(db_session, "https://a.com/dead", status=LinkStatus.DEAD)
    await add_link(
        db_session,
        "https://a.com/backing-off",
        status=LinkStatus.FAILED,
        enrich_attempts=1,
        next_attempt_at=datetime.now(UTC) + timedelta(hours=1),
    )
    await add_link(
        db_session, "https://a.com/gave-up", status=LinkStatus.FAILED, enrich_attempts=MAX_ATTEMPTS
    )
    retry_now = await add_link(
        db_session,
        "https://a.com/retry-now",
        status=LinkStatus.FAILED,
        enrich_attempts=1,
        next_attempt_at=datetime.now(UTC) - timedelta(hours=1),
    )

    claimed = await claim_due_links(db_session, limit=10)
    assert set(claimed) == {pending.id, retry_now.id}


async def test_claim_leases_links_so_they_are_not_claimed_twice(db_session: AsyncSession) -> None:
    link = await add_link(db_session, "https://a.com/1")

    assert await claim_due_links(db_session, limit=10) == [link.id]
    assert await claim_due_links(db_session, limit=10) == []

    await db_session.refresh(link)
    assert link.enrich_attempts == 1
    assert link.next_attempt_at is not None
    assert link.status is LinkStatus.PENDING


async def test_claim_respects_limit_oldest_first(db_session: AsyncSession) -> None:
    links = [await add_link(db_session, f"https://a.com/{i}") for i in range(3)]
    # Inside one test transaction now() never moves, so give each row its own created_at.
    for age_days, link in zip([2, 0, 1], links, strict=True):
        await db_session.execute(
            update(Link)
            .where(Link.id == link.id)
            .values(created_at=func.now() - timedelta(days=age_days))
        )
    await db_session.commit()

    # The two oldest are picked (RETURNING gives no particular order).
    assert set(await claim_due_links(db_session, limit=2)) == {links[0].id, links[2].id}


# --- enriching ---


@respx.mock
async def test_enrich_saves_preview_type_and_cached_thumbnail(
    db_session: AsyncSession, http: httpx.AsyncClient, tmp_path: Path
) -> None:
    link = await add_link(db_session, "https://blog.example.com/post")
    respx.get("https://blog.example.com/post").respond(200, html=ARTICLE_HTML)
    respx.get("https://cdn.example.com/cover.jpg").respond(
        200, content=PNG_BYTES, headers={"Content-Type": "image/png"}
    )

    link = await claim_and_enrich(db_session, http, link, tmp_path)

    assert link.status is LinkStatus.ENRICHED
    assert link.title == "A great post"
    assert link.description == "About things."
    assert link.site_name == "Example"
    assert link.content_type is ContentType.ARTICLE
    assert link.image_url == f"/thumbnails/{link.id}.png"
    assert (tmp_path / f"{link.id}.png").read_bytes() == PNG_BYTES
    assert link.next_attempt_at is None


@respx.mock
async def test_enrich_keeps_remote_image_when_thumbnail_download_fails(
    db_session: AsyncSession, http: httpx.AsyncClient, tmp_path: Path
) -> None:
    link = await add_link(db_session, "https://blog.example.com/post")
    respx.get("https://blog.example.com/post").respond(200, html=ARTICLE_HTML)
    respx.get("https://cdn.example.com/cover.jpg").respond(403)

    link = await claim_and_enrich(db_session, http, link, tmp_path)

    assert link.status is LinkStatus.ENRICHED
    assert link.image_url == "https://cdn.example.com/cover.jpg"
    assert not os.listdir(tmp_path)


@respx.mock
async def test_enrich_page_without_metadata_is_still_enriched(
    db_session: AsyncSession, http: httpx.AsyncClient, tmp_path: Path
) -> None:
    link = await add_link(db_session, "https://github.com/astral-sh/uv", note="fast pip")
    respx.get("https://github.com/astral-sh/uv").respond(200, html="<p>no head</p>")

    link = await claim_and_enrich(db_session, http, link, tmp_path)

    assert link.status is LinkStatus.ENRICHED
    assert link.title is None
    assert link.site_name == "github.com"
    assert link.content_type is ContentType.GITHUB_REPO
    assert link.note == "fast pip"


@respx.mock
async def test_enrich_tweet_through_oembed(
    db_session: AsyncSession, http: httpx.AsyncClient, tmp_path: Path
) -> None:
    link = await add_link(db_session, "https://twitter.com/jack/status/20?s=20")
    respx.get(X_OEMBED_URL).respond(
        200,
        json={
            "author_url": "https://twitter.com/jack",
            "html": "<blockquote><p>just setting up my twttr</p></blockquote>",
        },
    )
    # X blocks the page fetch for the image; the tweet is still enriched from oEmbed.
    respx.get("https://x.com/jack/status/20").respond(403)

    link = await claim_and_enrich(db_session, http, link, tmp_path)

    assert link.status is LinkStatus.ENRICHED
    assert link.content_type is ContentType.TWEET
    assert link.title == "@jack: just setting up my twttr"
    assert link.image_url is None


@respx.mock
@pytest.mark.parametrize("status", [404, 410])
async def test_enrich_gone_link_is_dead_and_never_retried(
    db_session: AsyncSession, http: httpx.AsyncClient, tmp_path: Path, status: int
) -> None:
    link = await add_link(db_session, "https://example.com/gone")
    respx.get("https://example.com/gone").respond(status)

    link = await claim_and_enrich(db_session, http, link, tmp_path)

    assert link.status is LinkStatus.DEAD
    assert link.next_attempt_at is None
    assert await claim_due_links(db_session, limit=10) == []


@respx.mock
async def test_enrich_retries_with_backoff_then_gives_up(
    db_session: AsyncSession, http: httpx.AsyncClient, tmp_path: Path
) -> None:
    link = await add_link(db_session, "https://example.com/flaky")
    route = respx.get("https://example.com/flaky").respond(503)

    for attempt in range(1, MAX_ATTEMPTS + 1):
        link = await claim_and_enrich(db_session, http, link, tmp_path)
        assert link.status is LinkStatus.FAILED
        assert link.enrich_attempts == attempt
        if attempt < MAX_ATTEMPTS:
            # Backing off: not due yet…
            assert link.next_attempt_at is not None
            assert await claim_due_links(db_session, limit=10) == []
            # …until the delay has passed.
            await make_due_again(db_session, link)

    assert route.call_count == MAX_ATTEMPTS
    assert link.next_attempt_at is None
    assert await claim_due_links(db_session, limit=10) == []


@respx.mock
async def test_enrich_success_after_a_failure(
    db_session: AsyncSession, http: httpx.AsyncClient, tmp_path: Path
) -> None:
    link = await add_link(db_session, "https://example.com/flaky")
    respx.get("https://example.com/flaky").mock(
        side_effect=[httpx.ReadTimeout("slow"), httpx.Response(200, html="<title>Back</title>")]
    )

    link = await claim_and_enrich(db_session, http, link, tmp_path)
    assert link.status is LinkStatus.FAILED
    await make_due_again(db_session, link)
    link = await claim_and_enrich(db_session, http, link, tmp_path)

    assert link.status is LinkStatus.ENRICHED
    assert link.title == "Back"


def test_retry_delay_grows() -> None:
    assert retry_delay(1) == timedelta(minutes=1)
    assert retry_delay(2) == timedelta(minutes=5)


# --- short links ---


@respx.mock
async def test_short_link_is_resolved_and_normalized(
    db_session: AsyncSession, http: httpx.AsyncClient, tmp_path: Path
) -> None:
    link = await add_link(db_session, "https://bit.ly/abc")
    respx.get("https://bit.ly/abc").respond(
        301, headers={"Location": "https://Example.com/post?utm_source=bitly"}
    )
    respx.get("https://example.com/post").respond(200, html="<title>Post</title>")

    link = await claim_and_enrich(db_session, http, link, tmp_path)

    assert link.url == "https://bit.ly/abc"
    assert link.normalized_url == "https://example.com/post"
    assert link.status is LinkStatus.ENRICHED
    assert link.title == "Post"


@respx.mock
async def test_short_link_to_known_url_is_merged_into_it(
    db_session: AsyncSession, http: httpx.AsyncClient, tmp_path: Path
) -> None:
    earlier = datetime(2026, 9, 1, tzinfo=UTC)
    existing = await add_link(
        db_session,
        "https://example.com/post",
        note="first",
        share_count=2,
        status=LinkStatus.ENRICHED,
        shared_at=datetime(2026, 9, 10, tzinfo=UTC),
    )
    short = await add_link(db_session, "https://t.co/xyz", note="via twitter", shared_at=earlier)
    respx.get("https://t.co/xyz").respond(301, headers={"Location": "https://example.com/post"})

    assert await claim_due_links(db_session, limit=10) == [short.id]
    await enrich_link(db_session, http, short.id, thumbnail_dir=tmp_path)

    assert await db_session.get(Link, short.id) is None
    await db_session.refresh(existing)
    assert existing.share_count == 3
    assert existing.note == "first\nvia twitter"
    assert existing.shared_at == earlier
    assert await db_session.scalar(select(func.count()).select_from(Link)) == 1


@respx.mock
async def test_dead_short_link(
    db_session: AsyncSession, http: httpx.AsyncClient, tmp_path: Path
) -> None:
    link = await add_link(db_session, "https://bit.ly/nope")
    respx.get("https://bit.ly/nope").respond(404)

    link = await claim_and_enrich(db_session, http, link, tmp_path)
    assert link.status is LinkStatus.DEAD


async def test_enrich_missing_link_is_a_no_op(
    db_session: AsyncSession, http: httpx.AsyncClient, tmp_path: Path
) -> None:
    await enrich_link(db_session, http, uuid.uuid4(), thumbnail_dir=tmp_path)


# --- imported links ---


async def add_import(session: AsyncSession, url: str, **fields) -> Link:
    return await add_link(session, url, source_channel=SourceChannel.WHATSAPP_IMPORT, **fields)


async def test_live_claim_leaves_imports_alone(db_session: AsyncSession) -> None:
    live = await add_link(db_session, "https://a.com/live")
    await add_import(db_session, "https://a.com/imported")

    assert await claim_due_links(db_session, limit=10) == [live.id]


async def test_import_claim_takes_one_link_per_host(db_session: AsyncSession) -> None:
    await add_link(db_session, "https://live.com/a")
    x_first = await add_import(
        db_session, "https://x.com/a/status/1", shared_at=datetime(2026, 1, 1, tzinfo=UTC)
    )
    await add_import(
        db_session, "https://x.com/a/status/2", shared_at=datetime(2026, 1, 2, tzinfo=UTC)
    )
    github = await add_import(db_session, "https://github.com/a/b")
    await add_import(db_session, "https://gone.com/x", status=LinkStatus.DEAD)

    claimed = await claim_due_import_links(db_session, limit=10)

    assert sorted(claimed) == sorted([(x_first.id, "x.com"), (github.id, "github.com")])
    await db_session.refresh(x_first)
    assert x_first.enrich_attempts == 1
    # Leased: a second claim moves on to the next link from x.com.
    [(_, host)] = await claim_due_import_links(db_session, limit=10)
    assert host == "x.com"
    assert await claim_due_import_links(db_session, limit=10) == []


async def test_import_claim_skips_busy_hosts_and_respects_limit(db_session: AsyncSession) -> None:
    await add_import(db_session, "https://x.com/a/status/1")
    await add_import(db_session, "https://www.instagram.com/p/abc/")
    github = await add_import(db_session, "https://github.com/a/b")

    claimed = await claim_due_import_links(
        db_session, limit=1, skip_hosts=["x.com", "www.instagram.com"]
    )

    assert claimed == [(github.id, "github.com")]


async def test_import_claim_handles_urls_without_a_host(db_session: AsyncSession) -> None:
    odd = await add_import(db_session, "https:///no-host")
    fine = await add_import(db_session, "https://a.com/x")

    claimed = await claim_due_import_links(db_session, limit=10, skip_hosts=["b.com"])
    assert sorted(claimed) == sorted([(odd.id, ""), (fine.id, "a.com")])


def test_domain_throttle() -> None:
    now = 100.0
    throttle = DomainThrottle(delay_seconds=5, clock=lambda: now)
    throttle.mark("x.com")
    assert throttle.busy_hosts() == ["x.com"]

    now = 104.9
    throttle.mark("github.com")
    assert sorted(throttle.busy_hosts()) == ["github.com", "x.com"]

    now = 105.0
    assert throttle.busy_hosts() == ["github.com"]


@respx.mock
async def test_run_once_throttles_imports_per_host(
    connection: AsyncConnection, db_session: AsyncSession, tmp_path: Path, settings: Settings
) -> None:
    first = await add_import(
        db_session, "https://example.com/1", shared_at=datetime(2026, 1, 1, tzinfo=UTC)
    )
    second = await add_import(
        db_session, "https://example.com/2", shared_at=datetime(2026, 1, 2, tzinfo=UTC)
    )
    respx.get(url__regex=r"https://example\.com/\d").respond(200, html="<title>Hi</title>")
    sessionmaker = async_sessionmaker(
        bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False
    )
    worker_settings = settings.model_copy(update={"thumbnail_dir": tmp_path})
    now = 0.0
    throttle = DomainThrottle(delay_seconds=5, clock=lambda: now)

    async with build_http_client(max_connections=2) as http:
        assert await run_once(sessionmaker, http, worker_settings, throttle) == 1
        # example.com was just fetched, so the second link waits.
        assert await run_once(sessionmaker, http, worker_settings, throttle) == 0
        now = 5.0
        assert await run_once(sessionmaker, http, worker_settings, throttle) == 1

    for link in (first, second):
        await db_session.refresh(link)
        assert link.status is LinkStatus.ENRICHED


@respx.mock
async def test_imported_short_link_merges_only_with_the_same_import(
    db_session: AsyncSession, http: httpx.AsyncClient, tmp_path: Path
) -> None:
    when = datetime(2026, 9, 1, tzinfo=UTC)
    live = await add_link(db_session, "https://example.com/post", status=LinkStatus.ENRICHED)
    other_day = await add_import(
        db_session,
        "https://example.com/post",
        status=LinkStatus.ENRICHED,
        shared_at=datetime(2026, 8, 1, tzinfo=UTC),
    )
    same_message = await add_import(
        db_session, "https://example.com/post", status=LinkStatus.ENRICHED, shared_at=when
    )
    short = await add_import(db_session, "https://t.co/xyz", note="via x", shared_at=when)
    respx.get("https://t.co/xyz").respond(301, headers={"Location": "https://example.com/post"})

    assert await claim_due_import_links(db_session, limit=10) == [(short.id, "t.co")]
    await enrich_link(db_session, http, short.id, thumbnail_dir=tmp_path)

    assert await db_session.get(Link, short.id) is None
    await db_session.refresh(same_message)
    assert same_message.share_count == 2
    assert same_message.note == "via x"
    for untouched in (live, other_day):
        await db_session.refresh(untouched)
        assert untouched.share_count == 1


@respx.mock
async def test_imported_short_link_is_not_merged_into_a_live_link(
    db_session: AsyncSession, http: httpx.AsyncClient, tmp_path: Path
) -> None:
    live = await add_link(db_session, "https://example.com/post", status=LinkStatus.ENRICHED)
    short = await add_import(db_session, "https://t.co/xyz")
    respx.get("https://t.co/xyz").respond(301, headers={"Location": "https://example.com/post"})
    respx.get("https://example.com/post").respond(200, html="<title>Post</title>")

    await claim_due_import_links(db_session, limit=10)
    await enrich_link(db_session, http, short.id, thumbnail_dir=tmp_path)

    await db_session.refresh(short)
    assert short.normalized_url == "https://example.com/post"
    assert short.status is LinkStatus.ENRICHED
    await db_session.refresh(live)
    assert live.share_count == 1


# --- worker loop ---


@respx.mock
async def test_run_once_enriches_a_batch(
    connection: AsyncConnection, db_session: AsyncSession, tmp_path: Path, settings: Settings
) -> None:
    link = await add_link(db_session, "https://example.com/post")
    respx.get("https://example.com/post").respond(200, html="<title>Hello</title>")
    # Sessions for the worker on the test's connection, so everything is still rolled back.
    sessionmaker = async_sessionmaker(
        bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False
    )
    worker_settings = settings.model_copy(update={"thumbnail_dir": tmp_path})

    throttle = DomainThrottle(delay_seconds=0)

    async with build_http_client(max_connections=2) as http:
        assert await run_once(sessionmaker, http, worker_settings, throttle) == 1
        assert await run_once(sessionmaker, http, worker_settings, throttle) == 0

    await db_session.refresh(link)
    assert link.status is LinkStatus.ENRICHED
    assert link.title == "Hello"


async def test_run_once_survives_a_crashing_link(
    connection: AsyncConnection,
    db_session: AsyncSession,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await add_link(db_session, "https://example.com/post")

    async def explode(*args, **kwargs) -> None:
        raise RuntimeError("bug")

    monkeypatch.setattr("app.worker.enrich_link", explode)
    sessionmaker = async_sessionmaker(
        bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False
    )
    async with build_http_client(max_connections=2) as http:
        assert await run_once(sessionmaker, http, settings, DomainThrottle(delay_seconds=0)) == 1
