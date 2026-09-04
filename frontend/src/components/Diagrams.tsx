/**
 * The two diagrams on the landing page.
 *
 * Drawn in markup rather than rendered from mermaid: a diagram library costs
 * about a megabyte to say what nine divs already say, and it would arrive with
 * its own palette to fight. These inherit the theme tokens, so they stay
 * correct when the theme moves.
 *
 * Both are wide, and both scroll inside their own container rather than
 * squashing. A pipeline that wraps mid-flow stops reading as a pipeline.
 */

import type { ReactNode } from 'react'

function Arrow({ label }: { label?: string }) {
  return (
    <div className="flex shrink-0 flex-col items-center gap-1 self-center px-0.5">
      <svg width="28" height="8" viewBox="0 0 34 8" aria-hidden className="text-accent">
        <path
          d="M0 4h27M24 1l3.5 3-3.5 3"
          stroke="currentColor"
          strokeWidth="1.3"
          fill="none"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
      {label && <span className="font-mono text-[9px] text-faint">{label}</span>}
    </div>
  )
}

function Node({
  title,
  sub,
  children,
  tone = 'plain',
  className = '',
}: {
  title: string
  sub?: string
  children?: ReactNode
  tone?: 'plain' | 'accent' | 'quiet'
  className?: string
}) {
  const skin =
    tone === 'accent'
      ? 'border-accent/35 bg-accent-soft/60'
      : tone === 'quiet'
        ? 'border-line bg-sunk/60'
        : 'border-line bg-white/75'
  return (
    <div className={`shrink-0 rounded-xl border px-4 py-3 ${skin} ${className}`}>
      <p className="font-mono text-[11.5px] font-medium text-ink">{title}</p>
      {sub && <p className="mt-0.5 text-[11px] leading-snug text-muted">{sub}</p>}
      {children}
    </div>
  )
}

const TOOLS: [string, string][] = [
  ['list_datasets', 'what exists'],
  ['describe_dataset', 'per-column statistics'],
  ['query_data', 'one read-only SELECT'],
  ['run_reconciliation', 'the whole deterministic pass'],
  ['get_exceptions', 'everything needing a person'],
  ['get_transaction_chain', 'follow one id end to end'],
]

const GUARDS: [string, string][] = [
  ['6', 'looking calls per turn'],
  ['6k', 'chars of tool result'],
  ['40', 'model calls per turn'],
  ['read-only', 'SQL, single select'],
]

export function AgentDiagram() {
  return (
    <div className="panel overflow-x-auto p-6">
      <div className="flex min-w-[980px] items-stretch gap-1">
        <Node title="you" sub="“reconcile it”" tone="quiet" className="w-[92px] self-center" />
        <Arrow />

        <div className="flex w-[182px] shrink-0 flex-col rounded-xl border border-accent/35 bg-accent-soft/50 p-4">
          <p className="font-mono text-[11.5px] font-medium text-accent-deep">LlmAgent</p>
          <p className="mt-0.5 text-[11px] leading-snug text-muted">
            one model · picks the strategy, reads the result
          </p>
          <div className="mt-3 space-y-1.5 border-t border-accent/20 pt-3">
            {GUARDS.map(([n, what]) => (
              <p key={what} className="flex items-baseline gap-1.5 text-[10.5px] text-muted">
                <span className="font-mono text-accent-deep">{n}</span>
                {what}
              </p>
            ))}
          </div>
        </div>

        <Arrow label="tool call" />

        <div className="w-[238px] shrink-0 rounded-xl border border-line bg-white/75 p-4">
          <p className="eyebrow mb-2">Six tools</p>
          <ul className="space-y-1.5">
            {TOOLS.map(([name, what]) => (
              <li key={name} className="leading-tight">
                <span className="font-mono text-[11px] text-ink">{name}</span>
                <span className="ml-1.5 text-[10.5px] text-faint">{what}</span>
              </li>
            ))}
          </ul>
        </div>

        <Arrow />

        <div className="flex w-[178px] shrink-0 flex-col justify-center gap-2">
          <Node title="rule engine" sub="SQL — matching, summing, balancing" />
          <Node title="verifier" sub="re-derives every figure from source cells" />
        </div>

        <Arrow />
        <Node
          title="SQLite"
          sub="one table per file, plus derived views"
          tone="quiet"
          className="w-[146px] self-center"
        />
      </div>

      <p className="mt-5 border-t border-line pt-4 text-[12px] leading-relaxed text-muted">
        The return path is a stream — prose, reasoning and tool calls arrive as
        they happen. <span className="text-ink">No number crosses it that the
        model produced.</span> Every figure comes back from a tool, which got it
        from SQL, which got it from a row in your file.
      </p>
    </div>
  )
}

