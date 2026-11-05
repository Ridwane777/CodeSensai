import { useId } from 'react'

/** Orbe de marque : sphère graphite, ruban orange qui coule plus vite quand l'agent réfléchit. */
export function Orb({ thinking = false, size = 320 }: { thinking?: boolean; size?: number }) {
  const uid = useId().replace(/:/g, '')
  return (
    <div data-thinking={thinking ? 'true' : 'false'} style={{ width: size, height: size }} aria-hidden="true">
      <svg viewBox="0 0 320 320" width="100%" height="100%">
        <defs>
          <radialGradient id={`${uid}g`} cx="50%" cy="50%" r="50%">
            <stop offset="0%" stopColor="var(--accent)" stopOpacity="0.55" />
            <stop offset="100%" stopColor="var(--accent)" stopOpacity="0" />
          </radialGradient>
          <radialGradient id={`${uid}s`} cx="38%" cy="30%" r="80%">
            <stop offset="0%" stopColor="#4a3f38" />
            <stop offset="55%" stopColor="#1d1714" />
            <stop offset="100%" stopColor="#0b0807" />
          </radialGradient>
          <linearGradient id={`${uid}r`} x1="0" x2="1">
            <stop offset="0%" stopColor="#ff9a5c" />
            <stop offset="100%" stopColor="#f04e12" />
          </linearGradient>
          <path id={`${uid}f`} d="M20,160 A140,46 0 0 0 300,160" />
        </defs>
        <circle className="orb-glow" cx="160" cy="160" r="150" fill={`url(#${uid}g)`} />
        <g transform="rotate(-16 160 160)">
          <path d="M20,160 A140,46 0 0 1 300,160" fill="none" stroke={`url(#${uid}r)`} strokeWidth="14" strokeLinecap="round" opacity="0.85" />
        </g>
        <circle cx="160" cy="160" r="92" fill={`url(#${uid}s)`} />
        <circle cx="160" cy="160" r="92" fill="none" stroke="#ff7a3d" strokeOpacity="0.35" strokeWidth="1.5" />
        <g transform="rotate(-16 160 160)">
          <path d="M20,160 A140,46 0 0 0 300,160" fill="none" stroke={`url(#${uid}r)`} strokeWidth="14" strokeLinecap="round" />
          <path className="orb-flow" d="M20,160 A140,46 0 0 0 300,160" fill="none" stroke="#fff" strokeOpacity="0.55" strokeWidth="2" strokeDasharray="6 18" />
          <text fontSize="8.5" fontWeight="700" letterSpacing="2" fill="#fff">
            <textPath href={`#${uid}f`} startOffset="50%" textAnchor="middle" dy="3">
              THOUGHT · ACTION · OBSERVATION · THOUGHT · ACTION
            </textPath>
          </text>
        </g>
      </svg>
    </div>
  )
}
