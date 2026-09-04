/**
 * The landing screen. Its only job is to make the shape of the thing obvious
 * before anyone uploads anything: what goes in, what comes back, and what the
 * system will refuse to decide on your behalf.
 */

import { useRouter } from '@/app/router'
import { AgentDiagram, RuleEngineDiagram } from '@/components/Diagrams'
import { Icon, Logo, Pill } from '@/components/ui'

const NAV = [
  { label: 'How it works', href: '#how' },
  { label: 'Architecture', href: '#architecture' },
  { label: 'Rule engine', href: '#engine' },
  { label: 'What it checks', href: '#checks' },
]

function Nav() {
  const { go } = useRouter()
  return (
    <header className="mx-auto flex w-full max-w-6xl items-center gap-8 px-8 py-6">
      <Logo />
      <nav className="hidden items-center gap-7 md:flex">
        {NAV.map((n) => (
          <a
            key={n.href}
            href={n.href}
            className="text-[12px] tracking-[0.08em] text-muted uppercase transition-colors hover:text-ink"
          >
            {n.label}
          </a>
        ))}
      </nav>
      <button onClick={() => go('/upload')} className="btn btn-ghost ml-auto">
        Open workspace
      </button>
    </header>
  )
}

const STEPS = [
  {
    n: '01',
    title: 'Drop in your exports',
    body: 'Any CSVs — orders, a processor file, a bank statement. No schema to configure and no column mapping: the shape is measured from the data itself.',
  },
  {
    n: '02',
    title: 'Ask in plain words',
    body: '“Reconcile it.” The deterministic pass runs first and does the bulk for free; the agent works only what is left and never does the arithmetic itself.',
  },
  {
    n: '03',
    title: 'Review what it could not settle',
    body: 'Every match carries the rows it was built from. You accept or reject — nothing is filed as reconciled because it merely looked right.',
  },
]

const CHECKS = [
  ['Amounts tie', 'Compared as integer minor units, re-derived from the source cell rather than trusted.'],
  ['One currency', 'A group spanning two currencies is refused, not scored.'],
  ['Nothing claimed twice', 'A row can settle an invoice and sit in a payout — but not be counted twice in either.'],
  ['Timing looks normal', 'The usual settlement lag is learned from your data. No window to configure.'],
  ['Duplicated rows named', 'A file recording the same line twice is called out, with what it does to the total.'],
  ['Rules earn trust', 'A new rule holds its matches for review until you approve it once.'],
]

export default function Home() {
  const { go } = useRouter()

  return (
    <div className="min-h-full">
      <Nav />

      <main className="mx-auto w-full max-w-6xl px-8">
        {/* hero */}
        <section className="flex flex-col items-center pt-16 pb-24 text-center md:pt-24">
          <Pill tone="accent" className="mb-7">
            <Icon.spark size={12} />
            Deterministic first, agent second
          </Pill>

          <h1 className="max-w-[16ch] text-[clamp(2.6rem,7vw,4.6rem)] leading-[1.02] font-semibold tracking-[-0.03em] text-accent-deep">
            Reconcile anything you can export.
          </h1>

          <p className="mt-6 max-w-[58ch] text-[15px] leading-relaxed text-muted">
            Multi-source reconciliation with no fixed schema. Matching, summing and
            balancing run as SQL — the model chooses the strategy and reads the
            result, but every figure on screen traces back to a row in your file.
          </p>

          <div className="mt-9 flex flex-wrap items-center justify-center gap-3">
            <button onClick={() => go('/upload')} className="btn btn-primary px-6 py-3">
              Start a reconciliation
              <Icon.arrow size={15} />
            </button>
            <a href="#how" className="btn btn-ghost px-6 py-3">
              See how it works
            </a>
          </div>

          <p className="mt-5 font-mono text-[11px] text-faint">
            CSV only · runs locally · nothing is filed without you
          </p>
        </section>

        {/* how */}
        <section id="how" className="scroll-mt-8 pb-24">
          <h2 className="eyebrow mb-6">How it works</h2>
          <div className="grid gap-4 md:grid-cols-3">
            {STEPS.map((s) => (
              <article key={s.n} className="panel p-6">
                <span className="font-mono text-[11px] text-accent">{s.n}</span>
                <h3 className="mt-3 text-[16px] font-medium text-ink">{s.title}</h3>
                <p className="mt-2 text-[13px] leading-relaxed text-muted">{s.body}</p>
              </article>
            ))}
          </div>
        </section>

        {/* architecture */}
        <section id="architecture" className="scroll-mt-8 pb-24">
          <h2 className="eyebrow mb-2">Architecture</h2>
          <p className="mb-6 max-w-[62ch] text-[13px] leading-relaxed text-muted">
            One agent, six tools, and a deterministic core it cannot bypass. The
            model decides what to look at and how to say it; the arithmetic
            happens in SQL, on your rows, every time.
          </p>
          <AgentDiagram />
        </section>

        {/* rule engine */}
        <section id="engine" className="scroll-mt-8 pb-24">
          <h2 className="eyebrow mb-2">The rule engine</h2>
          <p className="mb-6 max-w-[62ch] text-[13px] leading-relaxed text-muted">
            What runs when you say “reconcile it” — before any model is asked
            anything. Given the same files it gives the same answer, which is why
            this, and not the conversation, is what gets scored against labelled
            data.
          </p>
          <RuleEngineDiagram />
        </section>

        {/* checks */}
        <section id="checks" className="scroll-mt-8 pb-28">
          <h2 className="eyebrow mb-2">What it checks before calling anything reconciled</h2>
          <p className="mb-6 max-w-[62ch] text-[13px] leading-relaxed text-muted">
            Confidence is computed from evidence, never asserted by the model. A
            second pass re-derives every figure from the source rows before a
            match is released — sharing nothing with the pass that produced it.
          </p>
          <div className="panel divide-y divide-line">
            {CHECKS.map(([title, body]) => (
              <div key={title} className="flex gap-4 px-6 py-4">
                <span className="mt-0.5 text-accent">
                  <Icon.check size={15} />
                </span>
                <div>
                  <p className="text-[13px] font-medium text-ink">{title}</p>
                  <p className="mt-0.5 text-[12.5px] leading-relaxed text-muted">{body}</p>
                </div>
              </div>
            ))}
          </div>
        </section>
      </main>

      <footer className="mx-auto flex w-full max-w-6xl items-center gap-3 border-t border-line px-8 py-6">
        <Logo size={16} />
        <span className="ml-auto font-mono text-[11px] text-faint">
          synthetic data only · no figure is produced by a language model
        </span>
      </footer>
    </div>
  )
}
