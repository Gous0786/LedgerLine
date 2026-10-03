"""Public demo support: sample data on hand, and limits on the paid parts.

A demo link is opened by people who have never seen the app and will not read
instructions, so it must open with something to reconcile. It is also opened
by anyone at all, with no login, so every chat turn -- which costs real money
on the OpenRouter key -- is rate limited.

Only active when `DEMO_MODE` is set. Nothing here runs in local development.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict, deque
from datetime import date

from app.config import get_settings
from app.core import ingest
from app.db import connection as db

log = logging.getLogger(__name__)

# Loaded in this order, under these names, so the demo always looks the same.
SOURCES = ("erp_ledger", "gateway_transactions", "bank_statement")


def ensure_loaded() -> int:
    """Load the sample files if no dataset is present. Returns how many loaded.

    Left unreconciled on purpose: the point of the demo is watching the agent
    do it.
    """
    if db.query_one("SELECT id FROM dataset WHERE status = 'ready' LIMIT 1"):
        return 0
    directory = get_settings().demo_data_dir
    loaded = 0
    for name in SOURCES:
        path = directory / f"{name}.csv"
        if not path.exists():
            log.warning("demo file missing: %s", path)
            continue
        ingest.ingest_csv(path, name=name, original_name=path.name)
        loaded += 1
    log.info("demo data loaded: %d files", loaded)
    return loaded


class ChatLimiter:
    """Turns per visitor per hour, and turns per day across everyone.

    The per-visitor limit keeps one person from using up the day. The daily cap
    is the real backstop: the visitor is identified by IP, which a determined
    caller can vary, but the daily total cannot be got around.

    In memory, so a restart clears it. That is acceptable for a demo; the
    spending limit on the OpenRouter key is the hard ceiling.
    """

    def __init__(self, per_ip_per_hour: int, per_day: int) -> None:
        self.per_ip_per_hour = per_ip_per_hour
        self.per_day = per_day
        self._recent: dict[str, deque[float]] = defaultdict(deque)
        self._day = date.today()
        self._today = 0

    def check(self, visitor: str) -> str | None:
        """Record a turn and return None, or return why it is refused."""
        now = time.monotonic()
        if date.today() != self._day:
            self._day, self._today = date.today(), 0
            self._recent.clear()

        if self._today >= self.per_day:
            return (
                "The demo has reached its limit of chat turns for today. Please"
                " come back tomorrow. Everything else (matches, chains and the"
                " report) still works."
            )

        hits = self._recent[visitor]
        while hits and now - hits[0] > 3600:
            hits.popleft()
        if len(hits) >= self.per_ip_per_hour:
            wait = int(3600 - (now - hits[0])) // 60 + 1
            return (
                f"This demo allows {self.per_ip_per_hour} chat turns per hour per"
                f" visitor. Please try again in about {wait} minutes."
            )

        hits.append(now)
        self._today += 1
        return None


_limiter: ChatLimiter | None = None


def limiter() -> ChatLimiter:
    global _limiter
    if _limiter is None:
        s = get_settings()
        _limiter = ChatLimiter(s.demo_chat_per_ip_per_hour, s.demo_chat_per_day)
    return _limiter
