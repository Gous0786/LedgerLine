/**
 * The left rail: what has been settled, and what is waiting on a person.
 *
 * Collapsed it is a scoreboard -- how much is done, how much needs review.
 * Expanded it is the work itself, in two readings of the same reconciliation:
 *
 *   Matches  one edge at a time. Two rows that tie.
 *   Chains   the whole path -- order to processor to bank -- and where it broke.
 *
 * Both matter and neither replaces the other. A match answers "do these two
 * agree"; a chain answers "did this transaction actually complete", which is
 * the question somebody closing a month is really asking.
 */

import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  listTransactions,
  type Confidence,
  type Transaction,
  type TransactionsView,
} from '@/lib/api'
import { ChainSheet, ChainStrip, STATE_TONE } from '@/components/workspace/Chain'
import { Icon, Pill, Spinner, type Tone } from '@/components/ui'
import { useChatState } from '@/state/ChatContext'
import type { DatasetCoverage } from '@/lib/api'
import { useProposals } from '@/state/ProposalsContext'

const CONFIDENCE_TONE: Record<Confidence, Tone> = {
  exact: 'ok',
  within_tolerance: 'info',
  high: 'neutral',
  unbalanced: 'warn',
  ambiguous: 'warn',
}

type Mode = 'matches' | 'chains'
type Filter = 'review' | 'settled' | 'all'

const FILTERS: { id: Filter; label: string }[] = [
  { id: 'review', label: 'Needs review' },
  { id: 'settled', label: 'Settled' },
  { id: 'all', label: 'All' },
]

/** Broken first: a list sorted by severity is a worklist, one sorted by key is a
 *  directory. */
const STATE_ORDER: Record<string, number> = {
  exception: 0,
  incomplete: 1,
  unmatched: 2,
  pending: 3,
  reconciled: 4,
}

function SourceBar({ d }: { d: DatasetCoverage }) {
  const pct = d.rows ? Math.round((d.matched_in_any_edge / d.rows) * 100) : 0
  return (
    <div>
      <div className="flex items-baseline gap-2">
        <span className="truncate font-mono text-[10.5px] text-muted">{d.dataset}</span>
        <span className="ml-auto shrink-0 font-mono text-[10.5px] tabular-nums text-ink">
          {d.matched_in_any_edge}
          <span className="text-faint">/{d.rows}</span>
        </span>
      </div>
      <div className="mt-1 h-1 overflow-hidden rounded-full bg-sunk">
        <div
          className={
            'h-full rounded-full transition-[width] duration-500 ' +
            (pct === 100 ? 'bg-accent' : pct >= 60 ? 'bg-accent/70' : 'bg-warn/60')
          }
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  )
}

