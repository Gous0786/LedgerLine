"""Application settings, loaded from environment / .env."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # -- server ---------------------------------------------------------
    host: str = "127.0.0.1"
    port: int = 8000
    log_level: str = "info"

    # Vite dev server origins allowed to call this API.
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    # -- storage --------------------------------------------------------
    # SQLite is the system of record: uploaded CSVs land in their own
    # dynamically-created tables, so no fixed reconciliation schema is
    # imposed up front.
    db_path: Path = BACKEND_ROOT / "data" / "recon.db"
    upload_dir: Path = BACKEND_ROOT / "data" / "uploads"

    # -- models (LiteLLM -> OpenRouter) ---------------------------------
    # LiteLLM routes any "openrouter/<vendor>/<model>" id through OpenRouter
    # using OPENROUTER_API_KEY. Per-role ids so a cheap model can drive
    # mechanical steps while a stronger one handles judgement.
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"

    model_orchestrator: str = "openrouter/stealth/ox-alpha"
    model_worker: str = "openrouter/stealth/ox-alpha"

    def ensure_dirs(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.upload_dir.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_dirs()
    return settings
