import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import type { Components } from 'react-markdown'

/**
 * Renders agent prose as markdown, styled to sit inside the Activity trace --
 * dense, small type, no card chrome of its own since the caller already
 * provides that. GFM is on for tables: the agent's match summaries and
 * downstream-trace writeups lean on them heavily.
 */

const components: Components = {
  p: ({ children }) => <p className="mb-2 leading-relaxed last:mb-0">{children}</p>,
  h1: ({ children }) => (
    <h1 className="mt-3 mb-1.5 text-[14px] font-semibold text-ink first:mt-0">{children}</h1>
  ),
  h2: ({ children }) => (
    <h2 className="mt-3 mb-1.5 text-[13px] font-semibold text-ink first:mt-0">{children}</h2>
  ),
  h3: ({ children }) => (
    <h3 className="mt-2.5 mb-1 text-[12px] font-semibold text-ink first:mt-0">{children}</h3>
  ),
  strong: ({ children }) => <strong className="font-semibold text-ink">{children}</strong>,
  em: ({ children }) => <em className="italic text-muted">{children}</em>,
  a: ({ href, children }) => (
    <a
      href={href}
      target="_blank"
      rel="noreferrer"
      className="text-accent underline underline-offset-2 hover:text-accent/80"
    >
      {children}
    </a>
  ),
  ul: ({ children }) => (
    <ul className="mb-2 list-disc space-y-0.5 pl-4 last:mb-0">{children}</ul>
  ),
  ol: ({ children }) => (
    <ol className="mb-2 list-decimal space-y-0.5 pl-4 last:mb-0">{children}</ol>
  ),
  li: ({ children }) => <li className="pl-0.5">{children}</li>,
  hr: () => <hr className="my-3 border-line" />,
  blockquote: ({ children }) => (
    <blockquote className="my-2 border-l-2 border-line pl-3 text-muted">{children}</blockquote>
  ),
  code: ({ className, children }) => {
    // remark-rehype marks fenced blocks with a language class; inline code has
    // none, and that is the only reliable way to tell them apart here.
    const isBlock = /language-/.test(className ?? '')
    if (isBlock) {
      return (
        <code className={'font-mono text-[11px] ' + (className ?? '')}>{children}</code>
      )
    }
    return (
      <code className="rounded bg-base/60 px-1 py-0.5 font-mono text-[11px] text-cyan">
        {children}
      </code>
    )
  },
  pre: ({ children }) => (
    <pre className="mb-2 overflow-x-auto rounded-lg border border-line bg-base/40 p-2.5 last:mb-0">
      {children}
    </pre>
  ),
  table: ({ children }) => (
    <div className="mb-2 overflow-x-auto rounded-lg border border-line last:mb-0">
      <table className="w-full border-collapse text-[12px]">{children}</table>
    </div>
  ),
  thead: ({ children }) => <thead className="bg-base/40">{children}</thead>,
  th: ({ children }) => (
    <th className="border-b border-line px-2.5 py-1.5 text-left font-medium text-muted">
      {children}
    </th>
  ),
  td: ({ children }) => (
    <td className="border-b border-line/50 px-2.5 py-1.5 align-top">{children}</td>
  ),
}

export default function Markdown({ text }: { text: string }) {
  return (
    <div className="text-[13px] leading-relaxed text-ink">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {text}
      </ReactMarkdown>
    </div>
  )
}
