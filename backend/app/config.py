from functools import lru_cache
from typing import Annotated

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    """App configuration, read from environment variables (and `.env` if present)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    api_key: str


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
