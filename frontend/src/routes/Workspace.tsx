/**
 * Three columns, one job each.
 *
 *   left    what has been settled and what is waiting on a person
 *   middle  the conversation, and the agent's work inside it
 *   right   the source files, on their edges until asked for
 *
 * The rails are context and the middle is the work, so the middle keeps the
 * width and both rails collapse toward their spines. The token meter sits in
 * the bottom-left corner where it is visible without ever being in the way.
 */

import { useState } from 'react'
import { useRouter } from '@/app/router'
import ChatPanel from '@/components/workspace/ChatPanel'
import ReconciledRail from '@/components/workspace/ReconciledRail'
import SourceRail from '@/components/workspace/SourceRail'
import TokenMeter from '@/components/workspace/TokenMeter'
import ProposalModal from '@/components/ProposalModal'
import { Icon, Logo } from '@/components/ui'
import { useChatState } from '@/state/ChatContext'
import { useDatasets } from '@/state/DatasetsContext'
import { useProposals } from '@/state/ProposalsContext'
import { resetSession } from '@/lib/api'

export default function Workspace() {
  const { go } = useRouter()
  const { datasets, refresh: refreshDatasets } = useDatasets()
  const { summary, refresh: refreshProposals } = useProposals()
  const { clearChat } = useChatState()
  const [expanded, setExpanded] = useState(false)
  const [resetting, setResetting] = useState(false)

  async function startOver() {
    if (!confirm('Delete every uploaded file, match and message?')) return
    setResetting(true)
    try {
      await resetSession()
      clearChat()
      // Both stores, not just the datasets. The reconciled rail reads the
      // proposals store, so refreshing only one leaves the scoreboard showing
      // matches for files that no longer exist.
      await Promise.all([refreshDatasets(), refreshProposals()])
      go('/upload')
    } finally {
      setResetting(false)
    }
  }

  return (
    <div className="flex h-full flex-col">
      <header className="flex shrink-0 items-center gap-4 px-4 py-3">
        <button onClick={() => go('/')} className="transition-opacity hover:opacity-70">
          <Logo size={18} />
        </button>

        <span className="font-mono text-[11px] text-faint">
          {datasets.length} source{datasets.length === 1 ? '' : 's'}
        </span>

        <div className="ml-auto flex items-center gap-2">
          {/* Only once there is something to report on -- an empty close report
              is a worse answer than no button. */}
          {(summary?.by_status.accepted ?? 0) > 0 && (
            <button onClick={() => go('/report')} className="btn btn-quiet">
              <Icon.report size={13} />
              Close report
            </button>
          )}
          <button onClick={() => go('/upload')} className="btn btn-quiet">
            <Icon.upload size={13} />
            Add source
          </button>
          <button onClick={startOver} disabled={resetting} className="btn btn-quiet">
            Start over
          </button>
        </div>
      </header>

      <div className="flex min-h-0 flex-1 gap-2 px-4 pb-4">
        <ReconciledRail expanded={expanded} onToggle={() => setExpanded((v) => !v)} />

        <main className="panel flex min-w-0 flex-1 flex-col overflow-hidden">
          <ChatPanel />
        </main>

        <SourceRail />
      </div>

      {/* bottom-left corner, over the rail */}
      <div className="pointer-events-none fixed bottom-4 left-4 z-40">
        <div className="pointer-events-auto">
          <TokenMeter />
        </div>
      </div>

      <ProposalModal />
    </div>
  )
}
