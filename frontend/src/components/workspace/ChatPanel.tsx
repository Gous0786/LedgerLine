/**
 * The middle column: the agent's turn, rendered as it arrives.
 *
 * The interface *is* the output, so a tool call is a card with a result in it,
 * not a line of prose claiming a tool was called. Everything secondary --
 * reasoning, raw tool payloads -- is collapsed by default and one click away,
 * because the useful reading of a reconciliation is the conclusion, and the
 * evidence only matters when you doubt it.
 */

import { useEffect, useRef, useState } from 'react'
import { getToolName, isToolUIPart } from 'ai'
import Markdown from '@/components/Markdown'
import ReconResult from '@/components/workspace/ReconResult'
import { Dots, Icon, Spinner } from '@/components/ui'
import { useChatState } from '@/state/ChatContext'
import type { ActivityData, ReconUIMessage } from '@/types/stream'

type AnyPart = ReconUIMessage['parts'][number]

/** What `isToolUIPart` narrows to -- includes the dynamic-tool variant, which
 *  a tool-name-only union would miss. */
type ToolPart = Extract<AnyPart, { type: `tool-${string}` } | { type: 'dynamic-tool' }>

/** What each tool is doing, in words a person would use. */
const TOOL_LABEL: Record<string, string> = {
  run_reconciliation: 'Reconciling',
  get_exceptions: 'Collecting exceptions',
  get_transaction_chain: 'Tracing a transaction',
  query_data: 'Querying',
  describe_dataset: 'Profiling columns',
  list_datasets: 'Reading sources',
}

function summarise(name: string, input: unknown): string {
  if (!input || typeof input !== 'object') return ''
  const o = input as Record<string, unknown>
  if (name === 'run_reconciliation') {
    const cfg = (o.config ?? {}) as Record<string, unknown>
    return cfg.mode === 'rule' ? String(cfg.rule ?? 'custom rule') : 'automatic pass'
  }
  if (name === 'query_data') return String(o.sql ?? '').replace(/\s+/g, ' ').slice(0, 90)
  if (name === 'get_transaction_chain') return String(o.transaction_id ?? '')
  if (name === 'describe_dataset') return String(o.dataset ?? '')
  if (name === 'get_exceptions') {
    const f = (o.filters ?? {}) as Record<string, unknown>
    return f.kind ? String(f.kind) : 'everything'
  }
  return ''
}

