import { useEffect, useState } from 'react'
import {
  type ProposalDuplicates,
  formatMinor,
  getProposal,
  type Confidence,
  type ProposalDetail,
  type ProposalStatus,
} from '@/lib/api'
import { useProposals } from '@/state/ProposalsContext'

export const CONFIDENCE_TONE: Record<Confidence, string> = {
  exact: 'text-ok border-ok/40 bg-ok/10',
  within_tolerance: 'text-ok/80 border-ok/30 bg-ok/5',
  high: 'text-cyan border-cyan/40 bg-cyan/10',
  unbalanced: 'text-warn border-warn/40 bg-warn/10',
  ambiguous: 'text-bad border-bad/40 bg-bad/10',
}

const CONFIDENCE_WHY: Record<Confidence, string> = {
  exact: 'Unique match, amounts balance to zero, spans two sources.',
  within_tolerance:
    'Unique match. A residual remains but is inside the allowed tolerance — rounding, not a break.',
  high: 'Unique and cross-source, but there were no amounts to verify.',
  unbalanced: 'Matched on key, but the amounts disagree — usually a real break.',
  ambiguous: 'A row here could belong to more than one group.',
}

/** Renders one source row, highlighting the fields that carry the match. */
function DuplicateNote({ duplicates }: { duplicates: ProposalDuplicates }) {
  const { rows, amount_minor, balance_without_duplicates_minor, explains_residual } =
    duplicates
  const list = rows
    .map((r) => `${r.dataset} row ${r.row} repeats row ${r.duplicate_of}`)
    .join('; ')

  return (
    <div className="rounded-lg border border-warn/40 bg-warn/5 px-3 py-2.5">
      <div className="mb-1 flex items-baseline gap-2">
        <span className="pill border-warn/40 bg-warn/10 text-[10px] text-warn">
          duplicate rows
        </span>
        <span className="font-mono text-[11px] text-faint">
          {duplicates.members} of {rows.length === 1 ? 'this group' : 'these'} counted twice
        </span>
      </div>
      <p className="text-[12px] leading-relaxed text-muted">
        {list}. The source file records the same row twice, so its{' '}
        <span className="font-mono text-warn">{formatMinor(amount_minor)}</span> is in
        the total twice.{' '}
        {explains_residual ? (
          <>
            That is the entire difference — discount it and the group balances to{' '}
            <span className="font-mono text-ok">
              {formatMinor(balance_without_duplicates_minor)}
            </span>
            .
          </>
        ) : (
          <>
            Discounting it the group would still be off by{' '}
            <span className="font-mono text-warn">
              {formatMinor(balance_without_duplicates_minor)}
            </span>
            , so there is something else wrong here too.
          </>
        )}{' '}
        The amounts are left counted: the file and the counterparty genuinely
        disagree, and which one is right is your call.
      </p>
    </div>
  )
}

function MemberRow({
  member,
  groupKey,
}: {
  member: ProposalDetail['members'][number]
  groupKey: string
}) {
  const data = member.data ?? {}
  const entries = Object.entries(data).filter(([k]) => k !== '__row')

  return (
    <div
      className={
        'rounded-lg border bg-base/40 p-3 ' +
        (member.duplicate_of !== null ? 'border-warn/40' : 'border-line')
      }
    >
      <div className="mb-2 flex items-baseline gap-2">
        <span className="font-mono text-[12px] text-accent">{member.dataset}</span>
        {member.role && (
          <span className="pill border-line text-[10px] text-muted">{member.role}</span>
        )}
        <span className="font-mono text-[10px] text-faint">row {member.row}</span>
        {member.duplicate_of !== null && (
          <span className="pill border-warn/40 bg-warn/10 text-[10px] text-warn">
            duplicate of row {member.duplicate_of}
          </span>
        )}
        <span
          className={
            'ml-auto font-mono text-[12px] tabular-nums ' +
            (member.duplicate_of !== null ? 'text-warn' : '')
          }
        >
          {formatMinor(member.amount_minor)}
        </span>
      </div>
      <div className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5">
        {entries.map(([k, v]) => {
          const hit = String(v) === groupKey
          return (
            <div key={k} className="contents">
              <span className="font-mono text-[11px] text-faint">{k}</span>
              <span
                className={
                  'truncate font-mono text-[11px] ' +
                  (hit ? 'rounded bg-accent/20 px-1 text-ink' : 'text-muted')
                }
              >
                {v === null ? '∅' : String(v)}
              </span>
            </div>
          )
        })}
      </div>
    </div>
  )
}

