import { useEffect, useRef, useState } from 'react'
import TopBar from '@/components/TopBar'
import StatePanel from '@/components/StatePanel'
import MetricsPanel from '@/components/MetricsPanel'
import ActivityStream from '@/components/ActivityStream'
import DataView from '@/components/DataView'
import ChatBar from '@/components/ChatBar'
import { ChatProvider, useChatState } from '@/state/ChatContext'
import { DatasetsProvider } from '@/state/DatasetsContext'

type Mode = 'activity' | 'data'

const MODES: { id: Mode; label: string }[] = [
  { id: 'activity', label: 'Activity' },
  { id: 'data', label: 'Data' },
]

function Workspace() {
  const [mode, setMode] = useState<Mode>('data')
  const { busy } = useChatState()
  const wasBusy = useRef(false)

  // Follow the work: when the agent starts, surface what it is doing. Only on
  // the idle→busy edge, so a manual switch back to Data isn't yanked away.
  useEffect(() => {
    if (busy && !wasBusy.current) setMode('activity')
    wasBusy.current = busy
  }, [busy])

  return (
    <section className="glass flex min-w-0 flex-col overflow-hidden rounded-lg">
      <div className="flex shrink-0 items-center gap-1 border-b border-line px-3 py-1.5">
        {MODES.map((m) => (
          <button
            key={m.id}
            onClick={() => setMode(m.id)}
            className={
              'rounded px-2.5 py-1 text-[12px] transition-colors ' +
              (mode === m.id ? 'bg-accent/15 text-ink' : 'text-faint hover:text-muted')
            }
          >
            {m.label}
          </button>
        ))}
      </div>

      <div className="min-h-0 flex-1">
        {mode === 'activity' ? <ActivityStream /> : <DataView />}
      </div>
    </section>
  )
}

export default function App() {
  return (
    <DatasetsProvider>
      <ChatProvider>
        <div className="flex h-full flex-col">
          <TopBar />

          <div className="grid min-h-0 flex-1 grid-cols-[15rem_minmax(0,1fr)_13rem] gap-3 p-3">
            <StatePanel />
            <Workspace />
            <MetricsPanel />
          </div>

          <ChatBar />
        </div>
      </ChatProvider>
    </DatasetsProvider>
  )
}
