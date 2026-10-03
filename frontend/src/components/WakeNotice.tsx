/**
 * Shown while the backend is waking up, on every screen.
 *
 * Hidden for the first two seconds so a backend that is already awake (and
 * local development) never flashes it.
 */

import { Spinner } from '@/components/ui'
import { useBackend } from '@/state/BackendContext'

export default function WakeNotice() {
  const { ready, waited } = useBackend()
  if (ready || waited < 2) return null

  return (
    <div
      role="status"
      className="fixed bottom-5 left-1/2 z-50 flex max-w-[calc(100%-2rem)] -translate-x-1/2 items-center gap-3 rounded-full border border-line bg-base px-4 py-2.5 text-[12.5px] text-muted shadow-lg"
    >
      <span className="text-accent">
        <Spinner size={14} />
      </span>
      <span>
        Starting the demo server. It sleeps when idle, so this can take up to a
        minute{waited >= 5 ? ` (${waited}s)` : ''}.
      </span>
    </div>
  )
}
