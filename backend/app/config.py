from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    """App configuration, read from environment variables (and `.env` if present)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    api_key: str
    # Worker: links enriched at once, and how long to wait when there's nothing to do.
    preview_concurrency: int = Field(default=5, ge=1, le=50)
    worker_poll_seconds: float = Field(default=5.0, gt=0)
    # Where the worker saves thumbnails and the API serves them from.
    thumbnail_dir: Path = Path("data/thumbnails")
    # Imported links are enriched more gently than live ones, so a backfill of thousands of
    # X/Instagram links doesn't get rate-limited: at most this many at once, and never two
    # fetches from the same site less than IMPORT_DOMAIN_DELAY_SECONDS apart.
    import_preview_concurrency: int = Field(default=2, ge=1, le=20)
    import_domain_delay_seconds: float = Field(default=5.0, ge=0)


class BotSettings(BaseSettings):
    """Telegram bot configuration. The bot talks to the API over HTTP, so it needs no database."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    api_key: str
    api_base_url: str = "http://localhost:8000"
    telegram_bot_token: str = ""
    # NoDecode: read "123,456" as a plain string instead of expecting a JSON list.
    telegram_allowed_user_ids: Annotated[frozenset[int], NoDecode] = frozenset()

    @field_validator("telegram_allowed_user_ids", mode="before")
    @classmethod
    def _split_user_ids(cls, value: object) -> object:
        if isinstance(value, str):
            return frozenset(int(part) for part in value.split(",") if part.strip())
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]


@lru_cache
def get_bot_settings() -> BotSettings:
    return BotSettings()  # type: ignore[call-arg]