const PIPELINE: [string, string][] = [
  ['ingest', 'sniff, type, one table per file'],
  ['mark repeats', 'byte-identical, and same-event-new-id'],
  ['discover joins', 'value overlap, every column pair'],
  ['embedded keys', 'a reference inside a narration'],
  ['classify shape', '1:1 · 1:N · N:1 · N:M declined'],
  ['find amounts', 'by measured agreement, never by name'],
  ['propose', 'confidence computed, never asserted'],
  ['verify', 'twelve invariants, from source cells'],
]

export function RuleEngineDiagram() {
  const rows = [PIPELINE.slice(0, 4), PIPELINE.slice(4)]
  return (
    <div className="panel overflow-x-auto p-6">
      <div className="min-w-[880px]">
        {rows.map((row, r) => (
          <div key={r} className={`flex items-stretch gap-1 ${r ? 'mt-3' : ''}`}>
            {row.map(([title, sub], i) => (
              <div key={title} className="flex items-stretch gap-1">
                <Node
                  title={title}
                  sub={sub}
                  tone={title === 'verify' ? 'accent' : 'plain'}
                  className="w-[148px]"
                />
                {i < row.length - 1 && <Arrow />}
              </div>
            ))}

            {r === 0 ? (
              // The flow continues on the next row; say so rather than leaving
              // the reader to guess that four boxes is the whole pipeline.
              <div className="flex items-center gap-1.5 self-center pl-2">
                <svg width="30" height="30" viewBox="0 0 30 30" aria-hidden className="text-accent">
                  <path
                    d="M2 8h18a4 4 0 0 1 4 4v8M21 17l3 3.5 3-3.5"
                    stroke="currentColor"
                    strokeWidth="1.3"
                    fill="none"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </svg>
                <span className="font-mono text-[9px] text-faint">continues</span>
              </div>
            ) : (
              <>
                <svg
                  width="26"
                  height="64"
                  viewBox="0 0 26 64"
                  aria-hidden
                  className="shrink-0 self-center text-accent"
                >
                  <path
                    d="M0 32h9M9 32V12h13M9 32v20h13M19 9l3.5 3-3.5 3M19 49l3.5 3-3.5 3"
                    stroke="currentColor"
                    strokeWidth="1.3"
                    fill="none"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </svg>
                <div className="flex w-[176px] shrink-0 flex-col justify-center gap-2">
                  <div className="rounded-xl border border-ok/40 bg-ok/10 px-3.5 py-2">
                    <p className="font-mono text-[11.5px] font-medium text-accent-deep">accepted</p>
                    <p className="text-[10.5px] leading-snug text-muted">
                      exact · verified · rule trusted
                    </p>
                  </div>
                  <div className="rounded-xl border border-warn/40 bg-warn/10 px-3.5 py-2">
                    <p className="font-mono text-[11.5px] font-medium text-warn">held</p>
                    <p className="text-[10.5px] leading-snug text-muted">
                      anything else — a person decides
                    </p>
                  </div>
                </div>
              </>
            )}
          </div>
        ))}
      </div>

      <p className="mt-5 border-t border-line pt-4 text-[12px] leading-relaxed text-muted">
        No thresholds are configured anywhere in this path.{' '}
        <span className="text-ink">
          The settlement lag, the amount columns, the join keys and the direction
          of flow are all measured from your files
        </span>{' '}
        — a constant that is right for one processor&rsquo;s contract is wrong for
        the next dataset.
      </p>
    </div>
  )
}
