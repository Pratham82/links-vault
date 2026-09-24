import json
import logging
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
import respx
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from telegram import Update
from telegram.ext import Application

from app.bot.telegram import (
    API_ERROR_TEXT,
    HELP_TEXT,
    NO_LINKS_TEXT,
    ApiError,
    LinkVaultClient,
    NoLinksError,
    build_application,
    format_reply,
    main,
    message_text,
)
from app.config import BotSettings, get_bot_settings
from app.models import Link, SourceChannel
from app.schemas import IngestResult

TOKEN = "123456:TEST-TOKEN"
OWNER_ID = 42
STRANGER_ID = 666
MESSAGE_DATE = datetime(2026, 9, 24, 16, 45, tzinfo=UTC)
TELEGRAM_API = f"https://api.telegram.org/bot{TOKEN}"


def make_update(
    text: str | None = None,
    *,
    user_id: int = OWNER_ID,
    caption: str | None = None,
    entities: list[dict[str, Any]] | None = None,
    **extra: Any,
) -> dict[str, Any]:
    message: dict[str, Any] = {
        "message_id": 7,
        "date": int(MESSAGE_DATE.timestamp()),
        "chat": {"id": user_id, "type": "private"},
        "from": {"id": user_id, "is_bot": False, "first_name": "Pratham", "username": "pratham"},
        **extra,
    }
    if text is not None:
        message["text"] = text
        if entities:
            message["entities"] = entities
    if caption is not None:
        message["caption"] = caption
        if entities:
            message["caption_entities"] = entities
    return {"update_id": 1, "message": message}


def parse_message(data: dict[str, Any]):
    return Update.de_json(data, bot=None).message


# --- settings ---


def test_allowed_user_ids_are_read_from_comma_separated_env(monkeypatch) -> None:
    monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", "123, 456,")
    settings = BotSettings(_env_file=None, api_key="k")
    assert settings.telegram_allowed_user_ids == frozenset({123, 456})


def test_allowed_user_ids_default_to_nobody(monkeypatch) -> None:
    monkeypatch.delenv("TELEGRAM_ALLOWED_USER_IDS", raising=False)
    assert BotSettings(_env_file=None, api_key="k").telegram_allowed_user_ids == frozenset()


def test_allowed_user_ids_reject_non_numbers(monkeypatch) -> None:
    monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", "123,@pratham")
    with pytest.raises(ValidationError):
        BotSettings(_env_file=None, api_key="k")


def test_main_exits_with_hint_when_token_missing(monkeypatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "")
    get_bot_settings.cache_clear()
    try:
        with pytest.raises(SystemExit, match="TELEGRAM_BOT_TOKEN is not set"):
            main()
    finally:
        get_bot_settings.cache_clear()


# --- message_text ---


def test_message_text_uses_text() -> None:
    assert message_text(parse_message(make_update("look https://a.com"))) == "look https://a.com"


def test_message_text_uses_caption() -> None:
    message = parse_message(make_update(caption="https://a.com", photo=[]))
    assert message_text(message) == "https://a.com"


def test_message_text_appends_hidden_link_urls() -> None:
    entities = [
        {"type": "text_link", "offset": 5, "length": 4, "url": "https://a.com/post"},
        {"type": "text_link", "offset": 10, "length": 5, "url": "https://b.com"},
        # Same URL twice, and one already visible in the text: both appended at most once.
        {"type": "text_link", "offset": 16, "length": 2, "url": "https://a.com/post"},
    ]
    message = parse_message(make_update("read this thing ok https://b.com", entities=entities))
    assert message_text(message) == "read this thing ok https://b.com\nhttps://a.com/post"


def test_message_text_is_none_without_text() -> None:
    assert (
        message_text(parse_message(make_update(location={"latitude": 1.0, "longitude": 2.0})))
        is None
    )


# --- format_reply ---


def _result(created: list[str], duplicates: list[str]) -> IngestResult:
    def link(url: str) -> dict[str, Any]:
        return {
            "id": "00000000-0000-0000-0000-000000000001",
            "url": url,
            "normalized_url": url,
            "source_channel": "telegram",
            "sender": "@pratham",
            "note": None,
            "title": None,
            "description": None,
            "image_url": None,
            "site_name": None,
            "content_type": "other",
            "tags": [],
            "status": "pending",
            "share_count": 1,
            "shared_at": MESSAGE_DATE.isoformat(),
            "created_at": MESSAGE_DATE.isoformat(),
            "updated_at": MESSAGE_DATE.isoformat(),
        }

    return IngestResult.model_validate(
        {"created": [link(u) for u in created], "duplicates": [link(u) for u in duplicates]}
    )


