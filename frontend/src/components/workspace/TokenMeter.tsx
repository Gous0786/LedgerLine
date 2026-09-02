/**
 * Tokens, bottom-left, and nothing else.
 *
 * The stream also carries cost, latency and per-model breakdowns. None of them
 * are on screen: a running total of what a question costs is the one number
 * that changes behaviour while you work, and the rest is a report to read
 * afterwards rather than a dial to watch.
 */

import { useChatState } from '@/state/ChatContext'

function compact(n: number): string {
  if (n < 1000) return String(n)
  if (n < 1_000_000) return `${(n / 1000).toFixed(n < 10_000 ? 1 : 0)}k`
  return `${(n / 1_000_000).toFixed(1)}M`
}

export default function TokenMeter() {
  const { metrics, busy } = useChatState()
  const total = metrics.promptTokens + metrics.completionTokens
  if (total === 0 && !busy) return null

  const cachedShare = total > 0 ? Math.round((metrics.cachedTokens / total) * 100) : 0

  return (
    <div
      className="panel-flat flex items-center gap-2.5 rounded-full px-3 py-1.5"
      title={
        `${metrics.promptTokens.toLocaleString()} in · ` +
        `${metrics.completionTokens.toLocaleString()} out · ` +
        `${metrics.cachedTokens.toLocaleString()} cached · ` +
        `${metrics.calls} model call${metrics.calls === 1 ? '' : 's'}`
      }
    >
      <span
        className={
          'size-1.5 rounded-full ' + (busy ? 'animate-pulse bg-accent' : 'bg-accent/40')
        }
      />
      <span className="font-mono text-[11.5px] text-ink">{compact(total)}</span>
      <span className="text-[10.5px] tracking-[0.1em] text-faint uppercase">tokens</span>
      {cachedShare > 0 && (
        <span className="font-mono text-[10.5px] text-accent">{cachedShare}% cached</span>
      )}
    </div>
  )
}
