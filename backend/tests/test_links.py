from datetime import UTC, datetime

from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ContentType, Link, SourceChannel


async def post_link(client: AsyncClient, text: str, **overrides) -> dict:
    body = {"text": text, "source_channel": "api", "sender": "tester", **overrides}
    response = await client.post("/links", json=body)
    assert response.status_code == 201, response.text
    return response.json()


async def test_create_link_returns_pending_link(client: AsyncClient) -> None:
    data = await post_link(client, "worth a look https://example.com/post")

    assert data["duplicates"] == []
    [link] = data["created"]
    assert link["url"] == "https://example.com/post"
    assert link["normalized_url"] == "https://example.com/post"
    assert link["note"] == "worth a look"
    assert link["source_channel"] == "api"
    assert link["sender"] == "tester"
    assert link["status"] == "pending"
    assert link["content_type"] == "other"
    assert link["tags"] == []
    assert link["share_count"] == 1
    assert link["title"] is None
    assert link["created_at"] is not None


async def test_create_link_persists_every_url(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    data = await post_link(client, "https://a.com/1 https://b.com/2")

    assert [link["url"] for link in data["created"]] == ["https://a.com/1", "https://b.com/2"]
    count = await db_session.scalar(select(func.count()).select_from(Link))
    assert count == 2


async def test_create_link_defaults_shared_at_to_now(client: AsyncClient) -> None:
    before = datetime.now(UTC)
    data = await post_link(client, "https://example.com")
    shared_at = datetime.fromisoformat(data["created"][0]["shared_at"])
    assert before <= shared_at <= datetime.now(UTC)


async def test_create_link_keeps_given_shared_at_in_utc(client: AsyncClient) -> None:
    data = await post_link(client, "https://example.com", shared_at="2026-09-24T22:15:00+05:30")
    shared_at = datetime.fromisoformat(data["created"][0]["shared_at"])
    assert shared_at == datetime(2026, 9, 24, 16, 45, tzinfo=UTC)
    assert shared_at.utcoffset().total_seconds() == 0


async def test_create_link_rejects_naive_shared_at(client: AsyncClient) -> None:
    response = await client.post(
        "/links",
        json={
            "text": "https://example.com",
            "source_channel": "api",
            "sender": "tester",
            "shared_at": "2026-09-24T22:15:00",
        },
    )
    assert response.status_code == 422


async def test_create_link_without_urls_is_rejected(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    response = await client.post(
        "/links", json={"text": "just a note", "source_channel": "api", "sender": "tester"}
    )
    assert response.status_code == 422
    assert response.json() == {"detail": "No http(s) URLs found in text"}
    assert await db_session.scalar(select(func.count()).select_from(Link)) == 0


async def test_create_link_validates_body(client: AsyncClient) -> None:
    response = await client.post(
        "/links", json={"text": "https://example.com", "source_channel": "fax", "sender": "x"}
    )
    assert response.status_code == 422


async def test_get_link_by_id(client: AsyncClient) -> None:
    created = (await post_link(client, "https://example.com"))["created"][0]

    response = await client.get(f"/links/{created['id']}")
    assert response.status_code == 200
    assert response.json() == created


async def test_get_missing_link_is_404(client: AsyncClient) -> None:
    response = await client.get("/links/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404
    assert response.json() == {"detail": "Link not found"}


async def test_get_link_with_malformed_id_is_422(client: AsyncClient) -> None:
    response = await client.get("/links/not-a-uuid")
    assert response.status_code == 422


async def test_list_links_orders_by_shared_at_desc(client: AsyncClient) -> None:
    await post_link(client, "https://old.com", shared_at="2026-01-01T00:00:00Z")
    await post_link(client, "https://new.com", shared_at="2026-03-01T00:00:00Z")
    await post_link(client, "https://mid.com", shared_at="2026-02-01T00:00:00Z")

    response = await client.get("/links")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 3
    assert [link["url"] for link in data["items"]] == [
        "https://new.com",
        "https://mid.com",
        "https://old.com",
    ]


async def test_list_links_paginates(client: AsyncClient) -> None:
    for day in range(1, 6):
        await post_link(client, f"https://example.com/{day}", shared_at=f"2026-01-0{day}T00:00:00Z")

    data = (await client.get("/links", params={"limit": 2, "offset": 2})).json()
    assert data["total"] == 5
    assert data["limit"] == 2
    assert data["offset"] == 2
    assert [link["url"] for link in data["items"]] == [
        "https://example.com/3",
        "https://example.com/2",
    ]


async def test_list_links_rejects_bad_pagination(client: AsyncClient) -> None:
    assert (await client.get("/links", params={"limit": 0})).status_code == 422
    assert (await client.get("/links", params={"limit": 201})).status_code == 422
    assert (await client.get("/links", params={"offset": -1})).status_code == 422


async def test_list_links_filters_by_source(client: AsyncClient) -> None:
    await post_link(client, "https://a.com", source_channel="telegram")
    await post_link(client, "https://b.com", source_channel="api")

    data = (await client.get("/links", params={"source": "telegram"})).json()
    assert [link["url"] for link in data["items"]] == ["https://a.com"]


async def test_list_links_filters_by_date_range(client: AsyncClient) -> None:
    await post_link(client, "https://before.com", shared_at="2026-09-23T23:59:59Z")
    await post_link(client, "https://inside.com", shared_at="2026-09-24T10:00:00Z")
    await post_link(client, "https://after.com", shared_at="2026-09-25T00:00:00Z")

    data = (
        await client.get(
            "/links", params={"from": "2026-09-24T00:00:00Z", "to": "2026-09-25T00:00:00Z"}
        )
    ).json()
    assert [link["url"] for link in data["items"]] == ["https://inside.com"]


async def test_list_links_searches_url_and_note(client: AsyncClient) -> None:
    await post_link(client, "React server components https://a.com/x")
    await post_link(client, "https://react.dev/learn")
    await post_link(client, "https://other.com")

    data = (await client.get("/links", params={"q": "REACT"})).json()
    assert sorted(link["url"] for link in data["items"]) == [
        "https://a.com/x",
        "https://react.dev/learn",
    ]


async def test_list_links_search_treats_wildcards_literally(client: AsyncClient) -> None:
    await post_link(client, "100% worth it https://a.com")
    await post_link(client, "https://b.com")

    data = (await client.get("/links", params={"q": "100%"})).json()
    assert [link["url"] for link in data["items"]] == ["https://a.com"]
    assert (await client.get("/links", params={"q": "%"})).json()["total"] == 1


async def test_list_links_filters_by_type_and_tag(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    # Type and tags are set by the worker in later phases, so seed them directly.
    now = datetime.now(UTC)
    db_session.add_all(
        [
            Link(
                url="https://github.com/o/r",
                normalized_url="https://github.com/o/r",
                source_channel=SourceChannel.API,
                sender="t",
                content_type=ContentType.GITHUB_REPO,
                tags=["ai", "tools"],
                shared_at=now,
            ),
            Link(
                url="https://example.com",
                normalized_url="https://example.com",
                source_channel=SourceChannel.API,
                sender="t",
                tags=["react"],
                shared_at=now,
            ),
        ]
    )
    await db_session.commit()

    by_type = (await client.get("/links", params={"type": "github_repo"})).json()
    assert [link["url"] for link in by_type["items"]] == ["https://github.com/o/r"]

    by_tag = (await client.get("/links", params={"tag": "react"})).json()
    assert [link["url"] for link in by_tag["items"]] == ["https://example.com"]

    assert (await client.get("/links", params={"type": "nope"})).status_code == 422
