from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """App configuration, read from environment variables (and `.env` if present)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    api_key: str


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
