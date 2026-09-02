/**
 * The right rail: one vertical tab per uploaded CSV.
 *
 * Collapsed it is a spine of file names; opened it is the table. The sources
 * are context rather than the work, so they sit to the side and stay shut until
 * asked for -- but they never leave the screen, because "which file did that
 * come from" is the question a reviewer asks most.
 */

import { useEffect, useState } from 'react'
import { getRows, type CsvRow, type Dataset } from '@/lib/api'
import { Icon, Spinner } from '@/components/ui'
import { useDatasets } from '@/state/DatasetsContext'

const PAGE = 50

function Table({ dataset }: { dataset: Dataset }) {
  const [rows, setRows] = useState<CsvRow[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let live = true
    setLoading(true)
    getRows(dataset.id, 0, PAGE)
      .then((page) => live && setRows(page.rows))
      .catch(() => live && setRows([]))
      .finally(() => live && setLoading(false))
    return () => {
      live = false
    }
  }, [dataset.id])

  if (loading) {
    return (
      <div className="flex items-center gap-2 px-4 py-6 text-[12px] text-faint">
        <Spinner size={12} />
        Loading rows…
      </div>
    )
  }
  if (!rows.length) {
    return <p className="px-4 py-6 text-[12px] text-faint">No rows.</p>
  }

  const cols = Object.keys(rows[0]).filter((c) => c !== '__row')

  return (
    <div className="min-h-0 flex-1 overflow-auto">
      <table className="w-full border-collapse text-left font-mono text-[11px]">
        <thead className="sticky top-0 z-10">
          <tr className="bg-sunk">
            {cols.map((c) => (
              <th
                key={c}
                className="border-b border-line px-2.5 py-2 font-medium whitespace-nowrap text-muted"
              >
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className="hover:bg-accent-soft/40">
              {cols.map((c) => (
                <td
                  key={c}
                  className="border-b border-line/60 px-2.5 py-1.5 whitespace-nowrap text-ink"
                >
                  {String(r[c] ?? '')}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      <p className="px-3 py-2 font-mono text-[10.5px] text-faint">
        first {rows.length} of {dataset.row_count.toLocaleString()} rows
      </p>
    </div>
  )
}

export default function SourceRail() {
  const { datasets, activeId, setActiveId } = useDatasets()
  const [open, setOpen] = useState(false)
  const active = datasets.find((d) => d.id === activeId) ?? null

  function toggle(id: string) {
    if (open && activeId === id) {
      setOpen(false)
      return
    }
    setActiveId(id)
    setOpen(true)
  }

  return (
    <aside className="flex min-h-0 shrink-0">
      {open && active && (
        <div className="panel mr-2 flex w-[min(52vw,640px)] min-h-0 flex-col overflow-hidden">
          <header className="flex shrink-0 items-center gap-2 border-b border-line px-4 py-2.5">
            <span className="text-accent">
              <Icon.sheet size={14} />
            </span>
            <span className="truncate text-[13px] font-medium text-ink">{active.name}</span>
            <span className="font-mono text-[11px] text-faint">
              {active.row_count.toLocaleString()} × {active.column_count}
            </span>
            <button
              onClick={() => setOpen(false)}
              className="ml-auto text-faint hover:text-ink"
              title="Collapse"
            >
              <Icon.close size={14} />
            </button>
          </header>
          <Table dataset={active} />
        </div>
      )}

      {/* the spine: vertical tabs, always visible */}
      <div className="panel flex w-11 shrink-0 flex-col items-center gap-1 py-3">
        {datasets.length === 0 && (
          <span className="text-faint" title="No sources">
            <Icon.sheet size={15} />
          </span>
        )}
        {datasets.map((d) => {
          const selected = open && d.id === activeId
          return (
            <button
              key={d.id}
              onClick={() => toggle(d.id)}
              title={`${d.name} — ${d.row_count.toLocaleString()} rows`}
              className={
                'flex flex-1 items-center justify-center rounded-lg py-3 transition-colors ' +
                (selected
                  ? 'bg-accent-deep text-[#f0fdf4]'
                  : 'text-muted hover:bg-accent-soft hover:text-accent-deep')
              }
            >
              <span
                className="text-[11px] font-medium tracking-[0.08em] whitespace-nowrap"
                style={{ writingMode: 'vertical-rl', transform: 'rotate(180deg)' }}
              >
                {d.name}
              </span>
            </button>
          )
        })}
      </div>
    </aside>
  )
}
