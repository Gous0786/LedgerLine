import type { CsvRow, DatasetColumn } from '@/lib/api'

interface Props {
  columns: DatasetColumn[]
  rows: CsvRow[]
}

const NUMERIC = new Set(['INTEGER', 'REAL'])

const TYPE_TONE: Record<string, string> = {
  INTEGER: 'text-cyan',
  REAL: 'text-cyan',
  DATE: 'text-violet',
  TIMESTAMP: 'text-violet',
  TEXT: 'text-faint',
}

/** A page of CSV rows. `__row` is our ordinal, shown as a line number rather
 *  than a data column. */
export default function DataTable({ columns, rows }: Props) {
  if (columns.length === 0) {
    return <div className="p-6 text-sm text-faint">This file has no columns.</div>
  }

  return (
    <div className="h-full overflow-auto">
      <table className="w-full border-collapse text-[13px]">
        <thead className="sticky top-0 z-10">
          <tr>
            <th className="glass-soft border-b border-line px-3 py-2 text-right font-mono text-[10px] font-normal text-faint">
              #
            </th>
            {columns.map((c) => (
              <th
                key={c.ordinal}
                className="glass-soft border-b border-line px-3 py-2 text-left font-normal whitespace-nowrap"
              >
                <div className="text-ink">{c.source_name || c.column_name}</div>
                <div
                  className={
                    'font-mono text-[10px] tracking-wider ' +
                    (TYPE_TONE[c.inferred_type] ?? 'text-faint')
                  }
                >
                  {c.inferred_type}
                </div>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={String(row.__row)} className="hover:bg-accent/5">
              <td className="border-b border-line/40 px-3 py-1.5 text-right font-mono text-[11px] text-faint tabular-nums">
                {row.__row}
              </td>
              {columns.map((c) => {
                const v = row[c.column_name]
                const numeric = NUMERIC.has(c.inferred_type)
                return (
                  <td
                    key={c.ordinal}
                    className={
                      'border-b border-line/40 px-3 py-1.5 whitespace-nowrap ' +
                      (numeric ? 'text-right font-mono tabular-nums ' : '') +
                      (v === null ? 'text-faint italic' : 'text-ink')
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

      {rows.length === 0 && <div className="p-6 text-sm text-faint">No rows on this page.</div>}
    </div>
  )
}
