"""ADK runner host.

The agent runs inside the FastAPI process, so the Runner and its session
service are process-level singletons.

Conversation history lives in the ADK session, keyed by the chat id the
frontend sends. `useChat` posts its full message list every turn, but replaying
that into ADK would duplicate everything the session already holds -- so only
the newest user message is forwarded.

Sessions are in-memory: a backend restart drops history while the browser still
shows it. Swap in DatabaseSessionService against the existing SQLite file when
that starts to matter.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from functools import lru_cache
from typing import Any

from google.adk.agents.run_config import RunConfig, StreamingMode
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from app.agents.root_agent import build_root_agent
from app.config import get_settings
from app.core import runlog

log = logging.getLogger(__name__)

APP_NAME = "recon"
USER_ID = "local"  # single-user local app

# One model call per tool round trip, so this is the ceiling on how long the
# agent may keep going before it has to answer. ADK's default is 500, which for
# a system this cost-conscious is not a backstop but an invitation: a loop the
# prompt failed to prevent would spend a hundred times the cost of a normal
# turn before anything stopped it. A worked reconciliation is 5-15 calls.
MAX_LLM_CALLS = 40


@lru_cache
def _session_service() -> InMemorySessionService:
    return InMemorySessionService()


@lru_cache
def get_runner() -> Runner:
    return Runner(
        app_name=APP_NAME,
        agent=build_root_agent(),
        session_service=_session_service(),
    )


async def ensure_session(session_id: str) -> None:
    service = _session_service()
    existing = await service.get_session(
        app_name=APP_NAME, user_id=USER_ID, session_id=session_id
    )
    if existing is None:
        await service.create_session(
            app_name=APP_NAME, user_id=USER_ID, session_id=session_id
        )
        log.info("created session %s", session_id)


async def run(session_id: str, text: str) -> AsyncIterator[Any]:
    """Stream ADK events for one user turn.

    A turn is also a *run*: it opens a `run` row and puts its id in a ContextVar
    that the callbacks, the translator and `propose_matches` all read, so
    everything the turn produces is attributable to it. Async generators share
    the consuming task's context, which is why setting it here reaches all
    three.
    """
    await ensure_session(session_id)
    runner = get_runner()

    run_id = runlog.start(title=text, session_id=session_id)
    runlog.event("user-message", {"text": text})
    status, error = "done", None
    try:
        async for event in runner.run_async(
            user_id=USER_ID,
            session_id=session_id,
            new_message=types.Content(role="user", parts=[types.Part(text=text)]),
            run_config=RunConfig(
                streaming_mode=StreamingMode.SSE, max_llm_calls=MAX_LLM_CALLS
            ),
        ):
            yield event
    except Exception as exc:
        status, error = "failed", f"{type(exc).__name__}: {exc}"
        raise
    except BaseException:
        # The client went away mid-stream, or the task was cancelled. Recorded
        # as what it was rather than silently as success.
        status = "cancelled"
        raise
    finally:
        runlog.finish(run_id, status, error)


def active_model() -> str:
    return get_settings().model_orchestrator
