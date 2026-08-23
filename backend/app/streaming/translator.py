"""ADK `Event` -> AI SDK UI Message Stream chunks.

NOT WIRED UP YET -- this file records the mapping so the seam exists before the
agent does. Implement alongside the first real ADK run.

    ADK event                            UI Message Stream chunk
    -----------------------------------  ---------------------------------------
    content.parts[].text (partial)       text-start / text-delta / text-end
    content.parts[].thought              reasoning-start / reasoning-delta / -end
    content.parts[].function_call        tool-input-start -> tool-input-available
    content.parts[].function_response    tool-output-available | tool-output-error
    author changes / transfer_to_agent   data-activity
    usage_metadata (+ litellm cost)      data-metrics  (transient)
    escalation / error_code              error

Rules worth keeping:

*   One id per logical block. ADK streams partial events for the same block, so
    ids must be stable across deltas -- deriving them from
    ``f"{event.invocation_id}:{event.author}:{part_index}"`` works.
*   ADK marks a final aggregated event after the partials. Emitting its text
    again duplicates the message; only stream ``event.partial`` text, then close
    the block on the final event.
*   Cost is not in ADK's usage metadata. Compute it from token counts with
    ``litellm.completion_cost`` and attach it as a data-metrics chunk.
*   Persist every chunk to `run_event` before yielding it, so a reconnecting
    client can replay from its `seq` cursor.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any


async def translate(events: AsyncIterator[Any]) -> AsyncIterator[dict[str, Any]]:
    raise NotImplementedError("implemented with the first ADK run (phase 3)")
    yield  # pragma: no cover - marks this as a generator
