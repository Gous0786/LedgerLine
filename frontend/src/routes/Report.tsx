/**
 * The close report: the artifact you hand to someone who was not here.
 *
 * Written in plain classes against one stylesheet rather than utility classes,
 * for a reason that is not stylistic: the download is the same markup with the
 * same stylesheet wrapped in a document. Serialising the node the reader is
 * already looking at means the file cannot drift from the page -- there is no
 * second implementation to keep in step.
 *
 * Light only. A report is paper, and this one is on the app's paper.
 */

import { useEffect, useRef, useState } from 'react'
import { useRouter } from '@/app/router'
import { getReport, type CloseReport } from '@/lib/api'
import { Icon, Spinner } from '@/components/ui'

const CSS = `
.rpt { --ink:#0d2b16; --muted:#47654f; --faint:#86a190; --line:#dceadf;
  --line-firm:#bcd6c2; --paper:#ffffff; --sunk:#eef5ef; --accent:#16a34a;
  --deep:#14532d; --wash:#dcfce7; --warn:#b45309; --warn-wash:#fef3c7;
  color:var(--ink); font-family:ui-sans-serif,system-ui,"Segoe UI",sans-serif;
  font-size:15px; line-height:1.6; max-width:1000px; margin:20px auto 56px;
  padding:0 44px 56px; background:var(--paper); border:1px solid var(--line);
  border-radius:18px; -webkit-font-smoothing:antialiased; }
.rpt * { box-sizing:border-box; }
.rpt .mono { font-family:ui-monospace,"Cascadia Code","JetBrains Mono",Consolas,monospace; }

.rpt .masthead { display:flex; flex-wrap:wrap; align-items:flex-end; gap:24px;
  padding:38px 0 20px; border-bottom:2px solid var(--ink); }
.rpt .mark { display:flex; align-items:center; gap:8px; }
.rpt .mark .word { font-size:13px; font-weight:500; letter-spacing:.16em; }
.rpt h1 { font-size:38px; font-weight:600; line-height:1.05; letter-spacing:-.025em;
  margin:10px 0 0; text-wrap:balance; color:var(--deep); }
.rpt .period { font-size:12.5px; color:var(--muted); margin:8px 0 0; }
.rpt .stamp { margin-left:auto; text-align:right; font-size:11px; line-height:1.75;
  color:var(--faint); }
.rpt .stamp b { display:block; color:var(--ink); font-weight:500; letter-spacing:.04em; }

.rpt section { padding-top:40px; }
.rpt .eyebrow { font-size:10.5px; font-weight:600; letter-spacing:.15em;
  text-transform:uppercase; color:var(--faint); margin:0 0 4px; }
.rpt h2 { font-size:22px; font-weight:600; letter-spacing:-.015em; margin:0 0 6px;
  text-wrap:balance; }
.rpt .lede { color:var(--muted); max-width:64ch; margin:0 0 20px; font-size:14px; }

.rpt .cards { display:grid; grid-template-columns:repeat(auto-fit,minmax(200px,1fr));
  gap:1px; background:var(--line); border:1px solid var(--line); border-radius:6px;
  overflow:hidden; }
.rpt .cur { background:var(--paper); padding:18px 20px; }
.rpt .cur .code { font-size:11px; letter-spacing:.1em; color:var(--faint); }
.rpt .cur .big { font-size:30px; font-weight:600; line-height:1.1; margin-top:4px;
  font-variant-numeric:tabular-nums; letter-spacing:-.025em; color:var(--deep); }
.rpt .cur .sub { font-size:11.5px; color:var(--muted); margin-top:6px;
  font-variant-numeric:tabular-nums; }
.rpt .cur .sub em { font-style:normal; color:var(--warn); }
.rpt .meter { height:4px; border-radius:2px; background:var(--sunk); margin-top:11px;
  overflow:hidden; }
.rpt .meter span { display:block; height:100%; background:var(--accent); }

.rpt .flow { border:1px solid var(--line); border-radius:6px; background:var(--paper);
  padding:24px 22px 18px; overflow-x:auto; }
.rpt .flow-grid { display:flex; align-items:center; gap:14px; min-width:620px; }
.rpt .node { text-align:center; flex:0 0 auto; min-width:158px; }
.rpt .node .nm { font-size:11.5px; color:var(--ink); }
.rpt .node .ct { font-size:25px; font-weight:600; line-height:1.2; margin-top:2px;
  font-variant-numeric:tabular-nums; color:var(--deep); }
.rpt .node .of { font-size:11px; color:var(--faint); }
.rpt .node .money { font-size:11.5px; color:var(--ink); margin-top:5px;
  font-variant-numeric:tabular-nums; }
.rpt .node .money .all { color:var(--faint); }
.rpt .node .col { font-size:9.5px; color:var(--faint); margin-top:1px;
  font-family:ui-monospace,"Cascadia Code",Consolas,monospace; }
.rpt .node .less { font-size:10px; color:var(--warn); margin-top:3px;
  font-variant-numeric:tabular-nums; }
.rpt .flow-note { font-size:11.5px; color:var(--muted); margin:10px 2px 0;
  max-width:74ch; }
.rpt .link { flex:1 1 auto; text-align:center; min-width:140px; }
.rpt .link .rail { height:3px; border-radius:2px; background:var(--accent); }
.rpt .link .ends { display:flex; justify-content:space-between; gap:10px;
  font-size:10.5px; color:var(--muted); margin-top:7px;
  font-variant-numeric:tabular-nums; }
.rpt .link .cap { font-size:10px; color:var(--faint); text-align:center;
  margin-top:2px; }

.rpt .wrap { overflow-x:auto; border:1px solid var(--line); border-radius:6px;
  background:var(--paper); }
.rpt table { width:100%; min-width:600px; border-collapse:collapse; font-size:13.5px; }
.rpt th, .rpt td { text-align:left; padding:10px 16px; border-bottom:1px solid var(--line); }
.rpt thead th { font-size:10.5px; font-weight:600; letter-spacing:.12em;
  text-transform:uppercase; color:var(--faint); background:var(--sunk); white-space:nowrap; }
.rpt tbody tr:last-child td { border-bottom:0; }
.rpt td.n, .rpt th.n { text-align:right; font-variant-numeric:tabular-nums;
  white-space:nowrap; font-family:ui-monospace,"Cascadia Code",Consolas,monospace; }
.rpt .why { color:var(--muted); font-size:13px; }

.rpt td.rule, .rpt th.rule { width:280px; min-width:240px; }
.rpt td.rule { font-family:ui-monospace,"Cascadia Code",Consolas,monospace;
  font-size:11.5px; line-height:1.5; overflow-wrap:anywhere; }
.rpt .chip { display:inline-block; padding:1px 8px; border-radius:999px; font-size:10.5px;
  border:1px solid var(--line-firm); color:var(--muted); white-space:nowrap;
  font-family:ui-monospace,"Cascadia Code",Consolas,monospace; }
.rpt .chip.ok { color:var(--deep); border-color:var(--accent); background:var(--wash); }
.rpt .chip.warn { color:var(--warn); border-color:var(--warn); background:var(--warn-wash); }

.rpt .ledger { border:1px solid var(--line); border-radius:6px; background:var(--paper);
  overflow:hidden; }
.rpt .ledger .row { display:flex; align-items:baseline; gap:14px; padding:11px 18px;
  border-bottom:1px solid var(--line); }
.rpt .ledger .row:last-child { border-bottom:0; }
.rpt .ledger .row.total { background:var(--sunk); font-weight:600; }
.rpt .ledger .note { color:var(--faint); font-size:12.5px; }
.rpt .ledger .num { margin-left:auto; font-size:15px; font-variant-numeric:tabular-nums;
  font-family:ui-monospace,"Cascadia Code",Consolas,monospace; }
.rpt .ledger .row.flag .who { color:var(--warn); }

.rpt .limits { border:1px solid var(--warn); border-radius:6px; background:var(--warn-wash);
  padding:18px 20px; }
.rpt .limits h3 { font-size:16px; font-weight:600; margin:0 0 8px; }
.rpt .limits ul { margin:0; padding-left:18px; }
.rpt .limits li { margin-bottom:6px; font-size:13.5px; }
.rpt .limits li:last-child { margin-bottom:0; }

.rpt footer { margin-top:48px; padding-top:16px; border-top:1px solid var(--line);
  display:flex; flex-wrap:wrap; gap:12px; font-size:11px; color:var(--faint);
  font-family:ui-monospace,"Cascadia Code",Consolas,monospace; }
.rpt footer .sig { margin-left:auto; text-align:right; }

@media print {
  .rpt { padding:0; max-width:none; margin:0; border:0; border-radius:0; }
  .rpt section { break-inside:avoid; }
}
@media (max-width:720px) {
  .rpt { padding:0 20px 40px; margin:12px; border-radius:14px; }
  .rpt .stamp { margin-left:0; text-align:left; }
}
`

