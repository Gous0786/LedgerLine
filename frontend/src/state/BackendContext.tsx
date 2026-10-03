/**
 * Is the backend up yet?
 *
 * A free backend host puts the server to sleep when nobody uses it, and the
 * first request wakes it -- which can take most of a minute. So the moment the
 * app loads, before the visitor has read the home page, this starts pinging
 * /api/health and keeps at it until the server answers. Everything that loads
 * data waits for `ready` rather than failing during the wake-up.
 *
 * Locally the backend is already running and the first ping answers at once.
 */

import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { API_BASE } from '@/lib/api'

export type BackendStatus = 'waking' | 'ready'

interface BackendState {
  status: BackendStatus
  ready: boolean
  /** Seconds since the first ping, while waking. */
  waited: number
}

const Ctx = createContext<BackendState | null>(null)

// A sleeping host holds the first request open while it starts, so a ping is
// given long enough to be answered by the wake-up itself.
const PING_TIMEOUT_MS = 70_000
const RETRY_DELAY_MS = 3_000

async function ping(signal: AbortSignal): Promise<boolean> {
  // One controller for both reasons to give up -- the provider unmounting, or
  // this ping taking too long. (AbortSignal.any would do this, but is newer
  // than the browsers this app supports.)
  const ctl = new AbortController()
  const timer = setTimeout(() => ctl.abort(), PING_TIMEOUT_MS)
  const onStop = () => ctl.abort()
  signal.addEventListener('abort', onStop)
  try {
    const res = await fetch(`${API_BASE}/health`, { signal: ctl.signal, cache: 'no-store' })
    return res.ok
  } catch {
    return false
  } finally {
    clearTimeout(timer)
    signal.removeEventListener('abort', onStop)
  }
}

export function BackendProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<BackendStatus>('waking')
  const [waited, setWaited] = useState(0)

  useEffect(() => {
    const stop = new AbortController()
    const started = Date.now()
    const tick = setInterval(() => setWaited(Math.round((Date.now() - started) / 1000)), 1000)

    void (async () => {
      while (!stop.signal.aborted) {
        if (await ping(stop.signal)) {
          setStatus('ready')
          break
        }
        await new Promise((r) => setTimeout(r, RETRY_DELAY_MS))
      }
      clearInterval(tick)
    })()

    return () => {
      stop.abort()
      clearInterval(tick)
    }
  }, [])

  const value = useMemo(() => ({ status, ready: status === 'ready', waited }), [status, waited])
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export function useBackend(): BackendState {
  const v = useContext(Ctx)
  if (!v) throw new Error('useBackend outside BackendProvider')
  return v
}
