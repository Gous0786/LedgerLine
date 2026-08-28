import { formatMinor, type Proposal } from '@/lib/api'
import { useProposals } from '@/state/ProposalsContext'
import { CONFIDENCE_TONE } from '@/components/ProposalModal'

const STATUS_TONE: Record<string, string> = {
  accepted: 'text-ok',
  rejected: 'text-bad',
  review_later: 'text-warn',
  pending: 'text-muted',
}

/** One clickable proposal row. Clicking opens the evidence modal. */
export function ProposalRow({ p, showStatus = false }: { p: Proposal; showStatus?: boolean }) {
  const { open } = useProposals()
  return (
    <button
      onClick={() => open(p.id)}
      className="flex w-full items-center gap-2 rounded-md border border-line bg-base/30 px-2.5 py-1.5 text-left transition-colors hover:border-accent/50"
    >
      <span className={'pill border ' + CONFIDENCE_TONE[p.confidence]}>{p.confidence}</span>
      <span className="truncate font-mono text-[12px] text-ink">{p.group_key}</span>
      <span className="shrink-0 font-mono text-[10px] text-faint">
        {p.member_count} rows · {p.dataset_names.join(' ↔ ')}
      </span>
      <span className="ml-auto shrink-0 font-mono text-[11px] tabular-nums text-muted">
        {formatMinor(p.balance_minor)}
      </span>
      {showStatus && (
        <span className={'shrink-0 font-mono text-[10px] ' + (STATUS_TONE[p.status] ?? '')}>
          {p.status}
        </span>
      )}
    </button>
  )
}

/**
 * Rendered in place of the raw tool output when the agent calls
 * propose_matches -- the counts it returned, plus the proposals themselves so
 * they can be reviewed without leaving the trace.
 */
export function ProposeMatchesResult({ output }: { output: unknown }) {
  const { proposals } = useProposals()
  const o = (output ?? {}) as Record<string, unknown>

  if (o.error) {
    return (
      <div className="mt-1.5 rounded border border-bad/40 bg-bad/10 px-2.5 py-1.5 font-mono text-[11px] text-bad">
        {String(o.error)}
      </div>
    )
  }

  const rule = String(o.rule ?? '')
  const proposed = Number(o.proposed ?? 0)
  const auto = Number(o.auto_accepted ?? 0)
  const pending = Number(o.pending ?? 0)
  const skipped = Number(o.skipped_already_matched ?? 0)

  // Show the proposals this call created, newest first.
  const mine = proposals.filter((p) => p.rule === rule).slice(0, 12)

  return (
    <div className="mt-1.5 space-y-1.5">
      <div className="flex flex-wrap items-center gap-2 font-mono text-[11px]">
        <span className="text-muted">{proposed} proposed</span>
        {auto > 0 && <span className="text-ok">{auto} auto-accepted</span>}
        {pending > 0 && <span className="text-warn">{pending} need review</span>}
        {skipped > 0 && <span className="text-faint">{skipped} already matched</span>}
        {proposed === 0 && <span className="text-faint">no new groups</span>}
      </div>
      {mine.length > 0 && (
        <div className="space-y-1">
          {mine.map((p) => (
            <ProposalRow key={p.id} p={p} showStatus />
          ))}
        </div>
      )}
    </div>
  )
}

/** Standing queue of anything awaiting a decision, shown above the composer. */
export function PendingBanner() {
  const { pending, open } = useProposals()
  if (pending.length === 0) return null
  return (
    <button
      onClick={() => open(pending[0].id)}
      className="flex w-full items-center gap-2 rounded-md border border-warn/40 bg-warn/10 px-3 py-1.5 text-left transition-colors hover:bg-warn/15"
    >
      <span className="font-mono text-[11px] text-warn">
        {pending.length} match{pending.length === 1 ? '' : 'es'} need your decision
      </span>
      <span className="ml-auto font-mono text-[10px] text-faint">review →</span>
    </button>
  )
}
