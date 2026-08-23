/**
 * Chat against the orchestrator.
 *
 * Renders the native part families the backend emits — prose, reasoning and
 * tool calls — which is enough to prove the stream protocol end to end. The
 * dedicated Activity and Metrics surfaces are separate work; the `data-*`
 * parts that feed them are already typed in `types/stream.ts`.
 */

import { useState } from 'react'
import { useChat } from '@ai-sdk/react'
import { DefaultChatTransport, getToolName, isToolUIPart } from 'ai'
import type { ReconUIMessage } from '@/types/stream'

export default function ChatPanel() {
  const [input, setInput] = useState('')
  const { messages, sendMessage, status, error, stop } = useChat<ReconUIMessage>({
    transport: new DefaultChatTransport({ api: '/api/chat' }),
  })

  const busy = status === 'submitted' || status === 'streaming'

  function submit(e: React.FormEvent) {
    e.preventDefault()
    const text = input.trim()
    if (!text || busy) return
    setInput('')
    void sendMessage({ text })
  }

  return (
    <div className="flex h-full flex-col">
      <div className="flex-1 space-y-4 overflow-y-auto p-6">
        {messages.length === 0 && (
          <p className="text-sm text-[--color-muted]">
            No agent is connected yet. Send anything — the backend replies with a scripted
            stream that exercises reasoning, tool-call and metrics chunks.
          </p>
        )}

        {messages.map((m) => (
          <div key={m.id} className="space-y-2">
            <div className="text-xs uppercase tracking-wider text-[--color-muted]">
              {m.role}
            </div>

            {m.parts.map((part, i) => {
              if (part.type === 'text') {
                return (
                  <p key={i} className="whitespace-pre-wrap leading-relaxed">
                    {part.text}
                  </p>
                )
              }

              if (part.type === 'reasoning') {
                return (
                  <pre
                    key={i}
                    className="whitespace-pre-wrap rounded border border-[--color-edge] bg-[--color-panel] p-3 font-mono text-xs text-[--color-muted]"
                  >
                    {part.text}
                  </pre>
                )
              }

              if (isToolUIPart(part)) {
                return (
                  <div
                    key={i}
                    className="rounded border border-[--color-edge] bg-[--color-panel] p-3 font-mono text-xs"
                  >
                    <div className="text-[--color-accent]">
                      {getToolName(part)} · {part.state}
                    </div>
                    {'input' in part && part.input != null && (
                      <div className="mt-1 text-[--color-muted]">
                        in {JSON.stringify(part.input)}
                      </div>
                    )}
                    {'output' in part && part.output != null && (
                      <div className="mt-1 text-[--color-muted]">
                        out {JSON.stringify(part.output)}
                      </div>
                    )}
                  </div>
                )
              }

              return null
            })}
          </div>
        ))}

        {error && (
          <p className="rounded border border-red-900 bg-red-950/40 p-3 text-sm text-red-300">
            {error.message}
          </p>
        )}
      </div>

      <form onSubmit={submit} className="flex gap-2 border-t border-[--color-edge] p-4">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Ask the orchestrator…"
          className="flex-1 rounded border border-[--color-edge] bg-[--color-panel] px-3 py-2 text-sm outline-none focus:border-[--color-accent]"
        />
        <button
          type={busy ? 'button' : 'submit'}
          onClick={busy ? stop : undefined}
          className="rounded border border-[--color-edge] bg-[--color-panel] px-4 py-2 text-sm hover:border-[--color-accent]"
        >
          {busy ? 'Stop' : 'Send'}
        </button>
      </form>
    </div>
  )
}
