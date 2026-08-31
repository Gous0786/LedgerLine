import { useEffect, useState } from 'react'
import {
  formatMinor,
  listTransactions,
  type Transaction,
  type TransactionsView,
  type TxLeg,
  type TxState,
} from '@/lib/api'
import { useProposals } from '@/state/ProposalsContext'
import { CONFIDENCE_TONE } from '@/components/ProposalModal'

const STATE_TONE: Record<TxState, string> = {
  reconciled: 'text-ok border-ok/40 bg-ok/10',
  pending: 'text-cyan border-cyan/40 bg-cyan/10',
  exception: 'text-warn border-warn/40 bg-warn/10',
  incomplete: 'text-violet border-violet/40 bg-violet/10',
  unmatched: 'text-faint border-line bg-base/40',
}

const STATE_WHY: Record<TxState, string> = {
  reconciled: 'every leg matched and accepted',
  pending: 'legs matched, awaiting your decision',
  exception: 'a leg does not balance',
  incomplete: 'fewer legs than a typical transaction — a source never linked',
  unmatched: 'no source links to this at all',
}

/** One leg of the chain. Batches are shown but not expanded — they belong to
 *  several transactions at once. */
function Leg({ leg }: { leg: TxLeg }) {
  const { open } = useProposals()
  const off = leg.balance_minor !== null && leg.balance_minor !== 0

  return (
    <button
      onClick={() => open(leg.proposal_id)}
      className="flex w-full items-center gap-2 rounded-md px-2 py-1 text-left transition-colors hover:bg-accent/5"
    >
      <span className="font-mono text-[10px] text-faint">└</span>
      <span className={'pill border ' + CONFIDENCE_TONE[leg.confidence]}>
        {leg.confidence}
      </span>
      <span className="truncate font-mono text-[11px] text-muted">{leg.group_key}</span>
      {leg.is_batch && (
        <span className="shrink-0 font-mono text-[10px] text-violet">
          batch ×{leg.batch_size}
        </span>
      )}
      <span className="shrink-0 font-mono text-[10px] text-faint">
        {leg.members.map((m) => m.dataset.replace(/^source_\d+_/, '')).join(' ↔ ')}
      </span>
      {off && (
        <span className="ml-auto shrink-0 font-mono text-[11px] tabular-nums text-warn">
          {formatMinor(leg.balance_minor)}
        </span>
      )}
    </button>
  )
}

function Row({ tx }: { tx: Transaction }) {
  const [open, setOpen] = useState(tx.state === 'exception')
  // pick a couple of readable fields off the spine row for the header
  const summary = Object.entries(tx.data)
    .filter(([k, v]) => k !== '__row' && v !== null && String(v) !== tx.key)
    .slice(0, 2)
    .map(([, v]) => String(v))
    .join(' · ')

  return (
    <div className="rounded-lg border border-line bg-base/30">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-2 px-3 py-2 text-left"
      >
        <span className="font-mono text-[10px] text-faint">{open ? '−' : '+'}</span>
        <span className="font-mono text-[12px] text-ink">{tx.key}</span>
        <span className="truncate text-[11px] text-faint">{summary}</span>
        <span className={'pill ml-auto shrink-0 border ' + STATE_TONE[tx.state]}>
          {tx.state}
        </span>
        <span className="shrink-0 font-mono text-[10px] text-faint tabular-nums">
          {tx.leg_count}/{tx.expected_legs}
        </span>
      </button>

      {open && (
        <div className="border-t border-line px-3 py-2">
          <div className="mb-1 font-mono text-[10px] text-faint">{STATE_WHY[tx.state]}</div>
          {tx.legs.length === 0 ? (
            <div className="px-2 py-1 font-mono text-[11px] text-faint">
              no legs — nothing in any other source references this
            </div>
          ) : (
            tx.legs.map((l) => <Leg key={l.proposal_id} leg={l} />)
          )}
        </div>
      )}
    </div>
  )
}

export default function TransactionView() {
  const { proposals } = useProposals()
  const [view, setView] = useState<TransactionsView | null>(null)
  const [error, setError] = useState<string | null>(null)

  // rebuild whenever proposals change (a decision alters chain state)
  useEffect(() => {
    let cancelled = false
    listTransactions()
      .then((v) => !cancelled && setView(v))
      .catch((e: Error) => !cancelled && setError(e.message))
    return () => {
      cancelled = true
    }
  }, [proposals])

  if (error) return <p className="px-4 py-3 text-[12px] text-bad">{error}</p>
  if (!view) return <p className="px-4 py-3 text-[12px] text-faint">Assembling chains…</p>

  if (view.transactions.length === 0) {
    return (
      <p className="px-4 py-3 text-[13px] text-faint">
        No transactions yet — reconcile some sources first.
      </p>
    )
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3 font-mono text-[11px]">
        {(['reconciled', 'pending', 'exception', 'incomplete', 'unmatched'] as TxState[])
          .filter((s) => view.counts[s])
          .map((s) => (
            <span key={s} className={STATE_TONE[s].split(' ')[0]}>
              {view.counts[s]} {s}
            </span>
          ))}
      </div>

      <div className="space-y-1">
        {view.transactions.map((t) => (
          <Row key={t.key} tx={t} />
        ))}
      </div>

      {view.leftovers.length > 0 && (
        <div>
          <div className="eyebrow mb-1.5">
            Not part of any transaction
          </div>
          <div className="space-y-2">
            {view.leftovers.map((lo) => (
              <div key={lo.dataset_id} className="rounded-lg border border-line bg-base/30">
                <div className="border-b border-line px-3 py-1.5 font-mono text-[11px] text-muted">
                  {lo.dataset.replace(/^source_\d+_/, '')} · {lo.count} rows
                </div>
                <div className="max-h-56 overflow-auto p-2">
                  <table className="w-full border-collapse font-mono text-[11px]">
                    <tbody>
                      {lo.rows.map((r, i) => (
                        <tr key={i} className="hover:bg-accent/5">
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
