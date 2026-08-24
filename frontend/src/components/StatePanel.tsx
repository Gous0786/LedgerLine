import { useEffect, useState } from 'react'
import { getJSON, formatBytes, type Health } from '@/lib/api'
import { useDatasets } from '@/state/DatasetsContext'
import { useChatState } from '@/state/ChatContext'

function Row({ label, value, tone = '' }: { label: string; value: string; tone?: string }) {
  return (
    <div className="flex items-baseline justify-between gap-3 py-1">
      <span className="text-[11px] text-faint">{label}</span>
      <span className={'truncate font-mono text-[11px] ' + (tone || 'text-muted')}>{value}</span>
    </div>
  )
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="border-b border-line px-4 py-3 last:border-b-0">
      <div className="eyebrow mb-2">{title}</div>
      {children}
    </div>
  )
}

export default function StatePanel() {
  const { datasets, active, failures, error } = useDatasets()
  const { status, busy } = useChatState()
  const [health, setHealth] = useState<Health | null>(null)
  const [healthError, setHealthError] = useState(false)

  useEffect(() => {
    getJSON<Health>('/health')
      .then(setHealth)
      .catch(() => setHealthError(true))
  }, [])

  const totalRows = datasets.reduce((n, d) => n + d.row_count, 0)
  const totalBytes = datasets.reduce((n, d) => n + d.byte_size, 0)

  return (
    <aside className="glass flex h-full flex-col overflow-y-auto border-y-0 border-l-0">
      <Section title="Run">
        <Row
          label="agent"
          value={busy ? status : 'idle'}
          tone={busy ? 'text-cyan' : 'text-faint'}
        />
        <Row label="stage" value="ingest" />
        <Row label="matching" value="not wired" tone="text-faint" />
      </Section>

      <Section title="Sources">
        <Row label="files" value={String(datasets.length)} />
        <Row label="rows" value={totalRows.toLocaleString()} />
        <Row label="size" value={formatBytes(totalBytes)} />
        {active && <Row label="active" value={active.name} tone="text-accent" />}
      </Section>

      {datasets.length > 0 && (
        <Section title="Loaded">
          <ul className="space-y-1">
            {datasets.map((d) => (
              <li key={d.id} className="flex items-baseline justify-between gap-2">
                <span
                  className={
                    'truncate text-[11px] ' + (d.id === active?.id ? 'text-ink' : 'text-muted')
                  }
                >
                  {d.name}
                </span>
                <span className="shrink-0 font-mono text-[10px] text-faint tabular-nums">
                  {d.row_count.toLocaleString()}×{d.column_count}
                </span>
              </li>
            ))}
          </ul>
        </Section>
      )}

      <Section title="Backend">
        {healthError ? (
          <Row label="api" value="unreachable" tone="text-bad" />
        ) : health ? (
          <>
            <Row label="schema" value={health.schema_version ?? '—'} />
            <Row
              label="openrouter"
              value={health.openrouter_key_present ? 'key set' : 'no key'}
              tone={health.openrouter_key_present ? 'text-ok' : 'text-warn'}
            />
            <Row label="model" value={health.models.orchestrator.split('/').pop() ?? '—'} />
          </>
        ) : (
          <Row label="api" value="connecting…" />
        )}
      </Section>

      {(error || failures.length > 0) && (
        <Section title="Notices">
          {error && <p className="text-[11px] text-bad">{error}</p>}
          {failures.map((f) => (
            <p key={f.file} className="text-[11px] text-warn">
              {f.file}: {f.error}
            </p>
          ))}
        </Section>
      )}
    </aside>
  )
}
