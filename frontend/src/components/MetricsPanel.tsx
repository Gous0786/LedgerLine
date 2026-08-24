import { useChatState } from '@/state/ChatContext'

function Stat({
  label,
  value,
  unit,
  tone = 'text-ink',
}: {
  label: string
  value: string
  unit?: string
  tone?: string
}) {
  return (
    <div className="border-b border-line px-4 py-3 last:border-b-0">
      <div className="eyebrow">{label}</div>
      <div className="mt-1 flex items-baseline gap-1">
        <span className={'font-mono text-lg tabular-nums ' + tone}>{value}</span>
        {unit && <span className="font-mono text-[10px] text-faint">{unit}</span>}
      </div>
    </div>
  )
}

function Bar({ label, value, total, tone }: { label: string; value: number; total: number; tone: string }) {
  const pct = total > 0 ? Math.round((value / total) * 100) : 0
  return (
    <div className="py-1">
      <div className="flex items-baseline justify-between">
        <span className="text-[11px] text-faint">{label}</span>
        <span className="font-mono text-[11px] text-muted tabular-nums">
          {value.toLocaleString()}
        </span>
      </div>
      <div className="mt-1 h-1 overflow-hidden rounded-full bg-line">
        <div className={'h-full rounded-full ' + tone} style={{ width: `${pct}%` }} />
      </div>
    </div>
  )
}

export default function MetricsPanel() {
  const { metrics } = useChatState()
  const { promptTokens, completionTokens, totalTokens, costUsd, elapsedMs, calls, lastModel } =
    metrics

  return (
    <aside className="glass flex h-full flex-col overflow-y-auto border-y-0 border-r-0">
      <Stat
        label="Cost"
        value={costUsd > 0 ? costUsd.toFixed(4) : '0.0000'}
        unit="USD"
        tone={costUsd > 0 ? 'text-ok' : 'text-faint'}
      />
      <Stat
        label="Tokens"
        value={totalTokens.toLocaleString()}
        tone={totalTokens > 0 ? 'text-ink' : 'text-faint'}
      />
      <Stat
        label="Time"
        value={elapsedMs >= 1000 ? (elapsedMs / 1000).toFixed(1) : String(elapsedMs)}
        unit={elapsedMs >= 1000 ? 's' : 'ms'}
        tone={elapsedMs > 0 ? 'text-ink' : 'text-faint'}
      />

      <div className="border-b border-line px-4 py-3">
        <div className="eyebrow mb-2">Breakdown</div>
        <Bar label="prompt" value={promptTokens} total={totalTokens} tone="bg-accent" />
        <Bar label="completion" value={completionTokens} total={totalTokens} tone="bg-violet" />
      </div>

      <div className="px-4 py-3">
        <div className="eyebrow mb-2">Calls</div>
        <div className="flex items-baseline justify-between py-1">
          <span className="text-[11px] text-faint">model calls</span>
          <span className="font-mono text-[11px] text-muted tabular-nums">{calls}</span>
        </div>
        <div className="flex items-baseline justify-between py-1">
          <span className="text-[11px] text-faint">model</span>
          <span className="truncate font-mono text-[11px] text-muted">
            {lastModel ?? '—'}
          </span>
        </div>
      </div>

      {calls === 0 && (
        <p className="px-4 pb-4 text-[11px] leading-relaxed text-faint">
          Populated from the stream&apos;s metrics parts. The agent isn&apos;t wired yet, so
          these stay at zero.
        </p>
      )}
    </aside>
  )
}
