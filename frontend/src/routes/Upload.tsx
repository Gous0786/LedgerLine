/**
 * Upload, then ask. The two halves of starting a reconciliation, on one screen.
 *
 * The composer at the bottom is the same one the workspace uses. Pressing enter
 * here sends the turn *and* navigates, so the answer is already streaming by the
 * time the workspace paints -- the alternative, landing on an empty workspace
 * and typing again, makes the upload feel like a form to get through.
 */

import { useRef, useState } from 'react'
import { useRouter } from '@/app/router'
import { Icon, Logo, Spinner } from '@/components/ui'
import { useChatState } from '@/state/ChatContext'
import { useDatasets } from '@/state/DatasetsContext'
import { formatBytes } from '@/lib/api'

const SUGGESTIONS = [
  'Reconcile it',
  'What did not settle?',
  'Show me the batches that do not tie',
]

export default function Upload() {
  const { go } = useRouter()
  const { datasets, upload, remove, busy, error, failures, clearNotices } = useDatasets()
  const { send } = useChatState()
  const fileRef = useRef<HTMLInputElement>(null)
  const [dragging, setDragging] = useState(false)
  const [text, setText] = useState('')

  const ready = datasets.length > 0

  function pick(files: FileList | File[] | null) {
    if (!files) return
    const csvs = Array.from(files).filter((f) => /\.csv$/i.test(f.name))
    if (csvs.length) void upload(csvs)
  }

  function ask(prompt?: string) {
    const value = (prompt ?? text).trim()
    if (!value || !ready) return
    send(value)
    go('/workspace')
  }

  return (
    <div className="flex h-full flex-col">
      <header className="mx-auto flex w-full max-w-5xl items-center gap-4 px-8 py-6">
        <button onClick={() => go('/')} className="transition-opacity hover:opacity-70">
          <Logo />
        </button>
        <span className="ml-auto font-mono text-[11px] text-faint">
          {ready ? `${datasets.length} source${datasets.length === 1 ? '' : 's'} loaded` : 'CSV only'}
        </span>
        {ready && (
          <button onClick={() => go('/workspace')} className="btn btn-ghost">
            Skip to workspace
            <Icon.arrow size={14} />
          </button>
        )}
      </header>

      <main className="mx-auto flex w-full max-w-5xl flex-1 flex-col px-8 pb-8">
        <div className="pt-6 pb-8">
          <h1 className="text-[clamp(1.9rem,4vw,2.7rem)] leading-tight font-semibold tracking-[-0.025em] text-accent-deep">
            Add your sources
          </h1>
          <p className="mt-2 max-w-[58ch] text-[14px] leading-relaxed text-muted">
            One CSV per source — orders, processor, bank. Column names do not
            matter; the relationships between them are measured, not configured.
          </p>
        </div>

        {/* drop zone */}
        <label
          onDragOver={(e) => {
            e.preventDefault()
            setDragging(true)
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(e) => {
            e.preventDefault()
            setDragging(false)
            pick(e.dataTransfer.files)
          }}
          className={
            'flex cursor-pointer flex-col items-center justify-center gap-3 rounded-[var(--radius-panel)] border border-dashed px-6 py-12 text-center transition-colors ' +
            (dragging
              ? 'border-accent bg-accent-soft/60'
              : 'border-line-strong bg-white/50 hover:bg-white/80')
          }
        >
          <input
            ref={fileRef}
            type="file"
            accept=".csv,text/csv"
            multiple
            className="hidden"
            onChange={(e) => {
              pick(e.target.files)
              e.target.value = ''
            }}
          />
          <span className="text-accent">
            {busy ? <Spinner size={20} /> : <Icon.upload size={20} />}
          </span>
          <span className="text-[14px] font-medium text-ink">
            {busy ? 'Reading files…' : 'Drop CSVs here, or click to choose'}
          </span>
          <span className="font-mono text-[11px] text-faint">
            encoding and delimiter are sniffed · types inferred per column
          </span>
        </label>

        {(error || failures.length > 0) && (
          <div className="mt-3 rounded-xl border border-bad/30 bg-bad/5 px-4 py-3">
            <div className="flex items-start gap-2">
              <span className="mt-0.5 text-bad">
                <Icon.alert size={14} />
              </span>
              <div className="flex-1 text-[12.5px] text-bad">
                {error && <p>{error}</p>}
                {failures.map((f) => (
                  <p key={f.file}>
                    <span className="font-mono">{f.file}</span> — {f.error}
                  </p>
                ))}
              </div>
              <button onClick={clearNotices} className="text-bad/60 hover:text-bad">
                <Icon.close size={14} />
              </button>
            </div>
          </div>
        )}

        {/* loaded sources */}
        {ready && (
          <ul className="mt-4 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
            {datasets.map((d) => (
              <li key={d.id} className="panel rise group flex items-center gap-3 px-4 py-3">
                <span className="text-accent">
                  <Icon.sheet size={16} />
                </span>
                <div className="min-w-0 flex-1">
                  <p className="truncate text-[13px] font-medium text-ink">{d.name}</p>
                  <p className="font-mono text-[11px] text-faint">
                    {d.row_count.toLocaleString()} rows · {d.column_count} cols ·{' '}
                    {formatBytes(d.byte_size)}
                  </p>
                </div>
                <button
                  onClick={() => void remove(d.id)}
                  title="Remove"
                  className="text-faint opacity-0 transition-opacity group-hover:opacity-100 hover:text-bad"
                >
                  <Icon.trash size={14} />
                </button>
              </li>
            ))}
          </ul>
        )}

        <div className="flex-1" />

        {/* composer */}
        <div className="pt-10">
          {ready && (
            <div className="mb-3 flex flex-wrap gap-2">
              {SUGGESTIONS.map((s) => (
                <button
                  key={s}
                  onClick={() => ask(s)}
                  className="pill border-line bg-white/70 text-muted transition-colors hover:border-accent/40 hover:text-accent-deep"
                >
                  {s}
                </button>
              ))}
            </div>
          )}
          <div className="panel flex items-center gap-2 py-2 pr-2 pl-5">
            <input
              value={text}
              onChange={(e) => setText(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault()
                  ask()
                }
              }}
              disabled={!ready}
              placeholder={
                ready ? 'Ask for a reconciliation…' : 'Add at least one CSV to begin'
              }
              className="flex-1 bg-transparent text-[14px] outline-none placeholder:text-faint disabled:cursor-not-allowed"
            />
            <button
              onClick={() => ask()}
              disabled={!ready || !text.trim()}
              className="btn btn-primary"
            >
              Ask
              <Icon.arrow size={14} />
            </button>
          </div>
          <p className="mt-2 pl-5 font-mono text-[11px] text-faint">
            enter sends and opens the workspace
          </p>
        </div>
      </main>
    </div>
  )
}
