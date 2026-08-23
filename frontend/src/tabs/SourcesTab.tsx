import { useCallback, useEffect, useRef, useState } from 'react'
import DataTable from '@/components/DataTable'
import {
  deleteDataset,
  formatBytes,
  getRows,
  listDatasets,
  uploadCsvs,
  type Dataset,
  type RowsPage,
} from '@/lib/api'

const PAGE_SIZE = 100

export default function SourcesTab() {
  const [datasets, setDatasets] = useState<Dataset[]>([])
  const [activeId, setActiveId] = useState<string | null>(null)
  const [page, setPage] = useState<RowsPage | null>(null)
  const [offset, setOffset] = useState(0)

  const [busy, setBusy] = useState(false)
  const [dragging, setDragging] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [failures, setFailures] = useState<{ file: string; error: string }[]>([])
  const fileInput = useRef<HTMLInputElement>(null)

  const refresh = useCallback(async (selectId?: string) => {
    const list = await listDatasets()
    setDatasets(list)
    setActiveId((current) => {
      if (selectId) return selectId
      if (current && list.some((d) => d.id === current)) return current
      return list.length > 0 ? list[0].id : null
    })
  }, [])

  useEffect(() => {
    refresh().catch((e: Error) => setError(e.message))
  }, [refresh])

  // Reset paging whenever the selected file changes.
  useEffect(() => {
    setOffset(0)
  }, [activeId])

  useEffect(() => {
    if (!activeId) {
      setPage(null)
      return
    }
    let cancelled = false
    getRows(activeId, offset, PAGE_SIZE)
      .then((p) => {
        if (!cancelled) setPage(p)
      })
      .catch((e: Error) => {
        if (!cancelled) setError(e.message)
      })
    return () => {
      cancelled = true
    }
  }, [activeId, offset])

  async function handleFiles(files: FileList | null) {
    if (!files || files.length === 0) return
    const csvs = Array.from(files)
    setBusy(true)
    setError(null)
    setFailures([])
    try {
      const result = await uploadCsvs(csvs)
      setFailures(result.failed)
      await refresh(result.created[0]?.id)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
      if (fileInput.current) fileInput.current.value = ''
    }
  }

  async function handleDelete(id: string) {
    setBusy(true)
    try {
      await deleteDataset(id)
      await refresh()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const active = datasets.find((d) => d.id === activeId) ?? null
  const total = page?.total ?? 0
  const pageEnd = Math.min(offset + PAGE_SIZE, total)

  return (
    <div className="flex h-full flex-col">
      {/* upload */}
      <div
        onDragOver={(e) => {
          e.preventDefault()
          setDragging(true)
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault()
          setDragging(false)
          void handleFiles(e.dataTransfer.files)
        }}
        className={
          'm-4 rounded border border-dashed px-4 py-5 text-center text-sm transition-colors ' +
          (dragging
            ? 'border-[--color-accent] bg-[--color-panel]'
            : 'border-[--color-edge] text-[--color-muted]')
        }
      >
        <input
          ref={fileInput}
          type="file"
          accept=".csv,text/csv"
          multiple
          className="hidden"
          onChange={(e) => void handleFiles(e.target.files)}
        />
        {busy ? (
          'Ingesting…'
        ) : (
          <>
            Drop CSV files here, or{' '}
            <button
              onClick={() => fileInput.current?.click()}
              className="text-[--color-accent] underline underline-offset-2"
            >
              browse
            </button>
            . Multiple files at once are fine — each becomes its own tab.
          </>
        )}
      </div>

      {error && (
        <p className="mx-4 mb-2 rounded border border-red-900 bg-red-950/40 p-2 text-sm text-red-300">
          {error}
        </p>
      )}
      {failures.length > 0 && (
        <ul className="mx-4 mb-2 rounded border border-amber-900 bg-amber-950/30 p-2 text-sm text-amber-300">
          {failures.map((f) => (
            <li key={f.file}>
              {f.file}: {f.error}
            </li>
          ))}
        </ul>
      )}

      {datasets.length === 0 ? (
        <div className="px-4 text-sm text-[--color-muted]">No files loaded yet.</div>
      ) : (
        <>
          {/* one tab per CSV */}
          <div className="flex flex-wrap gap-1 border-b border-[--color-edge] px-4">
            {datasets.map((d) => (
              <button
                key={d.id}
                onClick={() => setActiveId(d.id)}
                title={d.original_name ?? d.name}
                className={
                  '-mb-px rounded-t border-x border-t px-3 py-1.5 text-sm transition-colors ' +
                  (d.id === activeId
                    ? 'border-[--color-edge] bg-[--color-panel] text-[--color-ink]'
                    : 'border-transparent text-[--color-muted] hover:text-[--color-ink]')
                }
              >
                {d.name}
                <span className="ml-2 font-mono text-xs text-[--color-muted]">
                  {d.row_count.toLocaleString()}
                </span>
              </button>
            ))}
          </div>

          {/* active file */}
          {active && (
            <div className="flex items-center gap-4 px-4 py-2 font-mono text-xs text-[--color-muted]">
              <span>{active.original_name}</span>
              <span>
                {active.row_count.toLocaleString()} rows × {active.column_count} cols
              </span>
              <span>{formatBytes(active.byte_size)}</span>
              <span>
                delim {active.delimiter === '\t' ? '\\t' : active.delimiter} · {active.encoding}
              </span>
              <button
                onClick={() => void handleDelete(active.id)}
                disabled={busy}
                className="ml-auto text-[--color-muted] hover:text-red-400 disabled:opacity-50"
              >
                remove
              </button>
            </div>
          )}

          <div className="min-h-0 flex-1 border-t border-[--color-edge]">
            {page && <DataTable columns={page.columns} rows={page.rows} />}
          </div>

          {total > PAGE_SIZE && (
            <div className="flex items-center gap-3 border-t border-[--color-edge] px-4 py-2 font-mono text-xs">
              <button
                onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
                disabled={offset === 0}
                className="rounded border border-[--color-edge] px-2 py-1 disabled:opacity-40"
              >
                prev
              </button>
              <span className="text-[--color-muted]">
                {(offset + 1).toLocaleString()}–{pageEnd.toLocaleString()} of{' '}
                {total.toLocaleString()}
              </span>
              <button
                onClick={() => setOffset(offset + PAGE_SIZE)}
                disabled={pageEnd >= total}
                className="rounded border border-[--color-edge] px-2 py-1 disabled:opacity-40"
              >
                next
              </button>
            </div>
          )}
        </>
      )}
    </div>
  )
}
