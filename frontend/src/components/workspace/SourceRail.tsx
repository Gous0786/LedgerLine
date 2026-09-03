/**
 * The right rail: one vertical tab per uploaded CSV.
 *
 * Collapsed it is a spine of file names; opened it is the table. The sources
 * are context rather than the work, so they sit to the side and stay shut until
 * asked for -- but they never leave the screen, because "which file did that
 * come from" is the question a reviewer asks most.
 */

import { useEffect, useState } from 'react'
import { getRows, setDuplicatePolicy, type CsvRow, type Dataset } from '@/lib/api'
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

  // The mark columns are shown as a badge on the row rather than as two more
  // columns of their own -- a reviewer scanning the file wants to see which
  // line is the repeat, not read two mostly-empty columns.
  const cols = Object.keys(rows[0]).filter(
    (c) => c !== '__row' && c !== '__duplicate_of' && c !== '__duplicate_kind',
  )
  const marked = rows.filter((r) => r.__duplicate_of != null).length

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
          {rows.map((r, i) => {
            const dup = r.__duplicate_of
            return (
              <tr
                key={i}
                className={
                  dup != null
                    ? 'bg-warn/[0.07] hover:bg-warn/[0.12]'
                    : 'hover:bg-accent-soft/40'
                }
                title={
                  dup != null
                    ? `Repeats row ${dup}${
                        r.__duplicate_kind === 'exact'
                          ? ' exactly'
                          : ' — same event, different id'
                      }`
                    : undefined
                }
              >
                {cols.map((c, k) => (
                  <td
                    key={c}
                    className="border-b border-line/60 px-2.5 py-1.5 whitespace-nowrap text-ink"
                  >
                    {k === 0 && dup != null && (
                      <span className="mr-1.5 rounded-sm border border-warn/40 bg-warn/10 px-1 text-[9.5px] text-warn">
                        dup of {String(dup)}
                      </span>
                    )}
                    {String(r[c] ?? '')}
                  </td>
                ))}
              </tr>
            )
          })}
        </tbody>
      </table>
      <p className="px-3 py-2 font-mono text-[10.5px] text-faint">
        first {rows.length} of {dataset.row_count.toLocaleString()} rows
        {marked > 0 && (
          <span className="text-warn">
            {' '}
            · {marked} repeated
            {dataset.exclude_duplicates ? ', set aside' : ', still counted'}
          </span>
        )}
      </p>
    </div>
  )
}

function DuplicatePolicy({ dataset }: { dataset: Dataset }) {
  const { refresh } = useDatasets()
  const [busy, setBusy] = useState(false)
  const repeated = dataset.duplicate_rows + dataset.near_duplicate_rows
  if (!repeated) return null

  const excluded = Boolean(dataset.exclude_duplicates)

  async function flip() {
    setBusy(true)
    try {
      await setDuplicatePolicy(dataset.id, !excluded)
      await refresh()
    } finally {
      setBusy(false)
    }
  }

  return (
    <button
      onClick={flip}
      disabled={busy}
      // The label says what the rows *are*, not what the switch does, because
      // that is the judgement being made: whether a repeat in this file is an
      // artefact of how it was exported or a second event that really happened.
      title={
        excluded
          ? 'These rows are treated as the same event recorded twice, and left out of matching. Click to count them again.'
          : 'These rows are counted, so a group holding one reads as a break. Click to treat them as the same event recorded twice.'
      }
      className={`rounded-full border px-2 py-0.5 text-[10.5px] transition-colors ${
        excluded
          ? 'border-accent/40 bg-accent-soft text-accent-deep'
          : 'border-warn/40 bg-warn/10 text-warn'
      } ${busy ? 'opacity-50' : 'hover:brightness-95'}`}
    >
      {repeated} repeated · {excluded ? 'set aside' : 'counted'}
    </button>
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
            <DuplicatePolicy dataset={active} />
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
