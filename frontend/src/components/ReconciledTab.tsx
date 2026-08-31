import { useEffect, useState } from 'react'
import { formatMinor, getProposal, type Proposal, type ProposalDetail } from '@/lib/api'
import { useProposals } from '@/state/ProposalsContext'
import { CONFIDENCE_TONE } from '@/components/ProposalModal'
import TransactionView from '@/components/TransactionView'

/** Expanded row: the members that reconciled, and the events in order. */
function Detail({ id }: { id: number }) {
  const [d, setD] = useState<ProposalDetail | null>(null)

  useEffect(() => {
    let cancelled = false
    getProposal(id).then((x) => !cancelled && setD(x)).catch(() => {})
    return () => {
      cancelled = true
    }
  }, [id])

  if (!d) return <div className="px-3 py-2 text-[11px] text-faint">Loading…</div>

  return (
    <div className="space-y-3 border-t border-line px-3 py-3">
      <div>
        <div className="eyebrow mb-1.5">Members</div>
        <table className="w-full border-collapse font-mono text-[11px]">
          <tbody>
            {d.members.map((m) => (
              <tr key={`${m.dataset_id}:${m.row}`}>
                <td className="py-0.5 pr-3 text-accent">{m.dataset}</td>
                <td className="py-0.5 pr-3 text-faint">{m.role ?? ''}</td>
                <td className="py-0.5 pr-3 text-muted">row {m.row}</td>
                <td className="py-0.5 text-right tabular-nums text-ink">
                  {formatMinor(m.amount_minor)}
                </td>
              </tr>
            ))}
            <tr className="border-t border-line">
              <td colSpan={3} className="pt-1 text-faint">
                balance
              </td>
              <td
                className={
                  'pt-1 text-right tabular-nums ' +
                  (d.balance_minor === 0 ? 'text-ok' : 'text-warn')
                }
              >
                {formatMinor(d.balance_minor)}
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <div>
        <div className="eyebrow mb-1.5">Audit trail</div>
        <ol className="space-y-0.5">
          {d.events.map((e, i) => (
            <li key={i} className="flex items-baseline gap-2 font-mono text-[11px]">
              <span className="text-faint">{i + 1}.</span>
              <span className="text-faint">{e.ts}</span>
              <span className="text-ink">{e.kind}</span>
              <span className="text-faint">by {e.actor}</span>
            </li>
          ))}
        </ol>
      </div>
    </div>
  )
}

function Row({ p }: { p: Proposal }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="rounded-lg border border-line bg-base/30">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-2 px-3 py-2 text-left"
      >
        <span className="font-mono text-[10px] text-faint">{open ? '−' : '+'}</span>
        <span className={'pill border ' + CONFIDENCE_TONE[p.confidence]}>{p.confidence}</span>
        <span className="truncate font-mono text-[12px] text-ink">{p.group_key}</span>
        <span className="shrink-0 font-mono text-[10px] text-faint">
          {p.dataset_names.join(' ↔ ')}
        </span>
        <span className="ml-auto shrink-0 font-mono text-[10px] text-faint">
          tier {p.tier} · {p.member_count} rows
        </span>
      </button>
      {open && <Detail id={p.id} />}
    </div>
  )
}

/** Pending grouped by the rule that produced it.
 *
 *  Reviewing by rule is the point: an unscoped rule shows up as a batch far
 *  wider than what was asked for, which is invisible when the same matches are
 *  listed one by one. */
