"""Count what the pipeline actually asks the database, and how often twice.

Redundant work in this system does not look like a slow query. It looks like
`find_join_candidates` -- an O(columns squared) value-overlap scan -- being
called from three places in one reconciliation because each of them needed the
answer and none of them knew the others had already computed it. That is
invisible in a profiler sorted by single-call duration and obvious the moment
you count calls by shape.

So this groups every statement by its *shape*: literals stripped, so the same
query against a different id counts as a repeat. A shape with a high count and
a high total cost is the thing to memoise; a shape called once is not
interesting however slow it is.

Deliberately a monkeypatch rather than a hook in the data layer. Measuring is
not a feature of the application, and the application should not carry a
counter in production for the sake of an occasional question.
"""

from __future__ import annotations

import contextlib
import logging
import re
import time
from collections import defaultdict
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)

_STRINGS = re.compile(r"'[^']*'")
_NUMBERS = re.compile(r"\b\d+\b")
_WS = re.compile(r"\s+")
_TABLES = re.compile(r"\bds_[0-9a-f]+\b")


def shape(sql: str) -> str:
    """The query with its particulars removed, so repeats collapse together."""
    s = _STRINGS.sub("'?'", sql)
    s = _TABLES.sub("ds_?", s)
    s = _NUMBERS.sub("?", s)
    return _WS.sub(" ", s).strip()


@dataclass
class Stat:
    calls: int = 0
    total_ms: float = 0.0
    callers: set[str] = field(default_factory=set)

    @property
    def avg_ms(self) -> float:
        return self.total_ms / self.calls if self.calls else 0.0


@dataclass
class Profile:
    stats: dict[str, Stat] = field(default_factory=lambda: defaultdict(Stat))
    functions: dict[str, Stat] = field(default_factory=lambda: defaultdict(Stat))

    @property
    def total_calls(self) -> int:
        return sum(s.calls for s in self.stats.values())

    @property
    def total_ms(self) -> float:
        return sum(s.total_ms for s in self.stats.values())

    @property
    def distinct_shapes(self) -> int:
        return len(self.stats)

    @property
    def repeated_calls(self) -> int:
        """Calls that were not the first of their shape -- the waste ceiling."""
        return sum(s.calls - 1 for s in self.stats.values() if s.calls > 1)

    def worst(self, n: int = 12) -> list[tuple[str, Stat]]:
        """Ranked by total time, which is where memoising actually pays."""
        return sorted(self.stats.items(), key=lambda kv: -kv[1].total_ms)[:n]

    def most_repeated(self, n: int = 12) -> list[tuple[str, Stat]]:
        return sorted(self.stats.items(), key=lambda kv: -kv[1].calls)[:n]


def _caller() -> str:
    """The application frame that issued this query, skipping the data layer."""
    import traceback

    for frame in reversed(traceback.extract_stack()[:-2]):
        mod = frame.filename.replace("\\", "/")
        if "/app/" not in mod:
            continue
        if any(part in mod for part in ("/db/", "/eval/profile", "sqlguard")):
            continue
        return f"{mod.rsplit('/app/', 1)[-1]}:{frame.name}"
    return "?"


@contextlib.contextmanager
def profiling() -> Iterator[Profile]:
    """Count database work for the duration of the block."""
    from app.core import sqlguard
    from app.db import connection as db

    prof = Profile()
    originals: list[tuple[Any, str, Any]] = []

    def wrap(module: Any, name: str, sql_arg: int) -> None:
        original = getattr(module, name)
        originals.append((module, name, original))
        label = f"{module.__name__.rsplit('.', 1)[-1]}.{name}"

        def wrapped(*args: Any, **kwargs: Any) -> Any:
            sql = ""
            if len(args) > sql_arg:
                sql = str(args[sql_arg])
            elif "sql" in kwargs:
                sql = str(kwargs["sql"])
            started = time.perf_counter()
            try:
                return original(*args, **kwargs)
            finally:
                ms = (time.perf_counter() - started) * 1000
                key = shape(sql) if sql else label
                st = prof.stats[key]
                st.calls += 1
                st.total_ms += ms
                st.callers.add(_caller())
                fn = prof.functions[label]
                fn.calls += 1
                fn.total_ms += ms

        setattr(module, name, wrapped)

    # sqlguard takes (db_path, sql); the db helpers take (sql, params)
    wrap(sqlguard, "select_all", 1)
    wrap(sqlguard, "select", 1)
    wrap(db, "query", 0)
    wrap(db, "query_one", 0)
    wrap(db, "execute", 0)

    try:
        yield prof
    finally:
        for module, name, original in originals:
            setattr(module, name, original)


def report(prof: Profile) -> None:
    print(f"\n{'=' * 62}\nDATABASE WORK")
    print(f"  {prof.total_calls} calls, {prof.distinct_shapes} distinct shapes,"
          f" {prof.total_ms:.0f} ms total")
    waste = prof.repeated_calls
    print(f"  {waste} calls repeated a shape already seen"
          f" ({waste / prof.total_calls * 100:.0f}% of all calls)")

    print("\n  by entry point:")
    for label, st in sorted(prof.functions.items(), key=lambda kv: -kv[1].total_ms):
        print(f"    {label:<24} {st.calls:>6} calls  {st.total_ms:>8.0f} ms")

    print("\n  costliest query shapes (total ms):")
    for sql, st in prof.worst(8):
        callers = ", ".join(sorted(st.callers)[:2])
        print(f"    {st.calls:>5}x {st.total_ms:>8.1f}ms  {sql[:76]}")
        print(f"           {'':>8}  from {callers}")
