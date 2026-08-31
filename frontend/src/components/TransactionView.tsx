import { useEffect, useMemo, useState } from 'react'
import {
  formatMinor,
  listTransactions,
  type HopState,
  type Transaction,
  type TransactionsView,
  type TxHop,
  type TxState,
} from '@/lib/api'
import { useProposals } from '@/state/ProposalsContext'

/** Source names carry an ordering prefix that means nothing to a reader. */
const short = (name: string) => name.replace(/^source_\d+_/, '').replace(/_/g, ' ')

const HOP: Record<HopState, { mark: string; tone: string; label: string }> = {
  matched: { mark: '──✓──', tone: 'text-ok', label: 'matched' },
  tolerance: { mark: '──≈──', tone: 'text-ok/70', label: 'within tolerance' },
  unchecked: { mark: '──?──', tone: 'text-cyan', label: 'amounts not checked' },
  off: { mark: '──✗──', tone: 'text-warn', label: 'amounts differ' },
  ambiguous: { mark: '──!──', tone: 'text-bad', label: 'more than one candidate' },
  missing: { mark: '──╳──', tone: 'text-faint', label: 'no link' },
}

const GROUPS: { state: TxState; title: string; tone: string; openByDefault: boolean }[] = [
  { state: 'exception', title: 'Breaks', tone: 'text-warn', openByDefault: true },
  { state: 'incomplete', title: 'Incomplete', tone: 'text-violet', openByDefault: true },
  { state: 'unmatched', title: 'Unmatched', tone: 'text-faint', openByDefault: true },
  { state: 'pending', title: 'Awaiting approval', tone: 'text-cyan', openByDefault: false },
  { state: 'reconciled', title: 'Reconciled', tone: 'text-ok', openByDefault: false },
]

/** The chain itself: each source, and the state of the gap to the next one. */
function Flow({ hops, stages }: { hops: TxHop[]; stages: string[] }) {
  return (
    <div className="flex flex-wrap items-center gap-1 font-mono text-[11px]">
      {stages.map((stage, i) => {
        const hop = hops[i]
        return (
          <span key={stage} className="flex items-center gap-1">
            <span className="text-muted">{short(stage)}</span>
            {hop && (
              <span className={HOP[hop.state].tone} title={HOP[hop.state].label}>
                {HOP[hop.state].mark}
                {hop.state === 'off' && hop.balance_minor
                  ? ` ${formatMinor(Math.abs(hop.balance_minor))} `
                  : ''}
              </span>
            )}
          </span>
        )
      })}
    </div>
  )
}

