import { useRef, useState } from 'react'
import { useDatasets } from '@/state/DatasetsContext'

export default function TopBar() {
  const { datasets, activeId, setActiveId, upload, busy } = useDatasets()
  const fileInput = useRef<HTMLInputElement>(null)
  const [dragging, setDragging] = useState(false)

  return (
    <header
      onDragOver={(e) => {
        e.preventDefault()
        setDragging(true)
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={(e) => {
        e.preventDefault()
        setDragging(false)
        void upload(e.dataTransfer.files)
      }}
      className={
        'glass flex shrink-0 items-center gap-4 border-x-0 border-t-0 px-4 py-2 transition-colors ' +
        (dragging ? 'bg-accent/10' : '')
      }
    >
      <div className="flex items-center gap-2">
        <span className="size-2 rounded-full bg-gradient-to-br from-accent to-violet" />
        <span className="text-[13px] font-medium tracking-tight">Recon</span>
      </div>

      <div className="h-4 w-px bg-line" />

      <nav className="flex min-w-0 flex-1 items-center gap-1 overflow-x-auto">
        {datasets.length === 0 && (
          <span className="text-[12px] text-faint">
            {dragging ? 'Drop to ingest' : 'No sources yet'}
          </span>
        )}
        {datasets.map((d) => {
          const on = d.id === activeId
          return (
            <button
              key={d.id}
              onClick={() => setActiveId(d.id)}
              title={d.original_name ?? d.name}
              className={
                'group flex shrink-0 items-center gap-2 rounded-md border px-2.5 py-1 text-[12px] transition-colors ' +
                (on
                  ? 'border-accent/40 bg-accent/10 text-ink'
                  : 'border-transparent text-muted hover:border-line hover:text-ink')
              }
            >
              <span className="max-w-40 truncate">{d.name}</span>
              <span className="font-mono text-[10px] text-faint tabular-nums">
                {d.row_count.toLocaleString()}
              </span>
            </button>
          )
        })}
      </nav>

      <input
        ref={fileInput}
        type="file"
        accept=".csv,text/csv"
        multiple
        className="hidden"
        onChange={(e) => {
          void upload(e.target.files ?? [])
          e.target.value = ''
        }}
      />
      <button
        onClick={() => fileInput.current?.click()}
        disabled={busy}
        className="shrink-0 rounded-md border border-line px-2.5 py-1 text-[12px] text-muted transition-colors hover:border-accent hover:text-ink disabled:opacity-40"
      >
        {busy ? 'Ingesting…' : '+ CSV'}
      </button>
    </header>
  )
}