function PendingByRule() {
  const { pending, rules, approveRule, open, busy } = useProposals()
  const byRule = new Map<string, typeof pending>()
  for (const p of pending) {
    const list = byRule.get(p.rule) ?? []
    list.push(p)
    byRule.set(p.rule, list)
  }

  return (
    <div className="mb-4 space-y-3">
      {[...byRule.entries()].map(([rule, items]) => {
        const trust = rules.find((r) => r.rule === rule)
        const exact = items.filter((i) => i.confidence === 'exact').length
        return (
          <div key={rule} className="rounded-lg border border-warn/30 bg-warn/5">
            <div className="flex flex-wrap items-center gap-2 border-b border-line px-3 py-2">
              <span className="font-mono text-[12px] text-ink">{rule}</span>
              <span className="font-mono text-[10px] text-faint">
                {items.length} awaiting · {trust?.status ?? 'unproven'}
              </span>
              {exact > 0 && (
                <button
                  onClick={() => void approveRule(rule)}
                  disabled={busy}
                  className="ml-auto rounded-md bg-ok/20 px-2.5 py-1 text-[11px] text-ok transition-colors hover:bg-ok/30 disabled:opacity-40"
                >
                  Approve rule ({exact} exact)
                </button>
              )}
            </div>
            <div className="space-y-1 p-2">
              {items.map((p) => (
                <button
                  key={p.id}
                  onClick={() => open(p.id)}
                  className="flex w-full items-center gap-2 rounded-md border border-line bg-base/30 px-2.5 py-1.5 text-left transition-colors hover:border-warn/60"
                >
                  <span className={'pill border ' + CONFIDENCE_TONE[p.confidence]}>
                    {p.confidence}
                  </span>
                  <span className="truncate font-mono text-[12px] text-ink">{p.group_key}</span>
                  <span className="ml-auto shrink-0 font-mono text-[10px] text-warn">
                    {p.status === 'review_later' ? 'deferred' : 'review'} →
                  </span>
                </button>
              ))}
            </div>
          </div>
        )
      })}
    </div>
  )
}

type GroupBy = 'transaction' | 'rule'

export default function ReconciledTab() {
  const { accepted, pending, summary } = useProposals()
  // Two ways to read the same matches: by transaction to audit one end to end,
  // by rule to judge the rule that produced them.
  const [groupBy, setGroupBy] = useState<GroupBy>('transaction')

  if (accepted.length === 0 && pending.length === 0) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-2 px-8 text-center">
        <div className="eyebrow">Nothing reconciled yet</div>
        <p className="max-w-sm text-[13px] text-faint">
          Ask the agent to reconcile your sources. Matches it is certain about land here;
          anything less certain waits for your decision.
        </p>
      </div>
    )
  }

  return (
    <div className="h-full overflow-y-auto px-4 py-3">
      <div className="mb-3 flex flex-wrap items-center gap-3 font-mono text-[11px]">
        <span className="text-ok">{summary?.by_status.accepted ?? 0} reconciled</span>
        <span className="text-warn">{summary?.needs_review ?? 0} awaiting decision</span>
        <span className="text-faint">{summary?.by_status.rejected ?? 0} rejected</span>

        <div className="ml-auto flex items-center gap-0.5 rounded-md border border-line p-0.5">
          {(['transaction', 'rule'] as GroupBy[]).map((g) => (
            <button
              key={g}
              onClick={() => setGroupBy(g)}
              className={
                'rounded px-2 py-0.5 text-[11px] transition-colors ' +
                (groupBy === g ? 'bg-accent/20 text-ink' : 'text-faint hover:text-muted')
              }
            >
              by {g}
            </button>
          ))}
        </div>
      </div>

      {/* The toggle governs everything. Previously the pending queue was always
          rule-grouped, so "by transaction" showed rule cards and buried the
          transactions below them -- the toggle looked broken because it was. */}
      {groupBy === 'transaction' ? (
        <TransactionView />
      ) : (
        <>
          {pending.length > 0 && (
            <>
              <div className="eyebrow mb-1.5">Awaiting your decision</div>
              <PendingByRule />
            </>
          )}
          {accepted.length > 0 && (
            <>
              <div className="eyebrow mb-1.5">Reconciled</div>
              <div className="space-y-1">
                {accepted.map((p) => (
                  <Row key={p.id} p={p} />
                ))}
              </div>
            </>
          )}
        </>
      )}
    </div>
  )
}
