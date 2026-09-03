/**
 * A router in fifty lines, because three screens do not justify a dependency.
 *
 * Real URLs rather than a state machine: the workspace is worth reloading into
 * and worth linking to, and the browser back button should mean what it looks
 * like it means.
 */

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'

export type Route = '/' | '/upload' | '/workspace' | '/report'

const ROUTES: Route[] = ['/', '/upload', '/workspace', '/report']

function currentPath(): Route {
  const path = window.location.pathname as Route
  return ROUTES.includes(path) ? path : '/'
}

interface RouterValue {
  route: Route
  go: (to: Route) => void
}

const Ctx = createContext<RouterValue | null>(null)

export function RouterProvider({ children }: { children: React.ReactNode }) {
  const [route, setRoute] = useState<Route>(currentPath)

  useEffect(() => {
    const onPop = () => setRoute(currentPath())
    window.addEventListener('popstate', onPop)
    return () => window.removeEventListener('popstate', onPop)
  }, [])

  const go = useCallback((to: Route) => {
    if (to === window.location.pathname) return
    window.history.pushState({}, '', to)
    setRoute(to)
    // A new screen starts at the top; carrying scroll across a route change
    // makes the transition feel like a jump.
    window.scrollTo({ top: 0 })
  }, [])

  const value = useMemo(() => ({ route, go }), [route, go])
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export function useRouter(): RouterValue {
  const ctx = useContext(Ctx)
  if (!ctx) throw new Error('useRouter must be used inside <RouterProvider>')
  return ctx
}
