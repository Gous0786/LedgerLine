interface Props {
  title: string
  children: React.ReactNode
}

/** Marks a surface that is scaffolded but not yet built, and records what
 *  is meant to live there. */
export default function Placeholder({ title, children }: Props) {
  return (
    <div className="p-8">
      <h2 className="text-lg font-medium">{title}</h2>
      <div className="mt-3 max-w-2xl space-y-2 text-sm text-[--color-muted]">{children}</div>
      <div className="mt-6 inline-block rounded border border-[--color-edge] bg-[--color-panel] px-3 py-1 font-mono text-xs text-[--color-muted]">
        not implemented
      </div>
    </div>
  )
}
