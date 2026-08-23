/**
 * Typed contract for the AI SDK UI Message Stream coming off the Python backend.
 *
 * Mirrors `backend/app/streaming/protocol.py` — change one, change the other.
 *
 * Native chunk families (`text-*`, `reasoning-*`, `tool-*`) are handled by the
 * SDK and land in `message.parts`. Everything the SDK has no concept of travels
 * as a custom `data-<name>` part, declared here so `useChat` is fully typed.
 */

import type { UIMessage } from 'ai'

/** Which agent is doing what, right now → the Activity feed. */
export interface ActivityData {
  agent: string
  state: 'started' | 'thinking' | 'calling-tool' | 'waiting' | 'done' | 'failed'
  label: string
  detail?: unknown
}

/** Cost / tokens / time. Sent `transient`, so it reaches `onData` but is
 *  never appended to message history. */
export interface MetricsData {
  promptTokens: number
  completionTokens: number
  cachedTokens: number
  reasoningTokens: number
  totalTokens: number
  costUsd: number
  elapsedMs: number
  model: string | null
  agent: string | null
}

/** Progress of a reconciliation run. Carries a stable id, so the part is
 *  overwritten in place rather than appended. */
export interface RunData {
  runId: string
  stage: string
  pct: number | null
  status: string
}

export interface DatasetData {
  datasetId: string
  name: string
  rows: number
}

export type ReconDataParts = {
  activity: ActivityData
  metrics: MetricsData
  run: RunData
  dataset: DatasetData
}

/** The message type used throughout the app. */
export type ReconUIMessage = UIMessage<never, ReconDataParts>
