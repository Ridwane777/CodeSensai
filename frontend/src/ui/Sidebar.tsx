import { useEffect, useId, useState } from 'react'
import { Link, NavLink, useLocation, useNavigate } from 'react-router-dom'
import { ConversationList } from '../features/chat/ConversationList'
import { BrandMark } from './FloatingNav'
import { NAV } from './nav'
import { SimBadge } from './SimBadge'
import { ThemeToggle } from './ThemeToggle'

/** Sidebar content: logo, conversations (real server), pages, engine status and theme. */
function SidebarContent({ onNavigate }: { onNavigate: () => void }) {
  const navigate = useNavigate()
  return (
    <div className="flex h-full flex-col gap-5 overflow-y-auto p-4">
      <Link to="/" onClick={onNavigate} className="flex items-center gap-2.5 px-2 text-lg font-semibold tracking-tight text-ink">
        <BrandMark className="h-7 w-7 text-accent" />
        CodeSensai
      </Link>
      <ConversationList onOpen={() => { navigate('/chat'); onNavigate() }} />
      <nav aria-label="Main navigation" className="flex flex-col gap-0.5">
        {NAV.map((n) => (
          <NavLink
            key={n.to}
            to={n.to}
            end={n.to === '/'}
            onClick={onNavigate}
            className={({ isActive }) =>
              `rounded-xl px-3 py-2 text-sm font-medium transition-colors ${
                isActive ? 'bg-accent-soft text-ink' : 'text-muted hover:bg-accent-soft hover:text-ink'
              }`
            }
          >
            {n.label}
          </NavLink>
        ))}
      </nav>
      <div className="mt-auto flex items-center justify-between gap-2 border-t border-line pt-4">
        <SimBadge />
        <ThemeToggle />
      </div>
    </div>
  )
}

/**
 * claude.ai-style sidebar: fixed on the left on large screens, a drawer opened by the
 * "hamburger" button below `lg` (clicking the backdrop, Escape or a link closes it).
 */
export function Sidebar() {
  const [open, setOpen] = useState(false)
  const drawerId = useId()
  const { pathname } = useLocation()

  // a page change closes the drawer
  useEffect(() => setOpen(false), [pathname])

  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && setOpen(false)
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open])

  const close = () => setOpen(false)
  return (
    <>
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-64 border-r border-line bg-surface lg:block">
        <SidebarContent onNavigate={() => {}} />
      </aside>

      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        aria-controls={drawerId}
        aria-label={open ? 'Close the menu' : 'Open the menu'}
        className="glass fixed left-3 top-3 z-50 grid h-10 w-10 place-items-center rounded-full lg:hidden"
      >
        <span className="relative block h-3.5 w-5" aria-hidden="true">
          <span className={`absolute left-0 h-0.5 w-5 rounded bg-current transition-transform duration-300 ${open ? 'top-1.5 rotate-45' : 'top-0'}`} />
          <span className={`absolute left-0 top-1.5 h-0.5 w-5 rounded bg-current transition-opacity ${open ? 'opacity-0' : ''}`} />
          <span className={`absolute left-0 h-0.5 w-5 rounded bg-current transition-transform duration-300 ${open ? 'top-1.5 -rotate-45' : 'top-3'}`} />
        </span>
      </button>

      {open && (
        <div className="lg:hidden">
          <div data-testid="sidebar-backdrop" className="fixed inset-0 z-40 bg-black/40" aria-hidden="true" onClick={close} />
          <aside id={drawerId} className="fixed inset-y-0 left-0 z-40 w-64 max-w-[85vw] border-r border-line bg-surface pt-12 shadow-xl">
            <SidebarContent onNavigate={close} />
          </aside>
        </div>
      )}
    </>
  )
}
