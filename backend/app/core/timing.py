"""Is this group's timing normal for its rule?

A batch can tie to the penny and still be wrong: the money arrived, but eleven
days after the processor released it, and somebody needs to know that. Amounts
cannot see it, so nothing in the matching path can.

The obvious implementation is a settlement window -- "three days" -- and it is
the wrong one. Three days is a fact about one payment processor's contract, not
about reconciliation, and a system that hard-codes it silently misreads every
dataset whose terms differ. There is no correct constant to pick.

So nothing is assumed. The lag between the two sides of a match is *measured*
across every group the same rule produced, and a group is anomalous when it sits
outside that distribution -- the same principle the rest of this system runs on,
where join keys are found by measured overlap and amount columns by measured
agreement rather than by name.

Deliberately conservative, because a false exception is worse than a missed one
here: it sends a reviewer to look at a transaction that was fine, and enough of
those and the queue gets ignored.

*   A distribution needs a population. Below `MIN_GROUPS` there is no baseline
    and the check abstains rather than guessing.
*   Only *late* is a finding. A group that settled faster than usual is not a
    break, and flagging it would be noise.
*   A degenerate spread (every group identical) needs an absolute floor too,
    or one second of jitter reads as an outlier.

**Why a gap and not a fence.** The first version used Tukey's fence on the
interquartile range, and it worked on one dataset and silently failed on
another with the same underlying behaviour. Measured, both had settlements
landing in 1-2 days and late ones at exactly 7; the only difference was how
many were late -- 19% against 31%. At 31% the third quartile lands *inside* the
late cluster, the IQR triples, and the fence moves out past the very values it
exists to catch. Any tail test breaks down once the tail is big enough, and
"how much of this dataset is broken" is not something a reconciler gets to
assume.

Late settlement is not a tail, it is a second mode: a tight cluster of normal
lags and a separate cluster of late ones, with clear air between. So the split
is found where that air is -- the largest gap between consecutive lags, taken
only when it dwarfs the spread of everything below it and leaves the flagged
group in the minority. That reads 19% and 31% identically, because it keys on
the shape rather than the proportion. Tukey stays as the fallback for a genuinely
continuous distribution, where there is no gap to find.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from typing import Any

log = logging.getLogger(__name__)

# Fewer groups than this and there is no distribution to speak of.
MIN_GROUPS = 8

# Tukey's fence, used only when no second cluster is found. 1.5x the
# interquartile range above the third quartile is the textbook outlier
# definition, and assumes nothing about the shape of the distribution -- but it
# does assume outliers are rare, which is why it is the fallback and not the
# primary. See the module docstring.
IQR_MULTIPLIER = 1.5

# How much bigger than the spread below it a gap must be before it counts as
# separating two clusters rather than being ordinary variation.
GAP_DOMINANCE = 1.5

# A split that flags more than this share of groups is not describing an
# exception, it is describing the dataset.
MAX_FLAGGED_SHARE = 0.5

# When the spread is degenerate -- every batch settling in exactly two days --
# the fence collapses onto the median and ordinary jitter becomes an outlier.
# A group must also exceed the baseline by this much in absolute terms.
MIN_ABSOLUTE_GAP_SECONDS = 12 * 3600

_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}")
_DATE_ONLY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_instant(value: Any) -> datetime | None:
    """Only unambiguous ISO-shaped values. A DD/MM/YYYY column would sort by
    day-of-month, which is worse than having no timing signal at all."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not (_ISO.match(s) or _DATE_ONLY.match(s)):
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def _quantile(sorted_values: list[float], q: float) -> float:
    """Linear-interpolated quantile; no numpy dependency for four numbers."""
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return sorted_values[0]
    pos = (len(sorted_values) - 1) * q
    low = int(pos)
    high = min(low + 1, len(sorted_values) - 1)
    frac = pos - low
    return sorted_values[low] * (1 - frac) + sorted_values[high] * frac


def group_span_seconds(rows: list[dict[str, Any]]) -> float | None:
    """How far apart in time the members of one group are.

    Every ISO-shaped value in every member row counts, rather than a nominated
    column: which column carries the meaningful instant differs per source, and
    the widest gap is what a late settlement widens.
    """
    instants: list[datetime] = []
    for row in rows:
        for value in row.values():
            found = parse_instant(value)
            if found is not None:
                instants.append(found)
    if len(instants) < 2:
        return None
    # Sources mix aware and naive stamps -- a processor emits `...Z`, a bank
    # exports a bare date. Subtracting the two raises, so naive values are read
    # as UTC. That can be wrong by hours; it cannot be wrong by the days a late
    # settlement is measured in.
    if any(i.tzinfo is not None for i in instants):
        instants = [
            i if i.tzinfo is not None else i.replace(tzinfo=UTC) for i in instants
        ]
    return (max(instants) - min(instants)).total_seconds()


def _dominant_gap(ordered: list[float], median: float) -> float | None:
    """The lag above which a separate, later cluster begins -- if there is one.

    Returns the last value *before* the gap, so `span > threshold` selects the
    upper cluster exactly.
    """
    if len(ordered) < MIN_GROUPS:
        return None
    lowest = ordered[0]
    best: tuple[float, float] | None = None
    for i in range(len(ordered) - 1):
        below, above = ordered[i], ordered[i + 1]
        # Only ever split off a *late* tail; an unusually fast settlement is
        # not a finding, and splitting below the median would invert the test.
        if below < median:
            continue
        gap = above - below
        if gap < MIN_ABSOLUTE_GAP_SECONDS:
            continue
        # The jump has to dwarf the ordinary spread of normal behaviour,
        # otherwise every distribution has a "largest gap" and this degenerates
        # into flagging the slowest group in every dataset.
        spread = max(below - lowest, MIN_ABSOLUTE_GAP_SECONDS)
        if gap <= spread * GAP_DOMINANCE:
            continue
        # Whatever the majority does is by definition not the exception.
        if (len(ordered) - i - 1) > len(ordered) * MAX_FLAGGED_SHARE:
            continue
        if best is None or gap > best[0]:
            best = (gap, below)
    return best[1] if best else None


class Baseline:
    """What normal looks like for one rule."""

    def __init__(self, spans: list[float]) -> None:
        self.samples = len(spans)
        ordered = sorted(spans)
        self.median = _quantile(ordered, 0.5)
        q1 = _quantile(ordered, 0.25)
        q3 = _quantile(ordered, 0.75)
        self.iqr = q3 - q1

        split = _dominant_gap(ordered, self.median)
        if split is not None:
            self.method = "gap"
            self.threshold = split
        else:
            # No second cluster: fall back to a tail test, which is the right
            # shape for a continuous distribution.
            self.method = "fence"
            self.threshold = max(
                q3 + IQR_MULTIPLIER * self.iqr,
                self.median + MIN_ABSOLUTE_GAP_SECONDS,
            )

    @property
    def usable(self) -> bool:
        return self.samples >= MIN_GROUPS

    def is_late(self, span: float | None) -> bool:
        return self.usable and span is not None and span > self.threshold

    def describe(self, span: float | None) -> str:
        if not self.usable:
            return (f"only {self.samples} group(s) with timestamps;"
                    " too few to establish a normal settlement lag")
        if span is None:
            return "this group carries no comparable timestamps"
        return (
            f"spans {span / 3600:.1f}h against a typical"
            f" {self.median / 3600:.1f}h for this rule"
            f" (flagged above {self.threshold / 3600:.1f}h by {self.method},"
            f" from {self.samples} groups)"
        )