@pytest.mark.parametrize(
    ("created", "duplicates", "expected"),
    [
        (["https://a.com"], [], "Saved 1 link:\n• https://a.com"),
        (
            ["https://a.com", "https://b.com"],
            [],
            "Saved 2 links:\n• https://a.com\n• https://b.com",
        ),
        ([], ["https://a.com"], "Already saved:\n• https://a.com"),
        (
            ["https://a.com"],
            ["https://b.com"],
            "Saved 1 link:\n• https://a.com\nAlready saved:\n• https://b.com",
        ),
    ],
)
def test_format_reply(created: list[str], duplicates: list[str], expected: str) -> None:
    assert format_reply(_result(created, duplicates)) == expected


# --- LinkVaultClient (API mocked with respx) ---


@pytest.fixture
async def api_client() -> AsyncIterator[LinkVaultClient]:
    async with httpx.AsyncClient(base_url="http://api.test") as http:
        yield LinkVaultClient(http)


@respx.mock
async def test_client_posts_message_as_telegram(api_client: LinkVaultClient) -> None:
    route = respx.post("http://api.test/links").respond(
        201, json=_result(["https://a.com"], []).model_dump(mode="json")
    )

    result = await api_client.ingest(
        text="https://a.com", sender="@pratham", shared_at=MESSAGE_DATE
    )

    assert [link.url for link in result.created] == ["https://a.com"]
    assert json.loads(route.calls.last.request.content) == {
        "text": "https://a.com",
        "source_channel": "telegram",
        "sender": "@pratham",
        "shared_at": "2026-09-24T16:45:00+00:00",
    }


@respx.mock
async def test_client_raises_no_links_on_422_detail(api_client: LinkVaultClient) -> None:
    respx.post("http://api.test/links").respond(
        422, json={"detail": "No http(s) URLs found in text"}
    )
    with pytest.raises(NoLinksError):
        await api_client.ingest(text="hi", sender="s", shared_at=MESSAGE_DATE)


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(401, json={"detail": "Missing or invalid X-API-Key header"}),
        httpx.Response(422, json={"detail": [{"msg": "field required"}]}),
        httpx.Response(422, text="not json"),
        httpx.Response(500, text="boom"),
    ],
)
@respx.mock
async def test_client_raises_api_error_on_unexpected_response(
    api_client: LinkVaultClient, response: httpx.Response
) -> None:
    respx.post("http://api.test/links").mock(return_value=response)
    with pytest.raises(ApiError):
        await api_client.ingest(text="https://a.com", sender="s", shared_at=MESSAGE_DATE)


@respx.mock
async def test_client_raises_api_error_when_unreachable(api_client: LinkVaultClient) -> None:
    respx.post("http://api.test/links").mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(ApiError):
        await api_client.ingest(text="https://a.com", sender="s", shared_at=MESSAGE_DATE)


# --- the whole bot: Telegram mocked with respx, API served in-process against the test DB ---


def _telegram_ok(result: Any) -> httpx.Response:
    return httpx.Response(200, json={"ok": True, "result": result})


def _echo_sent_message(request: httpx.Request) -> httpx.Response:
    # Telegram answers sendMessage with the Message it created.
    params = dict(httpx.QueryParams(request.content.decode()))
    return _telegram_ok(
        {
            "message_id": 8,
            "date": int(MESSAGE_DATE.timestamp()),
            "chat": {"id": int(params["chat_id"]), "type": "private"},
            "text": params["text"],
        }
    )


@pytest.fixture
def telegram() -> Iterator[respx.MockRouter]:
    with respx.mock(base_url=TELEGRAM_API, assert_all_called=False) as router:
        router.post("/getMe").mock(
            return_value=_telegram_ok(
                {"id": 1, "is_bot": True, "first_name": "Link Vault", "username": "vault_bot"}
            )
        )
        router.post("/sendMessage", name="send").mock(side_effect=_echo_sent_message)
        yield router


