/**
 * The small shared pieces. Icons are inline SVG rather than a dependency --
 * there are nine of them and they all want to inherit `currentColor`.
 */

import type { ReactNode, SVGProps } from 'react'

export function Logo({ size = 22 }: { size?: number }) {
  return (
    <span className="inline-flex items-center gap-2">
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden>
        <circle cx="12" cy="12" r="10.2" stroke="currentColor" strokeWidth="1.5" />
        {/* two arcs meeting: the two sides of a reconciliation */}
        <path
          d="M6.4 14.6c2.6 0 2.6-5.2 5.2-5.2s2.6 5.2 5.2 5.2"
          stroke="currentColor"
          strokeWidth="1.5"
          strokeLinecap="round"
        />
      </svg>
      <span className="text-[13px] font-medium tracking-[0.16em] text-ink">LEDGERLINE</span>
    </span>
  )
}

type IconProps = SVGProps<SVGSVGElement> & { size?: number }

function base(size: number): SVGProps<SVGSVGElement> {
  return {
    width: size,
    height: size,
    viewBox: '0 0 24 24',
    fill: 'none',
    stroke: 'currentColor',
    strokeWidth: 1.6,
    strokeLinecap: 'round' as const,
    strokeLinejoin: 'round' as const,
  }
}

export const Icon = {
  arrow: ({ size = 16, ...p }: IconProps) => (
    <svg {...base(size)} {...p}>
      <path d="M5 12h14M13 6l6 6-6 6" />
    </svg>
  ),
  upload: ({ size = 16, ...p }: IconProps) => (
    <svg {...base(size)} {...p}>
      <path d="M12 16V4M7 9l5-5 5 5" />
      <path d="M4 17v2a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-2" />
    </svg>
  ),
  sheet: ({ size = 16, ...p }: IconProps) => (
    <svg {...base(size)} {...p}>
      <rect x="4" y="3" width="16" height="18" rx="2" />
      <path d="M4 9h16M4 15h16M10 3v18" />
    </svg>
  ),
  check: ({ size = 16, ...p }: IconProps) => (
    <svg {...base(size)} {...p}>
      <path d="M4 12.5l5 5L20 6.5" />
    </svg>
  ),
  alert: ({ size = 16, ...p }: IconProps) => (
    <svg {...base(size)} {...p}>
      <path d="M12 8.5v5M12 17h.01" />
      <path d="M10.3 3.8 2.6 17.2A2 2 0 0 0 4.3 20.2h15.4a2 2 0 0 0 1.7-3L13.7 3.8a2 2 0 0 0-3.4 0Z" />
    </svg>
  ),
  chevron: ({ size = 16, ...p }: IconProps) => (
    <svg {...base(size)} {...p}>
      <path d="M9 6l6 6-6 6" />
    </svg>
  ),
  spark: ({ size = 16, ...p }: IconProps) => (
    <svg {...base(size)} {...p}>
      <path d="M12 3v4M12 17v4M3 12h4M17 12h4M6 6l2.5 2.5M15.5 15.5 18 18M18 6l-2.5 2.5M8.5 15.5 6 18" />
    </svg>
  ),
  close: ({ size = 16, ...p }: IconProps) => (
    <svg {...base(size)} {...p}>
      <path d="M6 6l12 12M18 6L6 18" />
    </svg>
  ),
  trash: ({ size = 16, ...p }: IconProps) => (
    <svg {...base(size)} {...p}>
      <path d="M4 7h16M10 11v6M14 11v6" />
      <path d="M6 7l1 13a1 1 0 0 0 1 1h8a1 1 0 0 0 1-1l1-13M9 7V4h6v3" />
    </svg>
  ),
  stop: ({ size = 16, ...p }: IconProps) => (
    <svg {...base(size)} {...p}>
      <rect x="6" y="6" width="12" height="12" rx="2" />
    </svg>
  ),
}

export type Tone = 'ok' | 'warn' | 'bad' | 'info' | 'neutral' | 'accent'

const TONE: Record<Tone, string> = {
  ok: 'border-ok/30 bg-ok/10 text-ok',
  warn: 'border-warn/30 bg-warn/10 text-warn',
  bad: 'border-bad/30 bg-bad/10 text-bad',
  info: 'border-info/30 bg-info/10 text-info',
  accent: 'border-accent/30 bg-accent-soft text-accent-deep',
  neutral: 'border-line bg-white/70 text-muted',
}

export function Pill({
  tone = 'neutral',
  children,
  className = '',
}: {
  tone?: Tone
  children: ReactNode
  className?: string
}) {
  return <span className={`pill ${TONE[tone]} ${className}`}>{children}</span>
}

export function Spinner({ size = 14 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" className="animate-spin" aria-hidden>
      <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="2.4" opacity="0.18" fill="none" />
      <path d="M21 12a9 9 0 0 0-9-9" stroke="currentColor" strokeWidth="2.4" fill="none" strokeLinecap="round" />
    </svg>
  )
}

/** The wait between turns. `label` reads it out for screen readers, which get
 *  nothing from an animation. */
export function Dots({ label = 'Working' }: { label?: string }) {
  return (
    <span className="dots" role="status" aria-label={label}>
      <i />
      <i />
      <i />
      <i />
    </span>
  )
}

export function Empty({ icon, title, hint }: { icon?: ReactNode; title: string; hint?: string }) {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-2 px-6 text-center">
      {icon && <span className="text-faint">{icon}</span>}
      <p className="text-[13px] text-muted">{title}</p>
      {hint && <p className="max-w-[42ch] text-[12px] leading-relaxed text-faint">{hint}</p>}
    </div>
  )
}
