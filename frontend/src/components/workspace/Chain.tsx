/**
 * A transaction as the path it took: order to processor to bank.
 *
 * A match is one edge. A transaction is the whole chain, and the useful
 * question about it is never "which rules ran" but *where it broke* -- so the
 * chain is drawn as stages with the gaps between them coloured, and the first
 * gap that is not clean is the answer.
 *
 * Two renderings of the same data. `ChainStrip` is a glance, small enough to
 * sit in a list; `ChainSheet` is the reading, with the rows at each stage.
 */

import { useEffect, useState } from 'react'
import {
  formatMinor,
  getProposal,
  type BatchStatusResult,
  type HopState,
  type ProposalDetail,
  type ProposalStatus,
  type Transaction,
  type TxState,
} from '@/lib/api'
import { Icon, Pill, Spinner, type Tone } from '@/components/ui'

export const STATE_TONE: Record<TxState, Tone> = {
  reconciled: 'ok',
  pending: 'info',
  exception: 'warn',
  incomplete: 'warn',
  unmatched: 'neutral',
}

/** Colour of the *link*, not the stage: what matters is the gap. */
const HOP_COLOUR: Record<HopState, string> = {
  matched: 'bg-accent',
  tolerance: 'bg-info',
  unchecked: 'bg-line-strong',
  ambiguous: 'bg-warn',
  off: 'bg-warn',
  missing: 'bg-bad/40',
}

const HOP_WORDS: Record<HopState, string> = {
  matched: 'ties exactly',
  tolerance: 'ties within tolerance',
  unchecked: 'linked, no amount to check',
  ambiguous: 'more than one candidate',
  off: 'amounts disagree',
  missing: 'nothing matches',
}

/** Stages as nodes, hops as the links between them. */
export function ChainStrip({
  stages,
  hops,
  compact = false,
}: {
  stages: string[]
  hops: Transaction['hops']
  compact?: boolean
}) {
  if (stages.length === 0) return null
  const dot = compact ? 'size-1.5' : 'size-2.5'
  const bar = compact ? 'h-[2px]' : 'h-[3px]'

  return (
    <div className="flex items-center gap-1">
      {stages.map((stage, i) => {
        const hop = hops[i] // the link *after* this stage
        return (
          <div key={stage} className="flex flex-1 items-center gap-1 last:flex-none">
            <span
              className={`${dot} shrink-0 rounded-full bg-accent-deep`}
              title={stage}
            />
            {hop && (
              <span
                className={`${bar} min-w-3 flex-1 rounded-full ${HOP_COLOUR[hop.state]}`}
                title={`${hop.from} → ${hop.to}: ${HOP_WORDS[hop.state]}`}
              />
            )}
          </div>
        )
      })}
    </div>
  )
}

function Row({ label, value }: { label: string; value: unknown }) {
  return (
    <div className="contents">
      <span className="font-mono text-[11px] text-faint">{label}</span>
      <span className="truncate font-mono text-[11px] text-ink">{String(value ?? '')}</span>
    </div>
  )
}

/** The rows behind one leg, fetched only when the leg is opened. */
function LegRows({ proposalId }: { proposalId: number }) {
  const [detail, setDetail] = useState<ProposalDetail | null>(null)

  useEffect(() => {
    let live = true
    getProposal(proposalId)
      .then((d) => live && setDetail(d))
      .catch(() => live && setDetail(null))
    return () => {
      live = false
    }
  }, [proposalId])

  if (!detail) {
    return (
      <p className="flex items-center gap-2 py-2 text-[12px] text-faint">
        <Spinner size={12} /> Loading rows…
      </p>
    )
  }

  return (
    <div className="space-y-2 py-2">
      {detail.members.map((m) => (
        <div key={`${m.dataset_id}-${m.row}`} className="rounded-lg border border-line bg-white/60 p-2.5">
          <div className="mb-1.5 flex items-baseline gap-2">
            <span className="font-mono text-[11.5px] text-accent">{m.dataset}</span>
            <span className="font-mono text-[10.5px] text-faint">row {m.row}</span>
            {m.duplicate_of !== null && (
              <Pill tone="warn">duplicate of row {m.duplicate_of}</Pill>
            )}
            <span className="ml-auto font-mono text-[11.5px] tabular-nums">
              {formatMinor(m.amount_minor)}
            </span>
          </div>
          <div className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5">
            {Object.entries(m.data ?? {})
              .filter(([k]) => k !== '__row')
              .slice(0, 8)
              .map(([k, v]) => (
                <Row key={k} label={k} value={v} />
              ))}
          </div>
        </div>
      ))}
    </div>
  )
}

