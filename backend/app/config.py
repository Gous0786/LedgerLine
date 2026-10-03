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

    # The system prompt and tool schemas are byte-identical on every turn and
    # are re-sent each time. Marking them cacheable turns that repeated cost
    # into a cache read. Anthropic models honour this reliably; others vary,
    # and it is inert where unsupported.
    enable_prompt_cache: bool = True

    # A single model call has been measured at 6-35 seconds through OpenRouter
    # on a model that should answer in one or two, and one turn died at 34s with
    # a mid-stream timeout. So the ceiling is stated here rather than inherited,
    # and a stalled call is retried instead of losing the turn.
    model_timeout_seconds: float = 120.0
    model_retries: int = 2

    # OpenRouter routes to whichever provider is serving a model; some are far
    # slower than others. Asking it to sort by throughput is the one lever that
    # attacks per-call latency directly. Inert on providers that ignore it.
    prefer_fast_provider: bool = True

    # Models to try when a call fails mid-stream. The observed failure is
    # `MidStreamFallbackError` -- litellm reporting that the stream broke and it
    # had nothing to fall back to. The break is OpenRouter's upstream provider
    # aborting (`error_type: timeout`), not our client timing out, so no client
    # setting prevents it: the only cure is somewhere else to go.
    # e.g. MODEL_FALLBACKS='["openrouter/anthropic/claude-haiku-4.5"]'
    model_fallbacks: list[str] = []

    model_orchestrator: str = "openrouter/stealth/ox-alpha"

    # -- public demo ----------------------------------------------------
    # For a deployment anyone can open. There is no login, so the limits below
    # are what stand between a stranger and the OpenRouter bill. Set a spending
    # limit on the key as well; these counters live in memory and restart with
    # the process.
    demo_mode: bool = False
    demo_data_dir: Path = BACKEND_ROOT.parent / "demo" / "data"
    demo_chat_per_ip_per_hour: int = 8
    demo_chat_per_day: int = 150
    demo_max_upload_bytes: int = 2 * 1024 * 1024

    # The built frontend (`npm run build`). Served from `/` when present, so a
    # deployment is one process on one port. Absent in local development,
    # where Vite serves it instead.
    frontend_dist: Path = BACKEND_ROOT.parent / "frontend" / "dist"

    def ensure_dirs(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.upload_dir.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_dirs()
    return settings
