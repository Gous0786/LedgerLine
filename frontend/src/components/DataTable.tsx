import type { CsvRow, DatasetColumn } from '@/lib/api'

interface Props {
  columns: DatasetColumn[]
  rows: CsvRow[]
}

const NUMERIC = new Set(['INTEGER', 'REAL'])

/** Renders a page of CSV rows. The `__row` ordinal is shown as a line number
 *  rather than a data column — it is ours, not the file's. */
export default function DataTable({ columns, rows }: Props) {
  if (columns.length === 0) {
    return <div className="p-6 text-sm text-[--color-muted]">This file has no columns.</div>
  }

  return (
    <div className="h-full overflow-auto">
      <table className="w-full border-collapse text-sm">
        <thead className="sticky top-0 z-10">
          <tr>
            <th className="border-b border-[--color-edge] bg-[--color-panel] px-3 py-2 text-right font-mono text-xs font-normal text-[--color-muted]">
              #
            </th>
            {columns.map((c) => (
              <th
                key={c.ordinal}
                className="border-b border-[--color-edge] bg-[--color-panel] px-3 py-2 text-left font-normal whitespace-nowrap"
              >
                <div>{c.source_name || c.column_name}</div>
                <div className="font-mono text-[10px] tracking-wide text-[--color-muted] uppercase">
                  {c.inferred_type}
                </div>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={String(row.__row)} className="hover:bg-[--color-panel]/60">
              <td className="border-b border-[--color-edge]/50 px-3 py-1.5 text-right font-mono text-xs text-[--color-muted] tabular-nums">
                {row.__row}
              </td>
              {columns.map((c) => {
                const v = row[c.column_name]
                const numeric = NUMERIC.has(c.inferred_type)
                return (
                  <td
                    key={c.ordinal}
                    className={
                      'border-b border-[--color-edge]/50 px-3 py-1.5 whitespace-nowrap ' +
                      (numeric ? 'text-right font-mono tabular-nums ' : '') +
                      (v === null ? 'text-[--color-muted] italic' : '')
                    }
                  >
                    {v === null ? '∅' : String(v)}
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>

      {rows.length === 0 && (
        <div className="p-6 text-sm text-[--color-muted]">No rows on this page.</div>
      )}
    </div>
  )
}