async def _application(http_client: httpx.AsyncClient) -> Application:
    settings = BotSettings(
        _env_file=None,
        api_key="unused",
        telegram_bot_token=TOKEN,
        telegram_allowed_user_ids="42",
    )
    application = build_application(settings, http_client=http_client)
    await application.initialize()
    return application


@pytest.fixture
async def bot_app(client: httpx.AsyncClient, telegram) -> AsyncIterator[Application]:
    # `client` is the test API client (in-process app, test DB, valid API key).
    application = await _application(client)
    yield application
    await application.shutdown()


async def send(application: Application, data: dict[str, Any]) -> None:
    await application.process_update(Update.de_json(data, application.bot))


def sent_texts(telegram: respx.MockRouter) -> list[str]:
    return [
        dict(httpx.QueryParams(call.request.content.decode()))["text"]
        for call in telegram["send"].calls
    ]


async def test_shared_link_lands_in_db_and_is_confirmed(
    bot_app: Application, telegram: respx.MockRouter, db_session: AsyncSession
) -> None:
    await send(bot_app, make_update("must read https://example.com/post"))

    link = (await db_session.scalars(select(Link))).one()
    assert link.url == "https://example.com/post"
    assert link.note == "must read"
    assert link.source_channel == SourceChannel.TELEGRAM
    assert link.sender == "@pratham"
    assert link.shared_at == MESSAGE_DATE
    assert sent_texts(telegram) == ["Saved 1 link:\n• https://example.com/post"]
    reply = dict(httpx.QueryParams(telegram["send"].calls.last.request.content.decode()))
    assert reply["chat_id"] == str(OWNER_ID)


async def test_sender_falls_back_to_full_name(
    bot_app: Application, db_session: AsyncSession
) -> None:
    data = make_update("https://example.com")
    data["message"]["from"] = {"id": OWNER_ID, "is_bot": False, "first_name": "A", "last_name": "B"}
    await send(bot_app, data)

    link = (await db_session.scalars(select(Link))).one()
    assert link.sender == "A B"


async def test_unknown_user_is_ignored_and_logged(
    bot_app: Application,
    telegram: respx.MockRouter,
    db_session: AsyncSession,
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING, logger="app.bot.telegram"):
        await send(bot_app, make_update("https://example.com", user_id=STRANGER_ID))
        await send(
            bot_app,
            make_update(
                "/start",
                user_id=STRANGER_ID,
                entities=[{"type": "bot_command", "offset": 0, "length": 6}],
            ),
        )

    assert await db_session.scalar(select(func.count()).select_from(Link)) == 0
    assert not telegram["send"].called
    assert f"id={STRANGER_ID}" in caplog.text


async def test_message_without_link_gets_a_hint(
    bot_app: Application, telegram: respx.MockRouter, db_session: AsyncSession
) -> None:
    await send(bot_app, make_update("just a thought"))

    assert await db_session.scalar(select(func.count()).select_from(Link)) == 0
    assert sent_texts(telegram) == [NO_LINKS_TEXT]


@pytest.mark.parametrize(
    "data",
    [
        make_update("/start", entities=[{"type": "bot_command", "offset": 0, "length": 6}]),
        make_update(location={"latitude": 1.0, "longitude": 2.0}),
    ],
    ids=["start", "no-text"],
)
async def test_start_and_non_text_messages_get_help(
    bot_app: Application, telegram: respx.MockRouter, data: dict[str, Any]
) -> None:
    await send(bot_app, data)
    assert sent_texts(telegram) == [HELP_TEXT]


async def test_api_failure_is_reported_to_user(
    telegram: respx.MockRouter, caplog: pytest.LogCaptureFixture
) -> None:
    def api_down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    async with httpx.AsyncClient(
        base_url="http://api.test", transport=httpx.MockTransport(api_down)
    ) as http:
        application = await _application(http)
        with caplog.at_level(logging.ERROR, logger="app.bot.telegram"):
            await send(application, make_update("https://example.com"))
        await application.shutdown()

    assert sent_texts(telegram) == [API_ERROR_TEXT]
    [record] = caplog.records
    assert "Could not reach the API at http://api.test" in record.getMessage()
    assert record.exc_info is None