export function ChainSheet({
  tx,
  stages,
  onClose,
  onDecide,
}: {
  tx: Transaction
  stages: string[]
  onClose: () => void
  onDecide: (ids: number[], status: ProposalStatus) => Promise<BatchStatusResult>
}) {
  const [openLeg, setOpenLeg] = useState<number | null>(null)
  const [deciding, setDeciding] = useState(false)
  const [outcome, setOutcome] = useState<BatchStatusResult | null>(null)

  // Every leg, not only the undecided ones: a chain is one judgement, and
  // "accept this transaction" should mean the same thing whichever legs a
  // previous pass happened to settle.
  const legIds = tx.legs.map((l) => l.proposal_id)

  async function decide(status: ProposalStatus) {
    if (!legIds.length) return
    setDeciding(true)
    try {
      setOutcome(await onDecide(legIds, status))
    } finally {
      setDeciding(false)
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-accent-deep/25 p-6 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="panel flex max-h-[85vh] w-full max-w-3xl flex-col overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="flex shrink-0 items-center gap-3 border-b border-line px-5 py-3">
          <span className="font-mono text-[13px] text-ink">{tx.key}</span>
          <Pill tone={STATE_TONE[tx.state]}>{tx.state}</Pill>
          <span className="font-mono text-[11px] text-faint">
            {tx.leg_count}/{tx.expected_legs} legs
          </span>
          <button onClick={onClose} className="ml-auto text-faint hover:text-ink">
            <Icon.close size={16} />
          </button>
        </header>

        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
          {tx.reason && (
            <p className="mb-4 rounded-lg border border-warn/30 bg-warn/5 px-3 py-2 text-[12.5px] text-ink">
              {tx.reason}
            </p>
          )}

          {/* the chain itself */}
          <div className="mb-5">
            <ChainStrip stages={stages} hops={tx.hops} />
            <div className="mt-2 flex items-start gap-1">
              {stages.map((stage, i) => (
                <div key={stage} className="flex-1 last:flex-none">
                  <p className="truncate font-mono text-[10.5px] text-muted">{stage}</p>
                  {tx.hops[i] && (
                    <p className="mt-0.5 text-[10.5px] text-faint">
                      {HOP_WORDS[tx.hops[i].state]}
                      {tx.hops[i].balance_minor ? (
                        <span className="text-warn">
                          {' '}
                          · {formatMinor(tx.hops[i].balance_minor)}
                        </span>
                      ) : null}
                      {tx.hops[i].is_batch && (
                        <span className="text-faint">
                          {' '}
                          · batch of {tx.hops[i].batch_size}
                        </span>
                      )}
                    </p>
                  )}
                </div>
              ))}
            </div>
          </div>

          {/* the source row this chain hangs off */}
          <p className="eyebrow mb-1.5">Origin</p>
          <div className="mb-5 grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 rounded-lg border border-line bg-white/60 p-3">
            {Object.entries(tx.data ?? {})
              .filter(([k]) => k !== '__row')
              .map(([k, v]) => (
                <Row key={k} label={k} value={v} />
              ))}
          </div>

          {/* every match this transaction participates in */}
          <p className="eyebrow mb-1.5">Legs</p>
          <div className="space-y-1.5">
            {tx.legs.length === 0 && (
              <p className="text-[12px] text-faint">
                Nothing matched this transaction at all.
              </p>
            )}
            {tx.legs.map((leg) => (
              <div key={leg.proposal_id} className="rounded-lg border border-line">
                <button
                  onClick={() =>
                    setOpenLeg(openLeg === leg.proposal_id ? null : leg.proposal_id)
                  }
                  className="flex w-full items-center gap-2 px-3 py-2 text-left"
                >
                  <Pill tone={leg.confidence === 'exact' ? 'ok' : 'warn'}>
                    {leg.confidence.replace(/_/g, ' ')}
                  </Pill>
                  <span className="truncate font-mono text-[11px] text-muted">
                    {leg.members.map((m) => m.dataset).join(' ↔ ')}
                  </span>
                  {leg.is_batch && <Pill tone="info">batch of {leg.batch_size}</Pill>}
                  <span className="ml-auto shrink-0 font-mono text-[11px] text-faint">
                    {leg.status}
                  </span>
                  <span
                    className={
                      'shrink-0 text-faint transition-transform ' +
                      (openLeg === leg.proposal_id ? 'rotate-90' : '')
                    }
                  >
                    <Icon.chevron size={13} />
                  </span>
                </button>
                {openLeg === leg.proposal_id && (
                  <div className="border-t border-line px-3">
                    <LegRows proposalId={leg.proposal_id} />
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>

        <footer className="shrink-0 border-t border-line px-5 py-3">
          {outcome && (
            <div
              className={
                'mb-2.5 rounded-lg border px-3 py-2 text-[12px] ' +
                (outcome.blocked
                  ? 'border-warn/35 bg-warn/5 text-ink'
                  : 'border-ok/30 bg-ok/5 text-ink')
              }
            >
              <p>
                {outcome.changed} leg{outcome.changed === 1 ? '' : 's'} updated
                {outcome.blocked > 0 && `, ${outcome.blocked} held back`}.
              </p>
              {/* Naming the leg that failed, because "1 held back" is not
                  actionable and the reviewer is standing right here. */}
              {outcome.results
                .filter((r) => r.blocked || r.error)
                .slice(0, 3)
                .map((r) => (
                  <p key={r.proposal_id} className="mt-1 text-[11.5px] text-warn">
                    {r.error ?? r.failures?.[0]}
                  </p>
                ))}
            </div>
          )}

          <div className="flex items-center gap-2">
            <span className="text-[11.5px] text-faint">
              {legIds.length
                ? `decide all ${legIds.length} leg${legIds.length === 1 ? '' : 's'}`
                : 'nothing to decide'}
            </span>
            <button
              onClick={() => decide('review_later')}
              disabled={deciding || !legIds.length}
              className="btn btn-ghost ml-auto"
            >
              Review later
            </button>
            <button
              onClick={() => decide('rejected')}
              disabled={deciding || !legIds.length}
              className="btn btn-ghost"
            >
              Reject chain
            </button>
            <button
              onClick={() => decide('accepted')}
              disabled={deciding || !legIds.length}
              className="btn btn-primary"
            >
              {deciding ? <Spinner size={13} /> : <Icon.check size={14} />}
              Accept chain
            </button>
          </div>
        </footer>
      </div>
    </div>
  )
}
