"""Run the deterministic pipeline against a fixture and read back its verdict.

No LLM. That is the point: this measures `automatch` + the match engine + the
verifier, which is the part of the system that is supposed to be reproducible.
A score that moved because a model felt different today would not be a score.

Everything happens in a throwaway database. The dev database holds real
uploaded work, and an eval that could touch it would be a tool nobody dares
run -- which is the same as not having one.
"""

from __future__ import annotations

import logging
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.eval.fixture import EXCEPTION, MATCHED, MISSING, Fixture

log = logging.getLogger(__name__)

# Confidences that assert "these rows reconcile".
_CLAIMS_MATCH = ("exact", "within_tolerance", "high")
# ...of which these would be released without a human, once the rule is trusted.
# This is the set the safety metric is computed over.
_AUTO_ACCEPTABLE = ("exact", "within_tolerance")


@dataclass
class Verdict:
    work_key: str
    state: str                       # MATCHED | EXCEPTION | MISSING
    confidence: str | None = None
    auto_acceptable: bool = False
    proposal_ids: list[int] = field(default_factory=list)
    rules: list[str] = field(default_factory=list)
    member_values: set[str] = field(default_factory=set)
    balance_minor: int | None = None


@dataclass
class RunResult:
    fixture: Fixture
    verdicts: dict[str, Verdict]
    automatch: dict[str, Any]
    verification: dict[str, Any]
    datasets: list[dict[str, Any]]
    matched_unlabelled: set[str] = field(default_factory=set)
    # Present only for an --agent run; the deterministic path has no turn.
    agent: Any = None


class _Sandbox:
    """A disposable database, configured everywhere the app reads one from."""

    def __init__(self) -> None:
        self.dir = Path(tempfile.mkdtemp(prefix="recon-eval-"))
        self.db_path = self.dir / "eval.db"

    def __enter__(self) -> _Sandbox:
        from app.config import get_settings
        from app.db import connection as db
        from app.db.migrate import migrate

        self._settings = get_settings()
        self._saved_db = self._settings.db_path
        self._saved_uploads = self._settings.upload_dir

        # Both matter: `db.configure` drives the read/write connection, and
        # `settings.db_path` is what sqlguard opens read-only.
        self._settings.db_path = self.db_path
        self._settings.upload_dir = self.dir / "uploads"
        self._settings.upload_dir.mkdir(parents=True, exist_ok=True)
        db.configure(self.db_path)
        migrate()
        return self

    def __exit__(self, *exc: Any) -> None:
        from app.db import connection as db

        self._settings.db_path = self._saved_db
        self._settings.upload_dir = self._saved_uploads
        db.configure(self._saved_db)
        shutil.rmtree(self.dir, ignore_errors=True)


def _member_values(proposal_id: int) -> set[str]:
    """The identifiers a proposal actually pulled in.

    Ground truth names the rows that belong together by their business ids, so
    checking membership means reading those ids back out of the source rows
    rather than trusting the group key alone.
    """
    from app.config import get_settings
    from app.core import sqlguard
    from app.db import connection as db

    out: set[str] = set()
    rows = db.query(
        "SELECT m.dataset_id, m.row, d.table_name FROM match_member m"
        " JOIN dataset d ON d.id = m.dataset_id WHERE m.proposal_id = ?",
        (proposal_id,),
    )
    for r in rows:
        try:
            found = sqlguard.select_all(
                get_settings().db_path,
                f'SELECT * FROM "{r["table_name"]}" WHERE __row = {int(r["row"])}',
            )
        except Exception:
            continue
        for cell in (found[0] if found else {}).values():
            if isinstance(cell, str) and cell.startswith("SYNTH-"):
                out.add(cell)
    return out


