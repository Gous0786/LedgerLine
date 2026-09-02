"""Score the *agent* against a fixture, not just the deterministic pass.

The deterministic harness measures `automatch` + the match engine + the
verifier. That is the reproducible half, and it is worth measuring on its own --
but it is not what the application does when somebody types "reconcile it", and
for a while the two disagreed by eleven points without anything noticing. Three
defects lived in that gap: callbacks with the wrong signature that killed every
turn, a verifier that only ran at release so a pending queue carried no
findings, and a population statistic computed against a population of one.

None were reachable from the deterministic path. So the agent path is a first
class thing to score, with the caveat that it costs money and does not repeat
exactly -- the same prompt on the same data has taken 12, 16 and 23 model calls.
Treat its number as a sample, and the deterministic score as the regression gate.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field

from app.eval.fixture import Fixture
from app.eval.runner import RunResult, _collect_verdicts, _Sandbox

log = logging.getLogger(__name__)

DEFAULT_PROMPT = "reconcile it"


@dataclass
class AgentTelemetry:
    prompt: str = ""
    wall_seconds: float = 0.0
    model_calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cached_tokens: int = 0
    cost_usd: float = 0.0
    tool_calls: list[str] = field(default_factory=list)
    tool_result_chars: int = 0
    tool_sent_chars: int = 0
    errors: list[str] = field(default_factory=list)
    answer: str = ""
    run_id: str | None = None
    per_call_prompt_tokens: list[int] = field(default_factory=list)
    budget_refusals: int = 0

    @property
    def failed(self) -> bool:
        """The turn never reached the model.

        Worth its own flag because the failure mode is silent and looks exactly
        like incompetence: a turn that dies before the first call leaves an
        empty database, and scoring that produces a confident 6.6% accuracy for
        a system that was never asked anything. A provider timeout must not be
        reportable as a quality regression.
        """
        return self.model_calls == 0


async def _drive(prompt: str, telemetry: AgentTelemetry) -> None:
    """One turn, through the same pair `api/chat.py` wires together."""
    from app.agents import runner as agent_runner
    from app.streaming.translator import translate

    text: list[str] = []
    events = agent_runner.run("eval-session", prompt)
    async for chunk in translate(events, model=agent_runner.active_model()):
        kind = chunk.get("type", "")
        if kind == "tool-input-available":
            telemetry.tool_calls.append(str(chunk.get("toolName", "?")))
        elif kind == "text-delta":
            text.append(str(chunk.get("delta", "")))
        elif kind == "error":
            telemetry.errors.append(str(chunk.get("errorText", "")))
    telemetry.answer = "".join(text).strip()


def _read_telemetry(telemetry: AgentTelemetry) -> None:
    """Everything the callbacks and the run log persisted for this turn."""
    from app.db import connection as db

    run = db.query_one("SELECT id FROM run ORDER BY started_at DESC, rowid DESC LIMIT 1")
    if not run:
        return
    telemetry.run_id = run["id"]

    rows = db.query(
        "SELECT prompt_tokens, completion_tokens, cached_tokens, cost_usd"
        " FROM run_metric WHERE run_id = ? ORDER BY id",
        (run["id"],),
    )
    telemetry.model_calls = len(rows)
    telemetry.per_call_prompt_tokens = [r["prompt_tokens"] or 0 for r in rows]
    telemetry.prompt_tokens = sum(r["prompt_tokens"] or 0 for r in rows)
    telemetry.completion_tokens = sum(r["completion_tokens"] or 0 for r in rows)
    telemetry.cached_tokens = sum(r["cached_tokens"] or 0 for r in rows)
    telemetry.cost_usd = sum(r["cost_usd"] or 0.0 for r in rows)

    sizes = db.query(
        "SELECT json_extract(payload_json, '$.result_chars') AS produced,"
        "       json_extract(payload_json, '$.returned_chars') AS sent"
        " FROM run_event WHERE run_id = ? AND kind = 'tool-output-available'",
        (run["id"],),
    )
    telemetry.tool_result_chars = sum(r["produced"] or 0 for r in sizes)
    telemetry.tool_sent_chars = sum(r["sent"] or 0 for r in sizes)

    refused = db.query_one(
        "SELECT COUNT(*) n FROM run_event"
        " WHERE run_id = ? AND kind = 'tool-budget-exceeded'",
        (run["id"],),
    )
    telemetry.budget_refusals = (refused or {}).get("n", 0) or 0


def run(fixture: Fixture, prompt: str = DEFAULT_PROMPT) -> RunResult:
    """Ingest the fixture, drive one agent turn, score what it produced."""
    from app.config import get_settings
    from app.core import ingest
    from app.db import connection as db

    if not get_settings().openrouter_api_key:
        raise RuntimeError(
            "agent mode needs OPENROUTER_API_KEY; the deterministic harness"
            " (without --agent) needs no credentials"
        )

    telemetry = AgentTelemetry(prompt=prompt)
    with _Sandbox():
        for name, path in fixture.sources:
            ingest.ingest_csv(path, name=name, original_name=path.name)

        datasets = db.query(
            "SELECT name, row_count FROM dataset WHERE status = 'ready' ORDER BY created_at"
        )

        started = time.perf_counter()
        asyncio.run(_drive(prompt, telemetry))
        telemetry.wall_seconds = time.perf_counter() - started
        _read_telemetry(telemetry)

        labelled = {e.work_key for e in fixture.expectations}
        verdicts = _collect_verdicts(labelled)
        all_keys = {
            str(r["group_key"])
            for r in db.query("SELECT DISTINCT group_key FROM match_proposal")
        }
        sweep = db.query_one(
            "SELECT COUNT(*) AS verified, SUM(status = 'pass') AS passed"
            " FROM verification"
        ) or {}

        return RunResult(
            fixture=fixture,
            verdicts=verdicts,
            automatch={"agent": True, "tool_calls": telemetry.tool_calls},
            verification={
                "verified": sweep.get("verified", 0),
                "passed": sweep.get("passed", 0),
                "failed": (sweep.get("verified", 0) or 0) - (sweep.get("passed", 0) or 0),
            },
            datasets=datasets,
            matched_unlabelled=all_keys - labelled,
            agent=telemetry,
        )


def report(telemetry: AgentTelemetry) -> None:
    if telemetry.failed:
        print(f"\n{'=' * 62}\nAGENT TURN FAILED   {telemetry.prompt!r}")
        print(f"  wall clock     {telemetry.wall_seconds:.1f}s")
        print("  model calls    0 -- the turn never reached the model, so the"
              " scores above are meaningless")
        for err in telemetry.errors or ["no error was reported"]:
            print(f"  error          {err}")
        return

    print(f"\n{'=' * 62}\nAGENT TURN   {telemetry.prompt!r}")
    print(f"  wall clock     {telemetry.wall_seconds:.1f}s"
          f"   run {telemetry.run_id}")
    print(f"  model calls    {telemetry.model_calls}")
    print(f"  prompt tokens  {telemetry.prompt_tokens:,}"
          f"   ({telemetry.cached_tokens:,} cached,"
          f" {telemetry.prompt_tokens - telemetry.cached_tokens:,} billed fresh)")
    print(f"  output tokens  {telemetry.completion_tokens:,}")
    print(f"  cost           ${telemetry.cost_usd:.4f}")
    print(f"  tool calls     {len(telemetry.tool_calls)}")
    counts: dict[str, int] = {}
    for name in telemetry.tool_calls:
        counts[name] = counts.get(name, 0) + 1
    for name, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"      {n:>3}x  {name}")
    if telemetry.budget_refusals:
        print(f"  budget refusals {telemetry.budget_refusals}"
              f"  (calls the guard blocked -- each still cost a round trip)")
    print(f"  tool bytes     {telemetry.tool_result_chars:,} produced,"
          f" {telemetry.tool_sent_chars:,} sent to the model")
    if telemetry.per_call_prompt_tokens:
        curve = telemetry.per_call_prompt_tokens
        print(f"  prompt growth  {curve[0]:,} -> {curve[-1]:,} tokens per call")
    if telemetry.errors:
        print(f"  errors         {telemetry.errors}")
