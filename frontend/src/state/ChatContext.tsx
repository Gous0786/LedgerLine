/**
 * One chat stream, shared by three surfaces.
 *
 * The input lives at the bottom, the agent's work renders in the middle, and
 * the cost/token meter sits on the right -- all reading the same `useChat`.
 * Lifting it here keeps them in sync; each owning its own hook would open
 * three separate streams.
 */

import { createContext, useCallback, useContext, useMemo, useState } from 'react'
import { useChat } from '@ai-sdk/react'
import { DefaultChatTransport } from 'ai'
import type { ChatStatus } from 'ai'
import type { MetricsData, ReconUIMessage } from '@/types/stream'

export interface MetricTotals {
  calls: number
  promptTokens: number
  completionTokens: number
  cachedTokens: number
  totalTokens: number
  costUsd: number
  elapsedMs: number
  lastModel: string | null
}

const ZERO: MetricTotals = {
  calls: 0,
  promptTokens: 0,
  completionTokens: 0,
  cachedTokens: 0,
  totalTokens: 0,
  costUsd: 0,
  elapsedMs: 0,
  lastModel: null,
}

interface ChatContextValue {
  messages: ReconUIMessage[]
  status: ChatStatus
  error: Error | undefined
  busy: boolean
  send: (text: string) => void
  stop: () => void
  metrics: MetricTotals
  resetMetrics: () => void
}

const Ctx = createContext<ChatContextValue | null>(null)

export function ChatProvider({ children }: { children: React.ReactNode }) {
  const [metrics, setMetrics] = useState<MetricTotals>(ZERO)

  const { messages, sendMessage, status, error, stop } = useChat<ReconUIMessage>({
    transport: new DefaultChatTransport({ api: '/api/chat' }),
    onData: (part) => {
      // Metrics ride in as transient parts: they reach onData but never enter
      // message history, so this is the only place to catch them.
      if (part.type === 'data-metrics') {
        const d = part.data as MetricsData
        setMetrics((m) => ({
          calls: m.calls + 1,
          promptTokens: m.promptTokens + (d.promptTokens ?? 0),
          completionTokens: m.completionTokens + (d.completionTokens ?? 0),
          cachedTokens: m.cachedTokens + (d.cachedTokens ?? 0),
          totalTokens: m.totalTokens + (d.totalTokens ?? 0),
          costUsd: m.costUsd + (d.costUsd ?? 0),
          elapsedMs: m.elapsedMs + (d.elapsedMs ?? 0),
          lastModel: d.model ?? m.lastModel,
        }))
      }
    },
  })

  const busy = status === 'submitted' || status === 'streaming'

  const send = useCallback(
    (text: string) => {
      const trimmed = text.trim()
      if (trimmed) void sendMessage({ text: trimmed })
    },
    [sendMessage],
  )

  const resetMetrics = useCallback(() => setMetrics(ZERO), [])

  const value = useMemo<ChatContextValue>(
    () => ({ messages, status, error, busy, send, stop, metrics, resetMetrics }),
    [messages, status, error, busy, send, stop, metrics, resetMetrics],
  )

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export function useChatState(): ChatContextValue {
  const ctx = useContext(Ctx)
  if (!ctx) throw new Error('useChatState must be used inside <ChatProvider>')
  return ctx
}
