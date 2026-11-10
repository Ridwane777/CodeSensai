import type { Usage } from '../../state/store'
import { fmt } from '../../ui/format'

/** Discreet context gauge, under the input area (M2). */
export function StatusBar({ usage, saved }: { usage: Usage; saved: number }) {
  const alert = usage.contextPct >= 80
  return (
    <div className="flex items-center gap-3 text-[11px]" title={`${fmt(usage.used)} / ${fmt(usage.budget)} tokens`}>
      {saved > 0 && <span className="font-semibold text-ok">{fmt(saved)} tokens saved</span>}
      <span className="tabular-nums">{fmt(usage.used)} / {fmt(usage.budget)} tokens</span>
      <div
        role="progressbar"
        aria-label="Context used"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={usage.contextPct}
        data-alert={alert ? 'true' : 'false'}
        className="h-1.5 w-20 overflow-hidden rounded-full bg-line"
      >
        <div
          className={`h-full rounded-full transition-[width] duration-500 ease-out ${alert ? 'bg-danger' : 'bg-accent-strong'}`}
          style={{ width: `${Math.min(100, usage.contextPct)}%` }}
        />
      </div>
      <span className={alert ? 'font-bold text-danger' : ''}>Context {usage.contextPct}%</span>
    </div>
  )
}
