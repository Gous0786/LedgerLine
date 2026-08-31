"""Turn a run into numbers, with the safety number first.

Precision and recall on MATCHED are the familiar pair, but they are not the
number that matters most here. A reconciliation system that misses a match
costs someone an afternoon; one that *claims* a match that is not real puts a
wrong figure in front of a person who then signs off on it. So the headline is
the false auto-match rate: of the groups this system would have released
without a human, how many were not actually matches.

It is computed only over auto-acceptable confidences, because that is the set
that would really have been released. Counting hand-reviewed proposals in it
would flatter the number by mixing in decisions a person was always going to
check.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from app.eval.fixture import EXCEPTION, MATCHED, MISSING
from app.eval.runner import RunResult

log = logging.getLogger(__name__)

STATES = (MATCHED, EXCEPTION, MISSING)


@dataclass
class Scores:
    scope: str
    total: int
    confusion: dict[str, dict[str, int]]
    correct: int
    accuracy: float
    precision: float | None
    recall: float | None
    f1: float | None
    false_auto_matches: int
    auto_accepted: int
    false_auto_match_rate: float | None
    member_exact: int
    member_checked: int
    by_outcome: dict[str, dict[str, int]] = field(default_factory=dict)
    examples: list[dict[str, Any]] = field(default_factory=list)


def _ratio(numerator: int, denominator: int) -> float | None:
    return (numerator / denominator) if denominator else None


def score(result: RunResult, scope: str | None = None) -> Scores:
    expectations = [
        e for e in result.fixture.expectations
        if scope is None or e.scope == scope
    ]
    confusion = {a: {p: 0 for p in STATES} for a in STATES}
    by_outcome: dict[str, dict[str, int]] = {}
    examples: list[dict[str, Any]] = []

    auto_accepted = 0
    false_auto = 0
    member_exact = 0
    member_checked = 0
    # A false auto-match is also a misclassification; listing it under both
    # headings just pads the report with the same row twice.
    shown: set[str] = set()

    for e in expectations:
        v = result.verdicts.get(e.work_key)
        predicted = v.state if v else MISSING
        confusion[e.outcome][predicted] += 1

        bucket = by_outcome.setdefault(
            e.raw_outcome, {"n": 0, "correct": 0}
        )
        bucket["n"] += 1
        if predicted == e.outcome:
            bucket["correct"] += 1

        if v and v.auto_acceptable:
            auto_accepted += 1
            if e.outcome != MATCHED:
                false_auto += 1
                if len(examples) < 15:
                    shown.add(e.work_key)
                    examples.append({
                        "work_key": e.work_key,
                        "scope": e.scope,
                        "expected": e.raw_outcome,
                        "predicted": predicted,
                        "confidence": v.confidence,
                        "rules": v.rules,
                        "balance_minor": v.balance_minor,
                        "kind": "false auto-match",
                    })

        # Did the group actually contain the rows ground truth says it should?
        # A right answer reached with the wrong rows is luck, not a match.
        if v and v.state == MATCHED and e.members:
            wanted = {x for k, x in e.members.items() if k != "settlement_batch_id"}
            if wanted:
                member_checked += 1
                if wanted <= v.member_values:
                    member_exact += 1

        if predicted != e.outcome and e.work_key not in shown and len(examples) < 15:
            shown.add(e.work_key)
            examples.append({
                "work_key": e.work_key,
                "scope": e.scope,
                "expected": e.raw_outcome,
                "predicted": predicted,
                "confidence": v.confidence if v else None,
                "rules": v.rules if v else [],
                "kind": "misclassified",
            })

    total = len(expectations)
    correct = sum(confusion[s][s] for s in STATES)

    tp = confusion[MATCHED][MATCHED]
    fp = sum(confusion[a][MATCHED] for a in STATES if a != MATCHED)
    fn = sum(confusion[MATCHED][p] for p in STATES if p != MATCHED)
    precision = _ratio(tp, tp + fp)
    recall = _ratio(tp, tp + fn)
    f1 = (
        2 * precision * recall / (precision + recall)
        if precision and recall and (precision + recall)
        else None
    )

    return Scores(
        scope=scope or "ALL",
        total=total,
        confusion=confusion,
        correct=correct,
        accuracy=_ratio(correct, total) or 0.0,
        precision=precision,
        recall=recall,
        f1=f1,
        false_auto_matches=false_auto,
        auto_accepted=auto_accepted,
        false_auto_match_rate=_ratio(false_auto, auto_accepted),
        member_exact=member_exact,
        member_checked=member_checked,
        by_outcome=by_outcome,
        examples=examples,
    )


def score_all(result: RunResult) -> dict[str, Scores]:
    scopes = sorted({e.scope for e in result.fixture.expectations})
    out = {"ALL": score(result, None)}
    for s in scopes:
        out[s] = score(result, s)
    return out


def as_dict(result: RunResult, scores: dict[str, Scores]) -> dict[str, Any]:
    """Machine-readable form, for CI to diff between commits."""
    return {
        "fixture": result.fixture.name,
        "datasets": {d["name"]: d["row_count"] for d in result.datasets},
        "automatch": {
            "rules_run": result.automatch.get("rules_run"),
            "groups_proposed": result.automatch.get("groups_proposed"),
            "declined": result.automatch.get("declined", []),
            "strategies": [
                {k: r.get(k) for k in ("rule", "shape", "strategy", "agreement",
                                       "tolerance_minor", "proposed")}
                for r in result.automatch.get("results", [])
            ],
        },
        "verification": {
            "verified": result.verification.get("verified"),
            "passed": result.verification.get("passed"),
            "failed": result.verification.get("failed"),
        },
        "unlabelled_keys_matched": len(result.matched_unlabelled),
        "scores": {
            name: {
                "total": s.total,
                "accuracy": s.accuracy,
                "precision": s.precision,
                "recall": s.recall,
                "f1": s.f1,
                "auto_accepted": s.auto_accepted,
                "false_auto_matches": s.false_auto_matches,
                "false_auto_match_rate": s.false_auto_match_rate,
                "member_exact": s.member_exact,
                "member_checked": s.member_checked,
                "confusion": s.confusion,
                "by_outcome": s.by_outcome,
            }
            for name, s in scores.items()
        },
    }
