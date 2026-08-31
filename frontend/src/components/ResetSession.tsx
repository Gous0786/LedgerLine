import { useEffect, useState } from 'react'
import { resetSession, type ResetResult } from '@/lib/api'
import { useChatState } from '@/state/ChatContext'
import { useDatasets } from '@/state/DatasetsContext'
import { useProposals } from '@/state/ProposalsContext'

/**
 * Wipes everything and starts over.
 *
 * Two-step rather than a browser confirm: this deletes uploaded files and every
 * match, and a single misplaced click should not be enough to do that. The
 * armed state reverts on its own so it cannot sit primed indefinitely.
 */
export default function ResetSession() {
  const [armed, setArmed] = useState(false)
  const [busy, setBusy] = useState(false)
  const [done, setDone] = useState<ResetResult | null>(null)
  const [error, setError] = useState<string | null>(null)

  const { clearChat } = useChatState()
  const { refresh: refreshDatasets } = useDatasets()
  const { refresh: refreshProposals } = useProposals()

  // Disarm after a few seconds so a forgotten click is not left loaded.
  useEffect(() => {
    if (!armed) return
    const t = setTimeout(() => setArmed(false), 4000)
    return () => clearTimeout(t)
  }, [armed])

  useEffect(() => {
    if (!done) return
    const t = setTimeout(() => setDone(null), 6000)
    return () => clearTimeout(t)
  }, [done])

  async function run() {
    setBusy(true)
    setError(null)
    try {
      const result = await resetSession()
      clearChat()
      await Promise.all([refreshDatasets(), refreshProposals()])
      setDone(result)
      setArmed(false)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  if (done) {
    return (
      <span className="font-mono text-[11px] text-ok">
        reset · {done.datasets} sources, {done.proposals} matches, {done.files_removed} files
      </span>
    )
  }

  if (error) {
    return (
      <button
        onClick={() => setError(null)}
        className="font-mono text-[11px] text-bad"
        title={error}
      >
        reset failed
      </button>
    )
  }

  if (!armed) {
    return (
      <button
        onClick={() => setArmed(true)}
        disabled={busy}
        title="Delete all uploaded data, matches and chat history"
        className="shrink-0 rounded-md border border-line px-2.5 py-1 text-[12px] text-faint transition-colors hover:border-bad/60 hover:text-bad disabled:opacity-40"
      >
        Reset
      </button>
    )
  }

  return (
    <span className="flex shrink-0 items-center gap-1.5">
      <span className="font-mono text-[11px] text-bad">delete everything?</span>
      <button
        onClick={() => void run()}
        disabled={busy}
        className="rounded-md bg-bad/20 px-2 py-1 text-[11px] text-bad transition-colors hover:bg-bad/30 disabled:opacity-40"
      >
        {busy ? 'resetting…' : 'yes, reset'}
      </button>
      <button
        onClick={() => setArmed(false)}
        className="rounded-md border border-line px-2 py-1 text-[11px] text-faint hover:text-ink"
      >
        cancel
      </button>
    </span>
  )
}
