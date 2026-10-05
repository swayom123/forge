"""Process configuration; no credentials are stored in source."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Settings loaded from environment or a local .env file."""

    model_config = SettingsConfigDict(env_prefix="FORGE_", env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./forge.db"
    log_level: str = "INFO"
    repository_max_files: int = 10_000
    repository_max_file_bytes: int = 1_000_000
    repository_ignored_directories: str = ""


@lru_cache
def get_settings() -> Settings:
    """Return cached process settings."""
    return Settings()