/** Rows come back as a table; anything else as folded JSON. */
function ToolOutput({ output }: { output: unknown }) {
  const rows =
    output && typeof output === 'object' && Array.isArray((output as { rows?: unknown }).rows)
      ? (output as { rows: Record<string, unknown>[] }).rows
      : Array.isArray(output)
        ? (output as Record<string, unknown>[])
        : null

  if (rows && rows.length > 0 && typeof rows[0] === 'object' && rows[0] !== null) {
    const cols = Object.keys(rows[0]).slice(0, 7)
    return (
      <div className="mt-2 overflow-x-auto rounded-lg border border-line">
        <table className="w-full border-collapse text-left font-mono text-[11px]">
          <thead>
            <tr className="bg-sunk/70">
              {cols.map((c) => (
                <th key={c} className="px-2.5 py-1.5 font-medium text-muted whitespace-nowrap">
                  {c}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.slice(0, 8).map((r, i) => (
              <tr key={i} className="border-t border-line">
                {cols.map((c) => (
                  <td key={c} className="px-2.5 py-1.5 whitespace-nowrap text-ink">
                    {String(r[c] ?? '')}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    )
  }

  return (
    <pre className="mt-2 max-h-64 overflow-auto rounded-lg border border-line bg-sunk/50 p-3 font-mono text-[11px] leading-relaxed whitespace-pre-wrap text-muted">
      {JSON.stringify(output, null, 2)}
    </pre>
  )
}

function ToolCard({ part }: { part: ToolPart }) {
  const [open, setOpen] = useState(false)
  const name = getToolName(part)
  const { state } = part
  const input = 'input' in part ? part.input : undefined
  const output = 'output' in part ? part.output : undefined
  const errorText = 'errorText' in part ? (part.errorText as string | undefined) : undefined
  const running = state !== 'output-available' && state !== 'output-error'
  const detail = summarise(name, input)

  return (
    <div className="rise panel-flat overflow-hidden rounded-xl">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-2.5 px-3.5 py-2.5 text-left"
      >
        <span className={running ? 'text-accent' : errorText ? 'text-bad' : 'text-accent/70'}>
          {running ? <Spinner size={13} /> : errorText ? <Icon.alert size={13} /> : <Icon.check size={13} />}
        </span>
        <span className="text-[12.5px] font-medium text-ink">
          {TOOL_LABEL[name] ?? name}
        </span>
        {detail && (
          <span className="truncate font-mono text-[11px] text-faint">{detail}</span>
        )}
        <span
          className={
            'ml-auto shrink-0 text-faint transition-transform ' + (open ? 'rotate-90' : '')
          }
        >
          <Icon.chevron size={13} />
        </span>
      </button>

      {errorText && (
        <p className="border-t border-line px-3.5 py-2 font-mono text-[11px] text-bad">
          {errorText}
        </p>
      )}

      {/* the reconciliation result is the answer, not an attachment to it */}
      {name === 'run_reconciliation' && output !== undefined && (
        <div className="border-t border-line px-3.5 py-3">
          <ReconResult output={output} />
        </div>
      )}

      {open && output !== undefined && (
        <div className="border-t border-line px-3.5 pt-1 pb-3">
          <ToolOutput output={output} />
        </div>
      )}
    </div>
  )
}

function Reasoning({ text }: { text: string }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="rise">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-1.5 text-[11.5px] text-faint transition-colors hover:text-muted"
      >
        <span className={'transition-transform ' + (open ? 'rotate-90' : '')}>
          <Icon.chevron size={12} />
        </span>
        Reasoning
      </button>
      {open && (
        <p className="mt-1.5 border-l-2 border-line pl-3 text-[12px] leading-relaxed whitespace-pre-wrap text-faint italic">
          {text}
        </p>
      )}
    </div>
  )
}

function Part({ part, streaming }: { part: AnyPart; streaming: boolean }) {
  if (part.type === 'text') {
    return (
      <div className={'rise text-[14px] leading-relaxed ' + (streaming ? 'caret' : '')}>
        <Markdown text={part.text} />
      </div>
    )
  }
  if (part.type === 'reasoning') return <Reasoning text={part.text} />
  if (part.type === 'data-activity') {
    const d = part.data as ActivityData
    if (d.state === 'done') return null
    return <p className="rise text-[11.5px] text-faint">{d.label}</p>
  }
  if (isToolUIPart(part)) return <ToolCard part={part} />
  return null
}

function Turn({ message, live }: { message: ReconUIMessage; live: boolean }) {
  if (message.role === 'user') {
    const text = message.parts
      .filter((p): p is Extract<AnyPart, { type: 'text' }> => p.type === 'text')
      .map((p) => p.text)
      .join('')
    return (
      <div className="flex justify-end">
        <p className="max-w-[80%] rounded-2xl rounded-br-md bg-accent-deep px-4 py-2.5 text-[13.5px] leading-relaxed text-[#f0fdf4]">
          {text}
        </p>
      </div>
    )
  }

  const last = message.parts.length - 1
  return (
    <div className="space-y-2.5">
      {message.parts.map((part, i) => (
        <Part key={i} part={part} streaming={live && i === last && part.type === 'text'} />
      ))}
    </div>
  )
}

export default function ChatPanel() {
  const { messages, busy, error, send, stop } = useChatState()
  const [text, setText] = useState('')
  const endRef = useRef<HTMLDivElement>(null)

  // Show the wait only when nothing else is already moving. Once prose starts
  // arriving the caret takes over, and a tool card carries its own spinner --
  // three things pulsing at once reads as three things happening.
  const tail = messages[messages.length - 1]
  const tailPart = tail?.parts?.[tail.parts.length - 1]
  const waiting = busy && !(tail?.role === 'assistant' && tailPart?.type === 'text')

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [messages, busy])

  function submit() {
    const value = text.trim()
    if (!value || busy) return
    send(value)
    setText('')
  }

  return (
    <section className="flex min-h-0 flex-1 flex-col">
      <div className="min-h-0 flex-1 overflow-y-auto px-6 py-6">
        <div className="mx-auto flex max-w-2xl flex-col gap-6">
          {messages.length === 0 && (
            <div className="pt-16 text-center">
              <p className="text-[15px] text-muted">Nothing has run yet.</p>
              <p className="mt-1.5 text-[13px] text-faint">
                Ask for a reconciliation, or about one transaction.
              </p>
            </div>
          )}

          {messages.map((m, i) => (
            <Turn key={m.id} message={m} live={busy && i === messages.length - 1} />
          ))}

          {waiting && (
            <div className="rise pt-0.5">
              <Dots />
            </div>
          )}

          {error && (
            <div className="rise flex gap-2.5 rounded-xl border border-warn/35 bg-warn/5 px-4 py-3">
              <span className="mt-0.5 shrink-0 text-warn">
                <Icon.alert size={14} />
              </span>
              <div className="min-w-0 flex-1">
                <p className="text-[12.5px] leading-relaxed text-ink">{error.message}</p>
                <button
                  onClick={() => send('continue')}
                  className="mt-2 text-[12px] font-medium text-accent-deep underline underline-offset-2 hover:text-accent"
                >
                  Ask again
                </button>
              </div>
            </div>
          )}

          <div ref={endRef} />
        </div>
      </div>

      <div className="shrink-0 px-6 pb-6">
        <div className="mx-auto flex max-w-2xl items-center gap-2">
          <div className="panel flex flex-1 items-center gap-2 py-1.5 pr-1.5 pl-5">
            <input
              value={text}
              onChange={(e) => setText(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault()
                  submit()
                }
              }}
              placeholder="Ask about the reconciliation…"
              className="flex-1 bg-transparent py-1.5 text-[13.5px] outline-none placeholder:text-faint"
            />
            {busy ? (
              <button onClick={stop} className="btn btn-ghost" title="Stop">
                <Icon.stop size={13} />
                Stop
              </button>
            ) : (
              <button onClick={submit} disabled={!text.trim()} className="btn btn-primary">
                <Icon.arrow size={14} />
              </button>
            )}
          </div>
        </div>
      </div>
    </section>
  )
}
