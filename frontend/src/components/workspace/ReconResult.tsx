/**
 * `run_reconciliation`, rendered as the thing it is rather than as JSON.
 *
 * The result already carries the whole picture -- which strategy each edge got,
 * what it refused and why, and the coverage that follows -- so the card shows
 * exactly that and the reviewer never has to open the payload to learn it.
 *
 * Handles both modes. The automatic pass reports rules, declines and coverage;
 * a hand-written rule reports one rule's counts. They share a shape closely
 * enough that one component is honest, and two would drift.
 */

import { Icon, Pill } from '@/components/ui'

interface RuleResult {
  rule?: string
  join?: string
  shape?: string
  strategy?: string
  amounts?: string | null
  agreement?: number | null
  tolerance_minor?: number
  proposed?: number
  by_confidence?: Record<string, number>
  duplicate_members_flagged?: number
  error?: string
}

interface Declined {
  join?: string
  shape?: string
  reason?: string
}

const CONFIDENCE_TONE: Record<string, 'ok' | 'warn' | 'bad' | 'info' | 'neutral'> = {
  exact: 'ok',
  within_tolerance: 'info',
  high: 'neutral',
  unbalanced: 'warn',
  ambiguous: 'warn',
}

function Confidences({ mix }: { mix: Record<string, number> }) {
  const entries = Object.entries(mix).filter(([, n]) => n > 0)
  if (!entries.length) return null
  return (
    <div className="flex flex-wrap gap-1.5">
      {entries.map(([k, n]) => (
        <Pill key={k} tone={CONFIDENCE_TONE[k] ?? 'neutral'}>
          {n} {k.replace(/_/g, ' ')}
        </Pill>
      ))}
    </div>
  )
}

function Coverage({ coverage }: { coverage: Record<string, unknown> }) {
  const datasets = (coverage.datasets ?? []) as {
    dataset: string
    rows: number
    matched_in_any_edge: number
    matched_in_no_edge: number
  }[]
  if (!datasets.length) return null

  return (
    <div className="space-y-1.5">
      <p className="eyebrow">Coverage</p>
      {datasets.map((d) => {
        const pct = d.rows ? Math.round((d.matched_in_any_edge / d.rows) * 100) : 0
        return (
          <div key={d.dataset} className="flex items-center gap-3">
            <span className="w-44 shrink-0 truncate font-mono text-[11px] text-muted">
              {d.dataset}
            </span>
            <span className="h-1.5 flex-1 overflow-hidden rounded-full bg-sunk">
              <span
                className="block h-full rounded-full bg-accent transition-[width] duration-500"
                style={{ width: `${pct}%` }}
              />
            </span>
            <span className="w-28 shrink-0 text-right font-mono text-[11px] text-faint">
              {d.matched_in_any_edge}/{d.rows}
              {d.matched_in_no_edge > 0 && (
                <span className="text-warn"> · {d.matched_in_no_edge} loose</span>
              )}
            </span>
          </div>
        )
      })}
    </div>
  )
}

export default function ReconResult({ output }: { output: unknown }) {
  const o = (output ?? {}) as Record<string, unknown>

  if (o.error) {
    return (
      <p className="rounded-lg border border-bad/30 bg-bad/5 px-3 py-2 font-mono text-[11.5px] text-bad">
        {String(o.error)}
      </p>
    )
  }

  // --- one hand-written rule -------------------------------------------
  if (o.rule && !o.results) {
    const mix = (o.by_confidence ?? {}) as Record<string, number>
    return (
      <div className="space-y-2">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-mono text-[12px] text-ink">{String(o.rule)}</span>
          <Pill tone={o.rule_status === 'trusted' ? 'ok' : 'neutral'}>
            {String(o.rule_status ?? 'unproven')}
          </Pill>
          <span className="font-mono text-[11px] text-muted">
            {Number(o.proposed ?? 0)} groups
          </span>
        </div>
        <Confidences mix={mix} />
      </div>
    )
  }

  // --- the automatic pass ----------------------------------------------
  const results = (o.results ?? []) as RuleResult[]
  const declined = (o.declined ?? []) as Declined[]
  const coverage = (o.coverage ?? {}) as Record<string, unknown>
  const total = Number(o.groups_proposed ?? 0)

  return (
    <div className="space-y-3.5">
      <p className="text-[13px] text-ink">
        <span className="font-medium">{total.toLocaleString()}</span> groups from{' '}
        {results.length} rule{results.length === 1 ? '' : 's'}
        {declined.length > 0 && (
          <span className="text-warn"> · {declined.length} edge declined</span>
        )}
      </p>

      {results.map((r) => (
        <div key={r.rule} className="rounded-lg border border-line bg-white/60 px-3 py-2.5">
          {r.error ? (
            <p className="font-mono text-[11px] text-bad">{r.error}</p>
          ) : (
            <>
              <div className="flex flex-wrap items-center gap-2">
                <Pill tone="accent">{r.shape}</Pill>
                <span className="text-[12px] text-muted">{r.strategy}</span>
                <span className="ml-auto font-mono text-[11px] text-faint">
                  {r.proposed} groups
                </span>
              </div>
              <p className="mt-1.5 truncate font-mono text-[11px] text-faint">{r.join}</p>
              {r.amounts && (
                <p className="mt-0.5 truncate font-mono text-[11px] text-muted">
                  {r.amounts}
                  {r.agreement != null && (
                    <span className="text-faint"> · agreement {r.agreement}</span>
                  )}
                </p>
              )}
              {r.duplicate_members_flagged ? (
                <p className="mt-1 font-mono text-[11px] text-warn">
                  {r.duplicate_members_flagged} duplicated row(s) flagged
                </p>
              ) : null}
              {r.by_confidence && (
                <div className="mt-2">
                  <Confidences mix={r.by_confidence} />
                </div>
              )}
            </>
          )}
        </div>
      ))}

      {declined.map((d, i) => (
        <div key={i} className="rounded-lg border border-warn/30 bg-warn/5 px-3 py-2.5">
          <div className="flex items-center gap-2">
            <span className="text-warn">
              <Icon.alert size={13} />
            </span>
            <span className="text-[12px] font-medium text-ink">
              Declined {d.shape} edge
            </span>
          </div>
          <p className="mt-1 font-mono text-[11px] text-muted">{d.join}</p>
          <p className="mt-1 text-[12px] leading-relaxed text-muted">{d.reason}</p>
        </div>
      ))}

      <Coverage coverage={coverage} />
    </div>
  )
}
