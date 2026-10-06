"""Process configuration; no credentials are stored in source."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Settings loaded from environment or a local .env file."""

    model_config = SettingsConfigDict(env_prefix="FORGE_", env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./forge.db"
    log_level: str = "INFO"
    repository_max_files: int = 10_000
    repository_max_file_bytes: int = 1_000_000
    repository_ignored_directories: str = ""
    worktree_root: Path = Path("/tmp/forge-worktrees")
    worktree_max_files: int = 20_000
    worktree_max_bytes: int = 500_000_000
    patch_max_bytes: int = 1_000_000
    sandbox_bwrap_path: Path = Path("/usr/bin/bwrap")
    sandbox_prlimit_path: Path = Path("/usr/bin/prlimit")
    sandbox_timeout_seconds: int = 120
    sandbox_cpu_seconds: int = 60
    sandbox_memory_bytes: int = 1_073_741_824
    sandbox_file_bytes: int = 52_428_800
    sandbox_output_bytes: int = 1_000_000
    sandbox_max_processes: int = 64
    sandbox_max_open_files: int = 256
    verification_max_failed_attempts: int = 3


@lru_cache
def get_settings() -> Settings:
    """Return cached process settings."""
    return Settings()
