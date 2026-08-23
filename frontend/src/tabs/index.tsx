import ChatPanel from '@/components/ChatPanel'
import Placeholder from '@/components/Placeholder'

export interface TabDef {
  id: string
  label: string
  render: () => React.ReactNode
}

export const TABS: TabDef[] = [
  {
    id: 'sources',
    label: 'Sources',
    render: () => (
      <Placeholder title="Sources">
        <p>
          Upload CSVs. Each file is sniffed, typed and written to its own SQLite table, so no
          fixed reconciliation schema is imposed — sources can be joined in whatever direction
          a given transaction flow requires.
        </p>
        <p>Backed by GET /api/datasets.</p>
      </Placeholder>
    ),
  },
  {
    id: 'console',
    label: 'Console',
    render: () => <ChatPanel />,
  },
  {
    id: 'matches',
    label: 'Matches',
    render: () => (
      <Placeholder title="Matches">
        <p>
          Virtualised grid of matched groups, expandable to the underlying rows from each
          source with a side-by-side field diff.
        </p>
      </Placeholder>
    ),
  },
  {
    id: 'breaks',
    label: 'Breaks',
    render: () => (
      <Placeholder title="Breaks">
        <p>
          The exception queue: everything that did not reconcile, classified, with the
          evidence behind each call and the agent&apos;s proposed resolution.
        </p>
      </Placeholder>
    ),
  },
  {
    id: 'activity',
    label: 'Activity',
    render: () => (
      <Placeholder title="Activity">
        <p>
          Live feed of agent status, reasoning and tool calls. The stream already carries
          this: <code className="font-mono">data-activity</code> parts for agent state, plus
          native <code className="font-mono">reasoning-*</code> and{' '}
          <code className="font-mono">tool-*</code> chunks.
        </p>
        <p>
          Every chunk is persisted to <code className="font-mono">run_event</code> before it
          goes out, so this replays after a reload via GET /api/runs/&#123;id&#125;/events.
        </p>
      </Placeholder>
    ),
  },
  {
    id: 'metrics',
    label: 'Metrics',
    render: () => (
      <Placeholder title="Metrics">
        <p>
          Cost, tokens and time — live off transient{' '}
          <code className="font-mono">data-metrics</code> parts during a run, and aggregated
          from <code className="font-mono">run_metric</code> via GET
          /api/metrics/runs/&#123;id&#125;.
        </p>
      </Placeholder>
    ),
  },
]
