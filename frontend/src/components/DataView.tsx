import { useEffect, useState } from 'react'
import DataTable from '@/components/DataTable'
import { formatBytes, getRows, type RowsPage } from '@/lib/api'
import { useDatasets } from '@/state/DatasetsContext'

const PAGE_SIZE = 100

export default function DataView() {
  const { active, remove, busy } = useDatasets()
  const [page, setPage] = useState<RowsPage | null>(null)
  const [offset, setOffset] = useState(0)
  const [error, setError] = useState<string | null>(null)

  const activeId = active?.id ?? null

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
      .then((p) => !cancelled && setPage(p))
      .catch((e: Error) => !cancelled && setError(e.message))
    return () => {
      cancelled = true
    }
  }, [activeId, offset])

  if (!active) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-2 px-8 text-center">
        <div className="eyebrow">No source selected</div>
        <p className="max-w-sm text-[13px] text-faint">
          Upload a CSV from the bar above. Each file becomes its own tab.
        </p>
      </div>
    )
  }

  const total = page?.total ?? 0
  const pageEnd = Math.min(offset + PAGE_SIZE, total)

  return (
    <div className="flex h-full flex-col">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-b border-line px-4 py-2 font-mono text-[11px] text-faint">
        <span className="text-muted">{active.original_name}</span>
        <span>
          {active.row_count.toLocaleString()} × {active.column_count}
        </span>
        <span>{formatBytes(active.byte_size)}</span>
        <span>
          {active.delimiter === '\t' ? '\\t' : active.delimiter} · {active.encoding}
        </span>
        <button
          onClick={() => void remove(active.id)}
          disabled={busy}
          className="ml-auto text-faint transition-colors hover:text-bad disabled:opacity-40"
        >
          remove
        </button>
      </div>

      {error && (
        <div className="border-b border-bad/40 bg-bad/10 px-4 py-2 text-[12px] text-bad">
          {error}
        </div>
      )}

      <div className="min-h-0 flex-1">
        {page && <DataTable columns={page.columns} rows={page.rows} />}
      </div>

      {total > PAGE_SIZE && (
        <div className="flex items-center gap-3 border-t border-line px-4 py-2 font-mono text-[11px]">
          <button
            onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
            disabled={offset === 0}
            className="rounded border border-line px-2 py-1 transition-colors hover:border-accent disabled:opacity-30"
          >
            prev
          </button>
          <span className="text-faint">
            {(offset + 1).toLocaleString()}–{pageEnd.toLocaleString()} of{' '}
            {total.toLocaleString()}
          </span>
          <button
            onClick={() => setOffset(offset + PAGE_SIZE)}
            disabled={pageEnd >= total}
            className="rounded border border-line px-2 py-1 transition-colors hover:border-accent disabled:opacity-30"
          >
            next
          </button>
        </div>
      )}
    </div>
  )
}
