"""Telegram capture bot.

Uses long polling (the bot asks Telegram for new messages), so no public URL is needed.
It saves links by calling the API's `POST /links` over HTTP, like any other client, so all
ingestion still goes through `services/ingest.py`.

Run it with `python -m app.bot.telegram`.
"""

import logging
import sys
from datetime import datetime

import httpx
from telegram import LinkPreviewOptions, Message, MessageEntity, Update
from telegram.ext import (
    Application,
    ApplicationHandlerStop,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    TypeHandler,
    filters,
)

from app.config import BotSettings, get_bot_settings
from app.models import SourceChannel
from app.schemas import IngestResult

logger = logging.getLogger(__name__)

HELP_TEXT = "Send or share a message with a link and I'll save it to Link Vault."
NO_LINKS_TEXT = "I couldn't find a link in that message."
API_ERROR_TEXT = "Sorry, I couldn't save that right now. Please try again in a bit."


class ApiError(Exception):
    """The API could not be reached or returned an unexpected response."""


class NoLinksError(Exception):
    """The API found no http(s) URL in the message."""


class LinkVaultClient:
    """Thin typed wrapper around the Link Vault HTTP API."""

    def __init__(self, http: httpx.AsyncClient) -> None:
        # The client carries base_url and the X-API-Key header.
        self._http = http

    async def ingest(self, *, text: str, sender: str, shared_at: datetime) -> IngestResult:
        body = {
            "text": text,
            "source_channel": SourceChannel.TELEGRAM.value,
            "sender": sender,
            "shared_at": shared_at.isoformat(),
        }
        try:
            response = await self._http.post("/links", json=body)
        except httpx.HTTPError as exc:
            raise ApiError(f"Could not reach the API at {self._http.base_url}: {exc!r}") from exc

        if response.status_code == httpx.codes.CREATED:
            return IngestResult.model_validate(response.json())
        # "No URLs" comes back as a 422 with a plain-string detail; body validation errors
        # are also 422 but carry a list of errors, and those are a bug, not user input.
        if response.status_code == httpx.codes.UNPROCESSABLE_ENTITY:
            try:
                detail = response.json().get("detail")
            except ValueError:
                detail = None
            if isinstance(detail, str):
                raise NoLinksError(detail)
        raise ApiError(f"API returned {response.status_code}: {response.text[:200]}")


def message_text(message: Message) -> str | None:
    """The text to ingest: message text or caption, plus URLs hidden behind linked words."""
    if message.text:
        text, entities = message.text, message.parse_entities([MessageEntity.TEXT_LINK])
    elif message.caption:
        text, entities = message.caption, message.parse_caption_entities([MessageEntity.TEXT_LINK])
    else:
        return None

    # A "text_link" is a word whose URL isn't in the text itself, e.g. [this post](https://…).
    hidden_urls: list[str] = []
    for entity in entities:
        if entity.url and entity.url not in text and entity.url not in hidden_urls:
            hidden_urls.append(entity.url)
    return "\n".join([text, *hidden_urls])


def format_reply(result: IngestResult) -> str:
    lines: list[str] = []
    if result.created:
        noun = "link" if len(result.created) == 1 else "links"
        lines.append(f"Saved {len(result.created)} {noun}:")
        lines.extend(f"• {link.url}" for link in result.created)
    if result.duplicates:
        lines.append("Already saved:")
        lines.extend(f"• {link.url}" for link in result.duplicates)
    return "\n".join(lines)


class LinkVaultBot:
    """Telegram handlers. Only users in `allowed_user_ids` get any response."""

    def __init__(self, client: LinkVaultClient, allowed_user_ids: frozenset[int]) -> None:
        self._client = client
        self._allowed_user_ids = allowed_user_ids

    def register(self, application: Application) -> None:
        # Group -1 runs before every other handler; raising ApplicationHandlerStop there
        # stops the update from reaching them, so the allowlist can't be forgotten.
        application.add_handler(TypeHandler(Update, self.reject_unknown_users), group=-1)
        # Within group 0 only the first matching handler runs.
        application.add_handler(CommandHandler(["start", "help"], self.help))
        application.add_handler(
            MessageHandler(
                filters.UpdateType.MESSAGE & (filters.TEXT | filters.CAPTION) & ~filters.COMMAND,
                self.save_links,
            )
        )
        application.add_handler(MessageHandler(filters.UpdateType.MESSAGE, self.help))

    async def reject_unknown_users(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        user = update.effective_user
        if user is None or user.id not in self._allowed_user_ids:
            # Log (so the owner can find their own ID) but never reply.
            logger.warning(
                "Ignoring update from unauthorized Telegram user id=%s username=%s",
                user.id if user else None,
                user.username if user else None,
            )
            raise ApplicationHandlerStop

    async def help(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.effective_message is not None:
            await update.effective_message.reply_text(HELP_TEXT)

    async def save_links(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        message = update.effective_message
        user = update.effective_user
        if message is None or user is None:
            return
        text = message_text(message)
        if text is None:
            return

        try:
            result = await self._client.ingest(
                text=text,
                sender=f"@{user.username}" if user.username else user.full_name,
                shared_at=message.date,
            )
        except NoLinksError:
            reply = NO_LINKS_TEXT
        except ApiError as exc:
            # The message says what went wrong; a traceback adds nothing for these.
            logger.error(
                "Saving links from Telegram message %s failed: %s", message.message_id, exc
            )
            reply = API_ERROR_TEXT
        else:
            reply = format_reply(result)

        await message.reply_text(reply, link_preview_options=LinkPreviewOptions(is_disabled=True))


def build_application(
    settings: BotSettings, http_client: httpx.AsyncClient | None = None
) -> Application:
    """Wire the bot up. Tests pass their own `http_client` pointed at the in-process API."""
    if http_client is None:
        http_client = httpx.AsyncClient(
            base_url=settings.api_base_url,
            headers={"X-API-Key": settings.api_key, "User-Agent": "link-vault-telegram-bot"},
            timeout=httpx.Timeout(10.0, connect=5.0),
        )

    async def close_http_client(_: Application) -> None:
        await http_client.aclose()

    application = (
        Application.builder()
        .token(settings.telegram_bot_token)
        .post_shutdown(close_http_client)
        .build()
    )
    bot = LinkVaultBot(LinkVaultClient(http_client), settings.telegram_allowed_user_ids)
    bot.register(application)
    return application


def main() -> None:
    logging.basicConfig(
        format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO
    )
    # httpx logs every request URL at INFO, and Telegram URLs contain the bot token.
    logging.getLogger("httpx").setLevel(logging.WARNING)

    settings = get_bot_settings()
    if not settings.telegram_bot_token:
        sys.exit("TELEGRAM_BOT_TOKEN is not set; get one from @BotFather and add it to .env")
    if not settings.telegram_allowed_user_ids:
        logger.warning("TELEGRAM_ALLOWED_USER_IDS is empty, so every message will be ignored")

    application = build_application(settings)
    logger.info("Starting Telegram bot (long polling), API at %s", settings.api_base_url)
    # Only plain new messages; edits, channel posts, etc. are never fetched.
    application.run_polling(allowed_updates=[Update.MESSAGE])


if __name__ == "__main__":
    main()
