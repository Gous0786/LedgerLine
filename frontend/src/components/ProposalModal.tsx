import { useEffect, useState } from 'react'
import {
  formatMinor,
  getProposal,
  type Confidence,
  type ProposalDetail,
  type ProposalStatus,
} from '@/lib/api'
import { useProposals } from '@/state/ProposalsContext'

export const CONFIDENCE_TONE: Record<Confidence, string> = {
  exact: 'text-ok border-ok/40 bg-ok/10',
  high: 'text-cyan border-cyan/40 bg-cyan/10',
  unbalanced: 'text-warn border-warn/40 bg-warn/10',
  ambiguous: 'text-bad border-bad/40 bg-bad/10',
}

const CONFIDENCE_WHY: Record<Confidence, string> = {
  exact: 'Unique match, amounts balance to zero, spans two sources.',
  high: 'Unique and cross-source, but there were no amounts to verify.',
  unbalanced: 'Matched on key, but the amounts disagree — usually a real break.',
  ambiguous: 'A row here could belong to more than one group.',
}

/** Renders one source row, highlighting the fields that carry the match. */
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
    <div className="rounded-lg border border-line bg-base/40 p-3">
      <div className="mb-2 flex items-baseline gap-2">
        <span className="font-mono text-[12px] text-accent">{member.dataset}</span>
        {member.role && (
          <span className="pill border-line text-[10px] text-muted">{member.role}</span>
        )}
        <span className="font-mono text-[10px] text-faint">row {member.row}</span>
        <span className="ml-auto font-mono text-[12px] tabular-nums">
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
                    (balanced ? 'text-ok' : 'text-warn')
                  }
                >
                  {formatMinor(detail.balance_minor)}
                </span>
                <span className="font-mono text-[10px] text-faint">
                  {balanced ? 'sums to zero' : 'does not balance'}
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
