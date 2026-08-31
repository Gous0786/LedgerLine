"""`python -m app.eval` -- score the deterministic pipeline against a fixture.

    uv run python -m app.eval --fixture ../../reconriver/sample-100-v2
    uv run python -m app.eval --fixture <dir> --json > eval.json
    uv run python -m app.eval --fixture <dir> --max-false-auto-match 0.0

The exit code is the point of the last form: a threshold turns this from a
report into a gate, so a change that starts inventing matches fails rather than
being noticed later.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from app.eval import fixture as fixture_mod
from app.eval import runner
from app.eval import score as score_mod
from app.eval.fixture import EXCEPTION, MATCHED, MISSING

STATES = (MATCHED, EXCEPTION, MISSING)


def _pct(value: float | None) -> str:
    return "  n/a " if value is None else f"{value * 100:6.2f}%"


def _report(result: runner.RunResult, scores: dict[str, score_mod.Scores]) -> None:
    f = result.fixture
    print(f"\nFIXTURE  {f.name}   ({f.path})")
    print("  sources : " + ", ".join(
        f"{d['name']}={d['row_count']}" for d in result.datasets
    ))
    scopes = sorted({e.scope for e in f.expectations})
    breakdown = ", ".join(f"{s}={len(f.by_scope(s))}" for s in scopes)
    print(f"  labels  : {len(f.expectations)}   ({breakdown})")
    if f.unlabelled_orders:
        print(f"  note    : {len(f.unlabelled_orders)} source orders carry no label")

    am = result.automatch
    print(f"\nAUTOMATCH  {am.get('rules_run', 0)} rules,"
          f" {am.get('groups_proposed', 0)} groups")
    for r in am.get("results", []):
        if "error" in r:
            print(f"  ! {r['rule']}: {r['error']}")
            continue
        print(f"  {r.get('shape','?'):<4} {r.get('strategy','?'):<12}"
              f" {r.get('proposed',0):>4} groups   {r.get('join','')}")
        if r.get("amounts"):
            print(f"       {r['amounts']}  (agreement {r.get('agreement')})")
    for d in am.get("declined", []):
        print(f"  DECLINED {d.get('shape','?')}  {d.get('join','')}")
        print(f"       {d.get('reason','')}")

    v = result.verification
    print(f"\nVERIFIER   {v.get('passed', 0)}/{v.get('verified', 0)} passed,"
          f" {v.get('failed', 0)} failed")

    for name in ("ALL", *[k for k in scores if k != "ALL"]):
        s = scores[name]
        print(f"\n{'=' * 62}\nSCOPE {name}   ({s.total} labelled)")
        print(f"  accuracy  {_pct(s.accuracy)}    "
              f"precision {_pct(s.precision)}  recall {_pct(s.recall)}  f1 {_pct(s.f1)}")
        print(f"  FALSE AUTO-MATCH RATE  {_pct(s.false_auto_match_rate)}"
              f"   ({s.false_auto_matches} of {s.auto_accepted} auto-acceptable)")
        if s.member_checked:
            print(f"  right rows in the group  {s.member_exact}/{s.member_checked}")

        print(f"\n  {'expected \\ predicted':<22}" + "".join(f"{p:>11}" for p in STATES))
        for actual in STATES:
            row = s.confusion[actual]
            print(f"  {actual:<22}" + "".join(f"{row[p]:>11}" for p in STATES))

        wrong = {k: v for k, v in s.by_outcome.items() if v["correct"] < v["n"]}
        if wrong:
            print("\n  outcomes not fully recovered:")
            for outcome, c in sorted(wrong.items(), key=lambda kv: kv[1]["correct"] - kv[1]["n"]):
                print(f"    {outcome:<26} {c['correct']:>3}/{c['n']}")

    worst = scores["ALL"]
    if worst.examples:
        print(f"\n{'=' * 62}\nEXAMPLES")
        for e in worst.examples[:10]:
            flag = "!!" if e["kind"] == "false auto-match" else "  "
            print(f"  {flag} {e['work_key']:<26} expected {e['expected']:<22}"
                  f" got {e['predicted']:<10} [{e.get('confidence')}]")

    if result.matched_unlabelled:
        print(f"\n  {len(result.matched_unlabelled)} matched keys carry no label"
              " (not scored)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.eval")
    parser.add_argument("--fixture", required=True, type=Path,
                        help="directory holding the CSVs and expected_reconciliation.csv")
    parser.add_argument("--json", action="store_true", help="emit JSON only")
    parser.add_argument("--max-false-auto-match", type=float, default=None,
                        help="fail (exit 1) if the false auto-match rate exceeds this")
    parser.add_argument("--min-recall", type=float, default=None,
                        help="fail (exit 1) if MATCHED recall falls below this")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)-7s %(name)s: %(message)s",
    )

    try:
        fx = fixture_mod.load(args.fixture)
    except (FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    result = runner.run(fx)
    scores = score_mod.score_all(result)

    if args.json:
        print(json.dumps(score_mod.as_dict(result, scores), indent=2, default=str))
    else:
        _report(result, scores)

    overall = scores["ALL"]
    failed = False
    if args.max_false_auto_match is not None:
        rate = overall.false_auto_match_rate or 0.0
        if rate > args.max_false_auto_match:
            print(f"\nFAIL false auto-match rate {rate:.4f}"
                  f" exceeds {args.max_false_auto_match}", file=sys.stderr)
            failed = True
    if args.min_recall is not None:
        rec = overall.recall or 0.0
        if rec < args.min_recall:
            print(f"\nFAIL recall {rec:.4f} below {args.min_recall}", file=sys.stderr)
            failed = True

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