export default function ProposalModal() {
  const { openId, close, act, busy } = useProposals()
  const [detail, setDetail] = useState<ProposalDetail | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (openId === null) {
      setDetail(null)
      return
    }
    let cancelled = false
    setDetail(null)
    setError(null)
    getProposal(openId)
      .then((d) => !cancelled && setDetail(d))
      .catch((e: Error) => !cancelled && setError(e.message))
    return () => {
      cancelled = true
    }
  }, [openId])

  useEffect(() => {
    if (openId === null) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') close()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [openId, close])

  if (openId === null) return null

  async function decide(status: ProposalStatus) {
    if (openId === null) return
    await act(openId, status)
    close()
  }

  const balanced = detail?.balance_minor === 0
  const absorbed =
    detail && detail.balance_minor !== null && detail.balance_minor !== 0 &&
    Math.abs(detail.balance_minor) <= (detail.tolerance_minor ?? 0)

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-6 backdrop-blur-sm"
      onClick={close}
    >
      <div
        className="glass flex max-h-[85vh] w-full max-w-3xl flex-col overflow-hidden rounded-xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* header */}
        <div className="flex shrink-0 items-center gap-3 border-b border-line px-5 py-3">
          <span className="font-mono text-[13px] text-ink">
            {detail?.group_key ?? `proposal ${openId}`}
          </span>
          {detail && (
            <span className={'pill border ' + CONFIDENCE_TONE[detail.confidence]}>
              {detail.confidence}
            </span>
          )}
          {detail && (
            <span className="font-mono text-[11px] text-faint">
              tier {detail.tier} · {detail.rule}
            </span>
          )}
          <button
            onClick={close}
            className="ml-auto text-[16px] leading-none text-faint hover:text-ink"
          >
            ×
          </button>
        </div>

        {/* body */}
        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
          {error && <p className="text-[13px] text-bad">{error}</p>}
          {!detail && !error && <p className="text-[13px] text-faint">Loading evidence…</p>}

          {detail && (
            <div className="space-y-4">
              <p className="text-[12px] text-muted">{CONFIDENCE_WHY[detail.confidence]}</p>

              {detail.duplicates && (
                <DuplicateNote duplicates={detail.duplicates} />
              )}

              <div>
                <div className="eyebrow mb-2">Evidence · {detail.members.length} rows</div>
                <div className="space-y-2">
                  {detail.members.map((m) => (
                    <MemberRow
                      key={`${m.dataset_id}:${m.row}`}
                      member={m}
                      groupKey={detail.group_key}
                    />
                  ))}
                </div>
              </div>

              <div className="flex items-baseline gap-2 rounded-lg border border-line px-3 py-2">
                <span className="eyebrow">Balance</span>
                <span
                  className={
                    'ml-auto font-mono text-[13px] tabular-nums ' +
                    (balanced ? 'text-ok' : absorbed ? 'text-ok/80' : 'text-warn')
                  }
                >
                  {formatMinor(detail.balance_minor)}
                </span>
                <span className="font-mono text-[10px] text-faint">
                  {balanced
                    ? 'sums to zero'
                    : absorbed
                      ? `residual within tolerance ${formatMinor(detail!.tolerance_minor)}`
                      : 'does not balance'}
                </span>
              </div>

              <div>
                <div className="eyebrow mb-2">History</div>
                <ol className="space-y-1">
                  {detail.events.map((e, i) => (
                    <li key={i} className="flex items-baseline gap-2 font-mono text-[11px]">
                      <span className="text-faint">{e.ts}</span>
                      <span className="text-ink">{e.kind}</span>
                      <span className="text-faint">by {e.actor}</span>
                    </li>
                  ))}
                </ol>
              </div>
            </div>
          )}
        </div>

        {/* actions */}
        <div className="flex shrink-0 items-center gap-2 border-t border-line px-5 py-3">
          <span className="font-mono text-[11px] text-faint">
            {detail?.status === 'accepted' ? 'already reconciled' : 'your decision'}
          </span>
          <button
            onClick={() => void decide('review_later')}
            disabled={busy}
            className="ml-auto rounded-md border border-line px-3 py-1.5 text-[12px] text-muted transition-colors hover:border-warn hover:text-warn disabled:opacity-40"
          >
            Review later
          </button>
          <button
            onClick={() => void decide('rejected')}
            disabled={busy}
            className="rounded-md border border-line px-3 py-1.5 text-[12px] text-muted transition-colors hover:border-bad hover:text-bad disabled:opacity-40"
          >
            Reject
          </button>
          <button
            onClick={() => void decide('accepted')}
            disabled={busy}
            className="rounded-md bg-ok/20 px-3 py-1.5 text-[12px] text-ok transition-colors hover:bg-ok/30 disabled:opacity-40"
          >
            Accept
          </button>
        </div>
      </div>
    </div>
  )
}