function money(minor: number | null | undefined): string {
  if (minor === null || minor === undefined) return '—'
  const neg = minor < 0
  const v = (Math.abs(minor) / 100).toFixed(2)
  const [whole, frac] = v.split('.')
  return (neg ? '-' : '') + whole.replace(/\B(?=(\d{3})+(?!\d))/g, ',') + '.' + frac
}

const TX_WORDS: Record<string, string> = {
  reconciled: 'Complete from end to end, every hop tied.',
  pending: 'Every hop tied, but a leg is still waiting on a person.',
  incomplete: 'Fewer legs than a normal transaction has — it stops partway.',
  exception: 'A hop is present but does not agree.',
  unmatched: 'Nothing matched this transaction at all.',
}

const TX_ORDER = ['reconciled', 'pending', 'incomplete', 'exception', 'unmatched']

export default function Report() {
  const { go } = useRouter()
  const [report, setReport] = useState<CloseReport | null>(null)
  const [error, setError] = useState<string | null>(null)
  const bodyRef = useRef<HTMLElement>(null)

  useEffect(() => {
    getReport()
      .then(setReport)
      .catch((e) => setError(e instanceof Error ? e.message : String(e)))
  }, [])

  function download() {
    const node = bodyRef.current
    if (!node || !report) return
    const stamp = report.period.to ?? report.generated_at.slice(0, 10)
    const html =
      '<!doctype html><html lang="en"><head><meta charset="utf-8">' +
      '<meta name="viewport" content="width=device-width,initial-scale=1">' +
      `<title>Reconciliation close — ${stamp}</title>` +
      '<style>body{margin:0;background-color:#fff;background-image:' +
      'radial-gradient(58% 44% at 12% 8%,rgba(34,197,94,.38) 0%,rgba(34,197,94,0) 100%),' +
      'radial-gradient(46% 40% at 92% 88%,rgba(21,128,61,.34) 0%,rgba(21,128,61,0) 100%),' +
      'radial-gradient(38% 34% at 78% 16%,rgba(134,239,172,.32) 0%,rgba(134,239,172,0) 100%);' +
      `background-attachment:fixed}${CSS}</style></head><body>` +
      node.outerHTML +
      '</body></html>'
    const url = URL.createObjectURL(new Blob([html], { type: 'text/html' }))
    const a = document.createElement('a')
    a.href = url
    a.download = `reconciliation-close-${stamp}.html`
    a.click()
    // Deferred: revoking in the same tick can cancel the save before the
    // browser has read the blob.
    setTimeout(() => URL.revokeObjectURL(url), 30_000)
  }

  const cov = report?.coverage
  const tx = report?.transactions

  return (
    <div className="min-h-full">
      <style>{CSS}</style>

      <header className="mx-auto flex w-full max-w-[1000px] items-center gap-3 px-8 pt-5">
        <button onClick={() => go('/workspace')} className="btn btn-quiet">
          <span className="rotate-180">
            <Icon.arrow size={14} />
          </span>
          Workspace
        </button>
        <button
          onClick={download}
          disabled={!report}
          className="btn btn-primary ml-auto"
        >
          <Icon.download size={14} />
          Download report
        </button>
      </header>

      {!report && !error && (
        <p className="flex items-center justify-center gap-2 py-24 text-[13px] text-faint">
          <Spinner size={14} /> Assembling the report…
        </p>
      )}
      {error && (
        <p className="mx-auto max-w-[1000px] px-8 py-24 text-[13px] text-bad">{error}</p>
      )}

      {report && cov && tx && (
        <article className="rpt" ref={bodyRef}>
          <header className="masthead">
            <div>
              {/* Inlined rather than the shared <Logo>: that component is
                  styled with utility classes, which do not exist inside the
                  downloaded file. Everything under .rpt draws on one
                  stylesheet so the page and the download cannot diverge. */}
              <div className="mark">
                <svg width="17" height="17" viewBox="0 0 24 24" fill="none" aria-hidden>
                  <circle cx="12" cy="12" r="10.2" stroke="currentColor" strokeWidth="1.5" />
                  <path
                    d="M6.4 14.6c2.6 0 2.6-5.2 5.2-5.2s2.6 5.2 5.2 5.2"
                    stroke="currentColor"
                    strokeWidth="1.5"
                    strokeLinecap="round"
                  />
                </svg>
                <span className="word">LEDGERLINE</span>
              </div>
              <h1>Reconciliation close</h1>
              <p className="period">
                {report.period.from} to {report.period.to} ·{' '}
                {report.sources.length} sources ·{' '}
                {cov.totals.rows.toLocaleString()} rows
              </p>
            </div>
            <div className="stamp">
              <b>RUN {report.run?.id ?? '—'}</b>
              {report.generated_at}
              <br />
              checksum <span className="mono">{report.checksum}</span>
              <br />
              {report.model}
            </div>
          </header>

          {/* value */}
          <section>
            <p className="eyebrow">Value reconciled</p>
            <h2>What tied, in money</h2>
            <p className="lede">
              Each currency stands alone — nothing here is converted or summed
              across them. “Open” is value inside a match nobody has released
              yet; “residual” is the part that does not tie at all.
            </p>
            <div className="cards">
              {Object.entries(report.value)
                .sort((a, b) => (b[1].reconciled ?? 0) - (a[1].reconciled ?? 0))
                .map(([code, v]) => {
                const rec = v.reconciled ?? 0
                const open = v.open ?? 0
                const pct = rec + open > 0 ? (rec / (rec + open)) * 100 : 0
                return (
                  <div className="cur" key={code}>
                    <div className="code">{code}</div>
                    <div className="big">{money(rec)}</div>
                    <div className="sub">
                      {money(open)} open
                      {v.residual ? (
                        <>
                          {' · '}
                          <em>residual {money(v.residual)}</em>
                        </>
                      ) : null}
                    </div>
                    <div className="meter">
                      <span style={{ width: `${pct.toFixed(1)}%` }} />
                    </div>
                  </div>
                )
              })}
            </div>
          </section>

          {/* flow */}
          <section>
            <p className="eyebrow">Transaction flow</p>
            <h2>Where the money was followed</h2>
            <p className="lede">
              {tx.spine_reason
                ? `Direction was measured, not configured: ${tx.spine_reason}.`
                : 'Direction was measured from the data, not configured.'}
            </p>

            <div className="flow">
              <div className="flow-grid">
                {tx.stages.map((stage, i) => {
                  const d = cov.datasets.find((x) => x.dataset === stage)
                  // Edges are keyed by dataset pair and arrive in their own
                  // order, so find the one joining these two stages rather
                  // than trusting the index to line up with the flow.
                  const next = tx.stages[i + 1]
                  const edge = cov.edges.find(
                    (e) =>
                      e.sides.some((s) => s.dataset === stage) &&
                      e.sides.some((s) => s.dataset === next),
                  )
                  const sides = edge
                    ? [stage, next].map((n) => edge.sides.find((s) => s.dataset === n))
                    : []
                  return (
                    <div key={stage} style={{ display: 'contents' }}>
                      <div className="node">
                        <div className="nm mono">{stage}</div>
                        <div className="ct">{d?.matched_in_any_edge ?? 0}</div>
                        <div className="of">of {d?.rows ?? 0} rows</div>
                        {d?.value && (
                          <>
                            <div className="money">
                              {money(d.value.matched_minor)}{' '}
                              <span className="all">
                                of {money(d.value.total_minor)}
                              </span>
                            </div>
                            {/* The column is named because the figure is only
                                checkable if you know which cells it came from,
                                and a file can carry more than one amount. */}
                            <div className="col">
                              {d.value.currency ? `${d.value.currency} · ` : ''}
                              {d.value.column}
                            </div>
                            {d.value.duplicate_minor > 0 && (
                              <div className="less">
                                less {money(d.value.duplicate_minor)} repeated
                              </div>
                            )}
                          </>
                        )}
                      </div>
                      {i < tx.stages.length - 1 && (
                        <div className="link">
                          <div className="rail" />
                          <div className="ends">
                            {sides.map((s, k) => (
                              <span key={k}>{s ? `${s.matched} of ${s.rows}` : '—'}</span>
                            ))}
                          </div>
                          <div className="cap">rows joined on this hop</div>
                        </div>
                      )}
                    </div>
                  )
                })}
              </div>
            </div>

            {cov.datasets.some((d) => (d.value?.duplicate_minor ?? 0) > 0) && (
              <p className="flow-note">
                Both figures leave out rows a file records twice, so the
                smaller reads as a share of the larger.{' '}
                {cov.datasets
                  .filter((d) => (d.value?.duplicate_minor ?? 0) > 0)
                  .map(
                    (d) =>
                      `${money(d.value!.duplicate_minor)} was removed from ${d.dataset}`,
                  )
                  .join('; ')}
                {' '}— stated rather than absorbed, because a total on a close
                report should never contain a deduction nobody can see.
              </p>
            )}

            <div style={{ height: 14 }} />

            <div className="wrap">
              <table>
                <thead>
                  <tr>
                    <th>Transaction outcome</th>
                    <th className="n">Count</th>
                    <th>Meaning</th>
                  </tr>
                </thead>
                <tbody>
                  {TX_ORDER.filter((s) => tx.counts[s]).map((s) => (
                    <tr key={s}>
                      <td>
                        <span className={'chip ' + (s === 'reconciled' ? 'ok' : s === 'pending' ? '' : 'warn')}>
                          {s}
                        </span>
                      </td>
                      <td className="n">{tx.counts[s]}</td>
                      <td className="why">{TX_WORDS[s]}</td>
                    </tr>
                  ))}
                  <tr>
                    <td>
                      <strong>total</strong>
                    </td>
                    <td className="n">
                      <strong>{tx.total}</strong>
                    </td>
                    <td className="why">Transactions anchored on {tx.spine}.</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </section>

          {/* exceptions */}
          <section>
            <p className="eyebrow">Exceptions</p>
            <h2>What did not settle, and why</h2>
            <p className="lede">
              Grouped by cause rather than by rule, because “thirty settlements
              arrived late” is something you can act on and “rule
              auto_batch produced thirty exceptions” is not.
            </p>
            <div className="wrap">
              <table>
                <thead>
                  <tr>
                    <th>Cause</th>
                    <th className="n">Groups</th>
                    <th className="n">Value at risk</th>
                    <th>What it means</th>
                  </tr>
                </thead>
                <tbody>
                  {report.exceptions.map((e) => (
                    <tr key={e.code}>
                      <td>{e.cause}</td>
                      <td className="n">{e.groups ?? `${e.rows ?? 0} rows`}</td>
                      <td className="n">{e.value_minor === null ? '—' : money(e.value_minor)}</td>
                      <td className="why">{e.note}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {tx.examples.length > 0 && (
              <>
                <div style={{ height: 14 }} />
                <div className="wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>Transaction</th>
                        <th>State</th>
                        <th>Finding</th>
                      </tr>
                    </thead>
                    <tbody>
                      {tx.examples.map((t) => (
                        <tr key={t.key}>
                          <td className="mono" style={{ fontSize: 12.5 }}>
                            {t.key}
                          </td>
                          <td>
                            <span className="chip warn">{t.state}</span>
                          </td>
                          <td className="why">{t.reason ?? '—'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </>
            )}
          </section>

          {/* what the files repeated */}
          {report.duplicates.sources.length > 0 && (
            <section>
              <p className="eyebrow">Duplicates</p>
              <h2>What the files recorded twice</h2>
              <p className="lede">
                Rows repeating an event already in the same file. Marked at
                ingest, never deleted. Whether they were counted is a decision
                made per file, and it is stated here because the same number
                means opposite things either way.
              </p>
              <div className="wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Source</th>
                      <th className="n">Identical</th>
                      <th className="n">Same event, new id</th>
                      <th>Treated as</th>
                    </tr>
                  </thead>
                  <tbody>
                    {report.duplicates.sources.map((d) => (
                      <tr key={d.dataset}>
                        <td className="mono" style={{ fontSize: 12.5 }}>
                          {d.dataset}
                        </td>
                        <td className="n">{d.identical || '—'}</td>
                        <td className="n">{d.same_event_different_id || '—'}</td>
                        <td className="why">
                          {d.excluded ? (
                            <>
                              <span className="chip ok">set aside</span> one
                              event recorded twice; left out of every figure
                              above
                            </>
                          ) : (
                            <>
                              <span className="chip warn">counted</span> still in
                              the figures, so their groups read as breaks
                            </>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}

          {/* accountability */}
          <section>
            <p className="eyebrow">Accountability</p>
            <h2>Who decided what</h2>
            <p className="lede">
              {report.decisions.proposed} groups were proposed. Nothing reached
              “reconciled” without an independent pass re-deriving its figures
              from the source rows.
            </p>
            <div className="ledger">
              <div className="row">
                <span className="who">Released automatically</span>
                <span className="note">system rule, verification passed</span>
                <span className="num">{report.decisions.auto_released}</span>
              </div>
              <div className="row">
                <span className="who">Accepted by a person</span>
                <span className="note">reviewed in the queue</span>
                <span className="num">{report.decisions.human_accepted}</span>
              </div>
              <div className="row">
                <span className="who">Rejected</span>
                <span className="note">—</span>
                <span className="num">{report.decisions.rejected}</span>
              </div>
              <div className="row flag">
                <span className="who">Accepted despite failed verification</span>
                <span className="note">override, recorded as one</span>
                <span className="num">{report.decisions.overridden}</span>
              </div>
              <div className="row">
                <span className="who">Held by verification</span>
                <span className="note">
                  {/* Only when something was actually held. Listing causes
                      beside a count of zero reads as an explanation of that
                      zero, which is the opposite of what they are. */}
                  {report.decisions.held > 0
                    ? report.exceptions
                        .filter((e) => e.groups !== null)
                        .map((e) => `${e.cause.toLowerCase()} ${e.groups}`)
                        .slice(0, 3)
                        .join(' · ')
                    : 'nothing was refused release'}
                </span>
                <span className="num">{report.decisions.held}</span>
              </div>
              <div className="row total">
                <span className="who">Still open</span>
                <span className="note">awaiting a decision</span>
                <span className="num">{report.decisions.open}</span>
              </div>
            </div>
          </section>

          {/* method */}
          <section>
            <p className="eyebrow">Method</p>
            <h2>How the matching was done</h2>
            <p className="lede">
              No schema was configured. Each shared key was classified by
              measured cardinality, and amount columns were found by how often
              they agree across the join — never by name.
            </p>
            <div className="wrap">
              <table>
                <thead>
                  <tr>
                    <th className="rule">Rule</th>
                    <th>Basis</th>
                    <th className="n">Groups</th>
                    <th>Trust</th>
                  </tr>
                </thead>
                <tbody>
                  {report.rules.map((r) => (
                    <tr key={r.rule}>
                      <td className="rule">
                        {r.rule.replace(/^auto_(batch|part|exact)__/, '')}
                      </td>
                      <td className="why">{r.description ?? '—'}</td>
                      <td className="n">{r.proposals}</td>
                      <td>
                        <span className={'chip ' + (r.status === 'trusted' ? 'ok' : '')}>
                          {r.approved_by ?? r.status}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div style={{ height: 14 }} />

            <div className="ledger">
              <div className="row">
                <span className="who">Groups verified</span>
                <span className="note">amounts re-derived from source cells</span>
                <span className="num">{report.verification.verified}</span>
              </div>
              <div className="row">
                <span className="who">Passed</span>
                <span className="note">every invariant</span>
                <span className="num">{report.verification.passed}</span>
              </div>
              <div className="row">
                <span className="who">Refused release</span>
                <span className="note">at least one invariant failed</span>
                <span className="num">{report.verification.failed}</span>
              </div>
            </div>
          </section>

          {/* limits */}
          <section>
            <p className="eyebrow">Limits</p>
            <h2>What this report does not tell you</h2>
            <p className="lede">
              Stated because the rest is only credible if the gaps are named.
            </p>
            <div className="limits">
              <h3>Not checked</h3>
              <ul>
                {report.limits.map((l) => (
                  <li key={l.title}>
                    <strong>{l.title}.</strong> {l.note}
                  </li>
                ))}
              </ul>
            </div>
          </section>

          <footer>
            <span>
              No figure on this page was produced by a language model — every one
              traces to a row in a source file.
            </span>
            <span className="sig">checksum {report.checksum}</span>
          </footer>
        </article>
      )}
    </div>
  )
}
