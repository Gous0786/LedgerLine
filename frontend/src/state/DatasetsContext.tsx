/** Uploaded CSVs, shared between the top tab strip and the data workspace. */

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { useBackend } from '@/state/BackendContext'
import {
  deleteDataset,
  listDatasets,
  uploadCsvs,
  type Dataset,
} from '@/lib/api'

interface DatasetsContextValue {
  datasets: Dataset[]
  active: Dataset | null
  activeId: string | null
  setActiveId: (id: string) => void
  busy: boolean
  error: string | null
  failures: { file: string; error: string }[]
  clearNotices: () => void
  upload: (files: FileList | File[]) => Promise<void>
  remove: (id: string) => Promise<void>
  refresh: () => Promise<void>
}

const Ctx = createContext<DatasetsContextValue | null>(null)

export function DatasetsProvider({ children }: { children: React.ReactNode }) {
  const [datasets, setDatasets] = useState<Dataset[]>([])
  const [activeId, setActiveId] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [failures, setFailures] = useState<{ file: string; error: string }[]>([])

  const load = useCallback(async (selectId?: string) => {
    const list = await listDatasets()
    setDatasets(list)
    setActiveId((current) => {
      if (selectId) return selectId
      if (current && list.some((d) => d.id === current)) return current
      return list.length > 0 ? list[0].id : null
    })
  }, [])

  const refresh = useCallback(async () => {
    try {
      await load()
    } catch (e) {
      setError((e as Error).message)
    }
  }, [load])

  // Wait for the backend: on a sleeping host the first request is the wake-up,
  // and loading before then would only show an error.
  const { ready } = useBackend()
  useEffect(() => {
    if (ready) void refresh()
  }, [ready, refresh])

  const upload = useCallback(
    async (files: FileList | File[]) => {
      const list = Array.from(files)
      if (list.length === 0) return
      setBusy(true)
      setError(null)
      setFailures([])
      try {
        const result = await uploadCsvs(list)
        setFailures(result.failed)
        await load(result.created[0]?.id)
      } catch (e) {
        setError((e as Error).message)
      } finally {
        setBusy(false)
      }
    },
    [load],
  )

  const remove = useCallback(
    async (id: string) => {
      setBusy(true)
      try {
        await deleteDataset(id)
        await load()
      } catch (e) {
        setError((e as Error).message)
      } finally {
        setBusy(false)
      }
    },
    [load],
  )

  const clearNotices = useCallback(() => {
    setError(null)
    setFailures([])
  }, [])

  const active = datasets.find((d) => d.id === activeId) ?? null

  const value = useMemo<DatasetsContextValue>(
    () => ({
      datasets,
      active,
      activeId,
      setActiveId,
      busy,
      error,
      failures,
      clearNotices,
      upload,
      remove,
      refresh,
    }),
    [datasets, active, activeId, busy, error, failures, clearNotices, upload, remove, refresh],
  )

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export function useDatasets(): DatasetsContextValue {
  const ctx = useContext(Ctx)
  if (!ctx) throw new Error('useDatasets must be used inside <DatasetsProvider>')
  return ctx
}