function Row({ tx, stages }: { tx: Transaction; stages: string[] }) {
  const { open } = useProposals()
  const [expanded, setExpanded] = useState(false)

  return (
    <div className="rounded-lg border border-line bg-base/30">
      <button
        onClick={() => setExpanded((v) => !v)}
        className="flex w-full flex-col gap-1 px-3 py-2 text-left"
      >
        <div className="flex w-full items-center gap-2">
          <span className="font-mono text-[10px] text-faint">{expanded ? '−' : '+'}</span>
          <span className="font-mono text-[12px] text-ink">{tx.key}</span>
          {tx.reason && (
            <span className="truncate text-[11px] text-warn">{tx.reason}</span>
          )}
        </div>
        <div className="pl-4">
          <Flow hops={tx.hops} stages={stages} />
        </div>
      </button>

      {expanded && (
        <div className="space-y-1 border-t border-line px-3 py-2">
          {tx.legs.map((l) => (
            <button
              key={l.proposal_id}
              onClick={() => open(l.proposal_id)}
              className="flex w-full items-center gap-2 rounded px-2 py-1 text-left transition-colors hover:bg-accent/5"
            >
              <span className="font-mono text-[10px] text-faint">└</span>
              <span className="truncate font-mono text-[11px] text-muted">
                {l.group_key}
              </span>
              {l.is_batch && (
                <span className="shrink-0 font-mono text-[10px] text-violet">
                  shared batch of {l.batch_size}
                </span>
              )}
              <span className="ml-auto shrink-0 font-mono text-[10px] text-faint">
                {l.members.length} rows
              </span>
              {l.balance_minor !== null && l.balance_minor !== 0 && (
                <span className="shrink-0 font-mono text-[11px] tabular-nums text-warn">
                  {formatMinor(l.balance_minor)}
                </span>
              )}
              <span className="shrink-0 font-mono text-[10px] text-accent">open →</span>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

function Group({
  title,
  tone,
  items,
  stages,
  defaultOpen,
  action,
}: {
  title: string
  tone: string
  items: Transaction[]
  stages: string[]
  defaultOpen: boolean
  action?: React.ReactNode
}) {
  const [open, setOpen] = useState(defaultOpen)
  if (items.length === 0) return null
  return (
    <div>
      <div className="mb-1.5 flex items-center gap-2">
        <button
          onClick={() => setOpen((v) => !v)}
          className="flex items-center gap-2 text-left"
        >
          <span className="font-mono text-[10px] text-faint">{open ? '−' : '+'}</span>
          <span className={'text-[12px] ' + tone}>{title}</span>
          <span className="font-mono text-[11px] text-faint">{items.length}</span>
        </button>
        {action}
      </div>
      {open && (
        <div className="mb-4 space-y-1">
          {items.map((t) => (
            <Row key={t.key} tx={t} stages={stages} />
          ))}
        </div>
      )}
    </div>
  )
}

export default function TransactionView() {
  const { proposals, rules, approveRule, busy } = useProposals()
  const [view, setView] = useState<TransactionsView | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    listTransactions()
      .then((v) => !cancelled && setView(v))
      .catch((e: Error) => !cancelled && setError(e.message))
    return () => {
      cancelled = true
    }
  }, [proposals])

  const grouped = useMemo(() => {
    const m = new Map<TxState, Transaction[]>()
    for (const t of view?.transactions ?? []) {
      const list = m.get(t.state) ?? []
      list.push(t)
      m.set(t.state, list)
    }
    return m
  }, [view])

  const unproven = rules.filter((r) => r.status === 'unproven' && r.pending > 0)

  if (error) return <p className="px-1 py-3 text-[12px] text-bad">{error}</p>
  if (!view) return <p className="px-1 py-3 text-[12px] text-faint">Assembling chains…</p>
  if (view.transactions.length === 0) {
    return (
      <p className="px-1 py-3 text-[13px] text-faint">
        No transactions yet — reconcile some sources first.
      </p>
    )
  }

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2 font-mono text-[11px] text-faint">
        <span>flow:</span>
        {view.stages.map((s, i) => (
          <span key={s}>
            <span className="text-muted">{short(s)}</span>
            {i < view.stages.length - 1 && <span className="px-1">→</span>}
          </span>
        ))}
      </div>

      {unproven.length > 0 && (
        <div className="flex flex-wrap items-center gap-2 rounded-lg border border-ok/30 bg-ok/5 px-3 py-2">
          <span className="text-[12px] text-muted">
            Nothing is final until you approve the rule that produced it.
          </span>
          {unproven.map((r) => (
            <button
              key={r.rule}
              onClick={() => void approveRule(r.rule)}
              disabled={busy}
              className="rounded-md bg-ok/20 px-2.5 py-1 font-mono text-[11px] text-ok transition-colors hover:bg-ok/30 disabled:opacity-40"
            >
              Approve {short(r.rule.replace(/^auto_exact__/, ''))} ({r.pending})
            </button>
          ))}
        </div>
      )}

      {GROUPS.map((g) => (
        <Group
          key={g.state}
          title={g.title}
          tone={g.tone}
          items={grouped.get(g.state) ?? []}
          stages={view.stages}
          defaultOpen={g.openByDefault}
        />
      ))}

      {view.leftovers.length > 0 && (
        <div>
          <div className="eyebrow mb-1.5">In no transaction at all</div>
          <div className="space-y-2">
            {view.leftovers.map((lo) => (
              <div key={lo.dataset_id} className="rounded-lg border border-line bg-base/30">
                <div className="border-b border-line px-3 py-1.5 font-mono text-[11px] text-muted">
                  {short(lo.dataset)} · {lo.count} rows nothing references
                </div>
                <div className="max-h-48 overflow-auto p-2">
                  <table className="w-full border-collapse font-mono text-[11px]">
                    <tbody>
                      {lo.rows.map((r, i) => (
                        <tr key={i}>
                          {Object.entries(r)
                            .filter(([k]) => k !== '__row')
                            .slice(0, 5)
                            .map(([k, v]) => (
                              <td
                                key={k}
                                className="border-b border-line/40 px-2 py-1 whitespace-nowrap text-muted"
                              >
                                {v === null ? '∅' : String(v)}
                              </td>
                            ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
