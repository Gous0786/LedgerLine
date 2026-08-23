import { useEffect, useState } from 'react'
import { TABS } from '@/tabs'
import { getJSON, type Health } from '@/lib/api'

export default function App() {
  const [active, setActive] = useState(TABS[0].id) // Sources
  const [health, setHealth] = useState<Health | null>(null)
  const [healthError, setHealthError] = useState<string | null>(null)

  useEffect(() => {
    getJSON<Health>('/health')
      .then(setHealth)
      .catch((e: Error) => setHealthError(e.message))
  }, [])

  const tab = TABS.find((t) => t.id === active) ?? TABS[0]

  return (
    <div className="flex h-full flex-col">
      <header className="flex items-center gap-6 border-b border-[--color-edge] px-6 py-3">
        <span className="font-medium tracking-tight">Reconciliation</span>

        <nav className="flex gap-1">
          {TABS.map((t) => (
            <button
              key={t.id}
              onClick={() => setActive(t.id)}
              className={
                'rounded px-3 py-1.5 text-sm transition-colors ' +
                (t.id === active
                  ? 'bg-[--color-panel] text-[--color-ink]'
                  : 'text-[--color-muted] hover:text-[--color-ink]')
              }
            >
              {t.label}
            </button>
          ))}
        </nav>

        <div className="ml-auto font-mono text-xs text-[--color-muted]">
          {healthError ? (
            <span className="text-red-400">backend unreachable</span>
          ) : health ? (
            <span>
              schema v{health.schema_version ?? '—'} ·{' '}
              <span className={health.openrouter_key_present ? '' : 'text-amber-400'}>
                openrouter {health.openrouter_key_present ? 'ok' : 'no key'}
              </span>
            </span>
          ) : (
            <span>connecting…</span>
          )}
        </div>
      </header>

      <main className="min-h-0 flex-1 overflow-hidden">{tab.render()}</main>
    </div>
  )
}
