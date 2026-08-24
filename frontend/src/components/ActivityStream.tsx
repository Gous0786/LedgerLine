/**
 * The agent's work, rendered as it happens.
 *
 * Modelled on how a coding agent narrates itself: one line per operation, tool
 * calls collapsed to a signature with their result underneath, and the rows a
 * query returned shown inline rather than buried. Reasoning is dimmed and
 * secondary; prose is primary.
 */

import { useEffect, useRef, useState } from 'react'
import { getToolName, isToolUIPart } from 'ai'
import type { ActivityData, ReconUIMessage } from '@/types/stream'
import { useChatState } from '@/state/ChatContext'

type AnyPart = ReconUIMessage['parts'][number]

const STATE_TONE: Record<ActivityData['state'], string> = {
  started: 'text-accent',
  thinking: 'text-violet',
  'calling-tool': 'text-cyan',
  waiting: 'text-warn',
  done: 'text-ok',
  failed: 'text-bad',
}

function Dot({ className = '' }: { className?: string }) {
  return <span className={'mt-[7px] size-1.5 shrink-0 rounded-full ' + className} />
}

/** Renders a tool result as a table when it looks like rows, else as JSON. */
function ToolOutput({ output }: { output: unknown }) {
  const rows = Array.isArray(output)
    ? output
    : output && typeof output === 'object' && Array.isArray((output as { rows?: unknown }).rows)
      ? ((output as { rows: unknown[] }).rows)
      : null

  if (rows && rows.length > 0 && typeof rows[0] === 'object' && rows[0] !== null) {
    const cols = Object.keys(rows[0] as object).slice(0, 8)
    return (
      <div className="mt-1.5 overflow-x-auto rounded border border-line/60">
        <table className="w-full border-collapse font-mono text-[11px]">
          <thead>
            <tr>
              {cols.map((c) => (
                <th
                  key={c}
                  className="border-b border-line/60 px-2 py-1 text-left font-normal text-faint"
                >
                  {c}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.slice(0, 8).map((r, i) => (
              <tr key={i}>
                {cols.map((c) => (
                  <td key={c} className="border-b border-line/40 px-2 py-1 whitespace-nowrap">
                    {String((r as Record<string, unknown>)[c] ?? '')}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
        {rows.length > 8 && (
          <div className="px-2 py-1 font-mono text-[11px] text-faint">
            +{rows.length - 8} more rows
          </div>
        )}
      </div>
    )
  }

  return (
    <pre className="mt-1.5 max-h-56 overflow-auto rounded border border-line/60 bg-base/40 p-2 font-mono text-[11px] whitespace-pre-wrap text-muted">
      {JSON.stringify(output, null, 2)}
    </pre>
  )
}

function ToolEntry({ part }: { part: AnyPart }) {
  const [open, setOpen] = useState(false)
  if (!isToolUIPart(part)) return null

  const name = getToolName(part)
  const input = 'input' in part ? part.input : undefined
  const output = 'output' in part ? part.output : undefined
  const errorText = 'errorText' in part ? (part.errorText as string | undefined) : undefined
  const running = part.state === 'input-streaming' || part.state === 'input-available'

  const signature =
    input && typeof input === 'object'
      ? Object.entries(input as Record<string, unknown>)
          .map(([k, v]) => `${k}: ${JSON.stringify(v)}`)
          .join(', ')
      : String(input ?? '')

  return (
    <div className="flex gap-2.5">
      <Dot
        className={
          errorText ? 'bg-bad' : running ? 'animate-pulse bg-cyan' : 'bg-ok'
        }
      />
      <div className="min-w-0 flex-1">
        <button
          onClick={() => setOpen((v) => !v)}
          className="group flex w-full items-baseline gap-2 text-left"
        >
          <span className="font-mono text-[13px] text-cyan">{name}</span>
          <span className="truncate font-mono text-[11px] text-faint group-hover:text-muted">
            {signature}
          </span>
          <span className="ml-auto shrink-0 font-mono text-[10px] text-faint">
            {open ? '−' : '+'}
          </span>
        </button>

        {errorText && <div className="mt-1 font-mono text-[11px] text-bad">{errorText}</div>}

        {open && output !== undefined && <ToolOutput output={output} />}
        {open && output === undefined && !errorText && (
          <div className="mt-1 font-mono text-[11px] text-faint">running…</div>
        )}
      </div>
    </div>
  )
}

function PartEntry({ part }: { part: AnyPart }) {
  if (part.type === 'text') {
    return (
      <div className="flex gap-2.5">
        <Dot className="bg-accent" />
        <p className="min-w-0 flex-1 text-[13px] leading-relaxed whitespace-pre-wrap">
          {part.text}
        </p>
      </div>
    )
  }

  if (part.type === 'reasoning') {
    return (
      <div className="flex gap-2.5">
        <Dot className="bg-violet/60" />
        <p className="min-w-0 flex-1 text-[12px] leading-relaxed whitespace-pre-wrap text-faint italic">
          {part.text}
        </p>
      </div>
    )
  }

  if (part.type === 'data-activity') {
    const d = part.data as ActivityData
    return (
      <div className="flex gap-2.5">
        <Dot className="bg-muted/50" />
        <div className="flex min-w-0 flex-1 items-baseline gap-2">
          <span className="font-mono text-[11px] text-muted">{d.agent}</span>
          <span className={'font-mono text-[11px] ' + (STATE_TONE[d.state] ?? 'text-muted')}>
            {d.state}
          </span>
          <span className="truncate text-[12px] text-faint">{d.label}</span>
        </div>
      </div>
    )
  }

  if (isToolUIPart(part)) return <ToolEntry part={part} />

  return null
}

export default function ActivityStream() {
  const { messages, busy, error } = useChatState()
  const endRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [messages, busy])

  if (messages.length === 0) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-2 px-8 text-center">
        <div className="eyebrow">Agent workspace</div>
        <p className="max-w-sm text-[13px] text-faint">
          Tool calls, the rows they return, and the agent&apos;s reasoning appear here as it
          works. Nothing is running yet.
        </p>
      </div>
    )
  }

  return (
    <div className="h-full overflow-y-auto px-5 py-4">
      <div className="space-y-4">
        {messages.map((m) => (
          <div key={m.id} className="space-y-2">
            {m.role === 'user' ? (
              <div className="flex justify-end">
                <div className="glass max-w-[80%] rounded-lg px-3 py-2 text-[13px] whitespace-pre-wrap">
                  {m.parts
                    .filter((p) => p.type === 'text')
                    .map((p) => (p as { text: string }).text)
                    .join('')}
                </div>
              </div>
            ) : (
              <div className="space-y-2.5">
                {m.parts.map((part, i) => (
                  <PartEntry key={i} part={part} />
                ))}
              </div>
            )}
          </div>
        ))}

        {busy && (
          <div className="flex gap-2.5">
            <Dot className="animate-pulse bg-accent" />
            <span className="font-mono text-[12px] text-faint">working…</span>
          </div>
        )}

        {error && (
          <div className="rounded border border-bad/40 bg-bad/10 px-3 py-2 text-[12px] text-bad">
            {error.message}
          </div>
        )}

        <div ref={endRef} />
      </div>
    </div>
  )
}