export default function ReconciledRail({
  expanded,
  onToggle,
}: {
  expanded: boolean
  onToggle: () => void
}) {
  // Straight from the shared store: the rail and the review sheet must never
  // disagree about what is outstanding, and a second fetch is a second truth.
  const { summary, open, proposals, coverage, actMany } = useProposals()
  const { busy } = useChatState()
  const [mode, setMode] = useState<Mode>('matches')
  const [filter, setFilter] = useState<Filter>('review')

  const [view, setView] = useState<TransactionsView | null>(null)
  const [loading, setLoading] = useState(false)
  const [openTx, setOpenTx] = useState<Transaction | null>(null)

  const needsReview = summary?.needs_review ?? 0
  const settled = summary?.by_status.accepted ?? 0
  const totals = coverage?.totals ?? null
  const pct = totals?.rows ? Math.round((totals.matched / totals.rows) * 100) : null
  const chainCounts = view
    ? {
        done: view.counts.reconciled ?? 0,
        open: view.transactions.length - (view.counts.reconciled ?? 0),
      }
    : null

  const rows = useMemo(() => {
    if (filter === 'all') return proposals
    if (filter === 'settled') return proposals.filter((p) => p.status === 'accepted')
    return proposals.filter((p) => p.status === 'pending' || p.status === 'review_later')
  }, [proposals, filter])

  const loadChains = useCallback(() => {
    setLoading(true)
    listTransactions()
      .then(setView)
      .catch(() => setView(null))
      .finally(() => setLoading(false))
  }, [])

  // Chains are assembled from every accepted match, so they are only correct
  // once the agent has stopped writing. Rebuilding on each token would be both
  // wrong and expensive.
  useEffect(() => {
    if (mode === 'chains' && expanded && !busy) loadChains()
  }, [mode, expanded, busy, proposals.length, loadChains])

  const chains = useMemo(() => {
    if (!view) return []
    return [...view.transactions].sort(
      (a, b) =>
        (STATE_ORDER[a.state] ?? 9) - (STATE_ORDER[b.state] ?? 9) ||
        a.key.localeCompare(b.key),
    )
  }, [view])

  return (
    <>
      <aside
        className={
          'panel flex min-h-0 shrink-0 flex-col overflow-hidden transition-[width] duration-200 ' +
          (expanded ? 'w-[340px]' : 'w-[212px]')
        }
      >
        <button
          onClick={onToggle}
          className="flex shrink-0 items-center gap-2 border-b border-line px-3.5 py-3 text-left"
        >
          <span className="eyebrow">Reconciled</span>
          <span
            className={
              'ml-auto text-faint transition-transform ' + (expanded ? 'rotate-180' : '')
            }
          >
            <Icon.chevron size={14} />
          </span>
        </button>

        {/* the scoreboard, always on. "272 settled" does not answer "how much
            of the bank statement is explained", so the rows are here too. */}
        <div className="shrink-0 space-y-3 px-3.5 py-3">
          <div>
            <p className="font-mono text-[27px] leading-none text-accent-deep">
              {pct === null ? '—' : `${pct}%`}
            </p>
            <p className="mt-1 text-[11.5px] text-faint">
              {totals ? `${totals.matched} of ${totals.rows} rows` : 'no data yet'}
            </p>
          </div>

          <div className="flex gap-4">
            <div>
              <p className="font-mono text-[16px] leading-none text-ink">{settled}</p>
              <p className="mt-1 text-[10.5px] text-faint">settled</p>
            </div>
            <div>
              <p
                className={
                  'font-mono text-[16px] leading-none ' +
                  (needsReview > 0 ? 'text-warn' : 'text-faint')
                }
              >
                {needsReview}
              </p>
              <p className="mt-1 text-[10.5px] text-faint">to review</p>
            </div>
            {chainCounts && (
              <div>
                <p className="font-mono text-[16px] leading-none text-ink">
                  {chainCounts.done}
                </p>
                <p className="mt-1 text-[10.5px] text-faint">chains</p>
              </div>
            )}
          </div>

          <div className="space-y-1.5 border-t border-line pt-2.5">
            {(coverage?.datasets ?? []).map((d) => (
              <SourceBar key={d.dataset_id} d={d} />
            ))}
            {!coverage && (
              <p className="text-[11px] text-faint">Loading coverage…</p>
            )}
          </div>
        </div>

        {expanded && (
          <>
            <div className="flex shrink-0 gap-1 border-t border-line px-2.5 pt-2">
              {(['matches', 'chains'] as Mode[]).map((m) => (
                <button
                  key={m}
                  onClick={() => setMode(m)}
                  className={
                    'flex-1 rounded-lg py-1.5 text-[12px] capitalize transition-colors ' +
                    (mode === m
                      ? 'bg-accent-soft font-medium text-accent-deep'
                      : 'text-muted hover:text-ink')
                  }
                >
                  {m}
                </button>
              ))}
            </div>

            {mode === 'matches' ? (
              <>
                <div className="flex shrink-0 gap-1 border-b border-line px-2.5 py-2">
                  {FILTERS.map((f) => (
                    <button
                      key={f.id}
                      onClick={() => setFilter(f.id)}
                      className={
                        'rounded-full px-2.5 py-1 text-[11px] transition-colors ' +
                        (filter === f.id
                          ? 'bg-accent-deep text-[#f0fdf4]'
                          : 'text-muted hover:bg-accent-soft hover:text-accent-deep')
                      }
                    >
                      {f.label}
                    </button>
                  ))}
                </div>

                <div className="min-h-0 flex-1 overflow-y-auto">
                  {rows.length === 0 && (
                    <p className="px-3.5 py-6 text-[12px] leading-relaxed text-faint">
                      Nothing here. Matches appear once a reconciliation has run.
                    </p>
                  )}
                  {rows.map((p) => (
                    <button
                      key={p.id}
                      onClick={() => open(p.id)}
                      className="block w-full border-b border-line/70 px-3.5 py-2.5 text-left transition-colors hover:bg-accent-soft/50"
                    >
                      <div className="flex items-baseline gap-2">
                        <span className="truncate font-mono text-[11.5px] text-ink">
                          {p.group_key}
                        </span>
                        <span className="ml-auto shrink-0">
                          <Pill tone={CONFIDENCE_TONE[p.confidence] ?? 'neutral'}>
                            {p.confidence.replace(/_/g, ' ')}
                          </Pill>
                        </span>
                      </div>
                      <p className="mt-1 truncate font-mono text-[10.5px] text-faint">
                        {p.dataset_names.join(' · ')} · {p.member_count} rows
                      </p>
                    </button>
                  ))}
                </div>
              </>
            ) : (
              <div className="min-h-0 flex-1 overflow-y-auto">
                {view && (
                  <p className="border-b border-line px-3.5 py-2 text-[11px] text-faint">
                    from{' '}
                    <span className="font-mono text-muted">{view.spine.name}</span>
                    {view.spine.reason && (
                      <span className="text-faint"> · {view.spine.reason}</span>
                    )}
                  </p>
                )}
                {loading && (
                  <p className="flex items-center gap-2 px-3.5 py-4 text-[12px] text-faint">
                    <Spinner size={12} /> Building chains…
                  </p>
                )}
                {!loading && chains.length === 0 && (
                  <p className="px-3.5 py-6 text-[12px] leading-relaxed text-faint">
                    No transactions yet. Chains are assembled from accepted
                    matches once a reconciliation has run.
                  </p>
                )}
                {!loading &&
                  chains.map((tx) => (
                    <button
                      key={tx.key}
                      onClick={() => setOpenTx(tx)}
                      className="block w-full border-b border-line/70 px-3.5 py-2.5 text-left transition-colors hover:bg-accent-soft/50"
                    >
                      <div className="flex items-baseline gap-2">
                        <span className="truncate font-mono text-[11.5px] text-ink">
                          {tx.key}
                        </span>
                        <span className="ml-auto shrink-0">
                          <Pill tone={STATE_TONE[tx.state]}>{tx.state}</Pill>
                        </span>
                      </div>
                      <div className="mt-2">
                        <ChainStrip stages={view?.stages ?? []} hops={tx.hops} compact />
                      </div>
                      {tx.reason && (
                        <p className="mt-1.5 truncate text-[10.5px] text-warn">
                          {tx.reason}
                        </p>
                      )}
                    </button>
                  ))}
              </div>
            )}
          </>
        )}
      </aside>

      {openTx && (
        <ChainSheet
          tx={openTx}
          stages={view?.stages ?? []}
          onClose={() => setOpenTx(null)}
          onDecide={async (ids, status) => {
            const result = await actMany(ids, status)
            // The chain's state is derived from its legs, so it has to be
            // rebuilt before the list can show the new one.
            loadChains()
            return result
          }}
        />
      )}
    </>
  )
}
