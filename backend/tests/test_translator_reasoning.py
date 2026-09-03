"""The reasoning block must survive a model that thinks more than once.

A turn where the model thinks, answers, calls a tool and then thinks again is
ordinary agent behaviour -- it just never appeared until a model that emits
reasoning parts was pointed at it. The AI SDK stream refuses a `reasoning-delta`
whose id has no open `reasoning-start`, so getting this wrong kills the turn in
the browser while the backend reports success.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from app.streaming.translator import translate


def part(text: str = "", *, thought: bool = False, call: object = None,
         response: object = None) -> SimpleNamespace:
    return SimpleNamespace(
        text=text, thought=thought, function_call=call, function_response=response
    )


def event(*parts: SimpleNamespace, partial: bool = True,
          author: str = "reconciler") -> SimpleNamespace:
    return SimpleNamespace(
        author=author,
        partial=partial,
        content=SimpleNamespace(parts=list(parts)),
        usage_metadata=None,
        error_message=None,
        error_code=None,
        id="e",
        model_version="test",
    )


async def collect(events: list[SimpleNamespace]) -> list[dict]:
    async def gen():
        for e in events:
            yield e

    return [chunk async for chunk in translate(gen(), model="test")]


def check_protocol(chunks: list[dict]) -> None:
    """Exactly what the client asserts: no delta outside an open part."""
    open_ids: set[str] = set()
    ended: set[str] = set()
    for c in chunks:
        kind, cid = c.get("type"), c.get("id")
        if kind == "reasoning-start":
            assert cid not in open_ids, f"reasoning-start twice for {cid}"
            assert cid not in ended, f"reasoning-start reused an ended id {cid}"
            open_ids.add(cid)
        elif kind == "reasoning-delta":
            assert cid in open_ids, (
                f"reasoning-delta for missing reasoning part with ID {cid!r}"
            )
        elif kind == "reasoning-end":
            assert cid in open_ids, f"reasoning-end for unopened {cid}"
            open_ids.discard(cid)
            ended.add(cid)
    assert not open_ids, f"reasoning parts left open: {open_ids}"


def test_thinks_again_after_speaking() -> None:
    chunks = asyncio.run(collect([
        event(part("weighing the join", thought=True)),
        event(part("Auto-reconciliation ran two rules.")),
        event(part(call=SimpleNamespace(id="c1", name="get_exceptions", args={}))),
        event(part(response=SimpleNamespace(id="c1", response={"ok": True}))),
        # The second thought is what used to be addressed to a dead id.
        event(part("now the exceptions", thought=True)),
        event(part("Sixteen groups do not tie.")),
    ]))
    check_protocol(chunks)

    starts = [c["id"] for c in chunks if c["type"] == "reasoning-start"]
    assert len(starts) == 2, f"expected two reasoning parts, got {starts}"
    assert starts[0] != starts[1], "second thought reused the first part's id"


def test_single_thought_still_closes() -> None:
    chunks = asyncio.run(collect([
        event(part("just the once", thought=True)),
        event(part("Done.")),
    ]))
    check_protocol(chunks)
    assert sum(c["type"] == "reasoning-start" for c in chunks) == 1


def test_thought_open_at_end_is_closed() -> None:
    """No prose ever arrives -- the finally block still has to close it."""
    chunks = asyncio.run(collect([event(part("thinking to the end", thought=True))]))
    check_protocol(chunks)


def test_non_streaming_model_emits_a_whole_block() -> None:
    """An aggregated reply must still be start/delta/end, not a bare delta."""
    chunks = asyncio.run(collect([
        event(part("all at once", thought=True), partial=False),
        event(part("The answer."), partial=False),
    ]))
    check_protocol(chunks)
    assert sum(c["type"] == "reasoning-start" for c in chunks) == 1


if __name__ == "__main__":
    # No test runner is installed, so the module runs itself. The function
    # names still follow the pytest convention, so it works under one too.
    failures = 0
    for _name, _fn in sorted(globals().items()):
        if not _name.startswith("test_") or not callable(_fn):
            continue
        try:
            _fn()
            print(f"  ok   {_name}")
        except AssertionError as exc:
            failures += 1
            print(f"  FAIL {_name}: {exc}")
    raise SystemExit(failures)