def _collect_verdicts(work_keys: set[str]) -> dict[str, Verdict]:
    """What did the system decide about each labelled key?

    A key with no proposal is MISSING -- the system had nothing to say, which
    against a label of MATCHED is a miss and against MISSING is correct. A key
    whose proposals include an unbalanced or ambiguous one is an EXCEPTION even
    if some other rule matched it cleanly, because the worst thing known about a
    transaction is the thing a reviewer needs to see.
    """
    from app.db import connection as db

    rows = db.query(
        "SELECT id, group_key, rule, confidence, status, balance_minor"
        " FROM match_proposal ORDER BY id"
    )
    grouped: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        grouped.setdefault(str(r["group_key"]), []).append(r)

    # Read once, not once per work key -- and only the *latest* verdict per
    # proposal. A proposal is verified when it is created and again if someone
    # tries to release it, so an early failure that a later pass cleared must
    # not keep counting against it.
    blocked = {
        r["proposal_id"] for r in db.query(
            "SELECT v.proposal_id FROM verification v"
            " WHERE v.id = (SELECT MAX(v2.id) FROM verification v2"
            "               WHERE v2.proposal_id = v.proposal_id)"
            "   AND v.status = 'fail'"
        )
    }

    verdicts: dict[str, Verdict] = {}
    for key in work_keys:
        props = grouped.get(key, [])
        if not props:
            verdicts[key] = Verdict(work_key=key, state=MISSING)
            continue

        # A proposal the verifier refused is not a claimed match. The system's
        # visible output for one is a queued item flagged with why it failed --
        # a mixed-currency group, say -- which is an exception in every sense
        # that matters to a reviewer, and scoring it as a match would credit
        # the system for a mistake its own gate caught.
        confidences = [p["confidence"] for p in props]
        if any(p["status"] != "accepted" and p["id"] in blocked for p in props):
            state = EXCEPTION
            confidence = "verification_failed"
        elif any(c in ("unbalanced", "ambiguous") for c in confidences):
            state = EXCEPTION
            # report the confidence that drove the call, not just the first
            confidence = next(c for c in confidences if c in ("unbalanced", "ambiguous"))
        elif any(c in _CLAIMS_MATCH for c in confidences):
            state = MATCHED
            confidence = next(c for c in confidences if c in _CLAIMS_MATCH)
        else:
            state = EXCEPTION
            confidence = confidences[0]

        members: set[str] = set()
        for p in props:
            members |= _member_values(p["id"])

        # What was actually released, not what merely looked releasable. A
        # proposal whose confidence is `exact` but which the verifier refused
        # never reached anyone, and counting it as an auto-match would credit
        # the system with a mistake it did not make -- and hide the fact that
        # the gate is what stopped it.
        released = any(
            p["status"] == "accepted" and p["confidence"] in _AUTO_ACCEPTABLE
            for p in props
        )
        verdicts[key] = Verdict(
            work_key=key,
            state=state,
            confidence=confidence,
            auto_acceptable=(state == MATCHED and released),
            proposal_ids=[p["id"] for p in props],
            rules=sorted({p["rule"] for p in props}),
            member_values=members,
            balance_minor=next(
                (p["balance_minor"] for p in props if p["balance_minor"] is not None), None
            ),
        )
    return verdicts


def run(fixture: Fixture) -> RunResult:
    """Ingest, match, verify -- then read back what the system concluded."""
    from app.core import automatch, ingest, verify
    from app.db import connection as db

    with _Sandbox():
        for name, path in fixture.sources:
            ingest.ingest_csv(path, name=name, original_name=path.name)
            log.info("ingested %s", name)

        datasets = db.query(
            "SELECT name, row_count FROM dataset WHERE status = 'ready' ORDER BY created_at"
        )
        am = automatch.auto_match_exact()

        # Everything the deterministic pass produced lands pending, because no
        # rule has been approved. Trusting them here is what a human clicking
        # approve would do, and it is the only way to exercise the release gate
        # -- including the verification that gate runs.
        from app.core import matching

        for rule in {r["rule"] for r in db.query("SELECT rule FROM rule_trust")}:
            try:
                matching.trust_rule(rule, actor="eval", note="eval harness")
            except matching.MatchError:
                continue

        sweep = verify.sweep(status="", limit=5000)

        labelled = {e.work_key for e in fixture.expectations}
        verdicts = _collect_verdicts(labelled)

        # Keys the system matched that carry no label at all: not scoreable,
        # but a large number would mean the fixture no longer describes the
        # data, so it is reported rather than dropped.
        all_keys = {
            str(r["group_key"])
            for r in db.query("SELECT DISTINCT group_key FROM match_proposal")
        }
        matched_unlabelled = all_keys - labelled

        return RunResult(
            fixture=fixture,
            verdicts=verdicts,
            automatch=am,
            verification=sweep,
            datasets=datasets,
            matched_unlabelled=matched_unlabelled,
        )
