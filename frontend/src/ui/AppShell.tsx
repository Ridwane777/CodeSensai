import type { ReactNode } from 'react'
import { useLocation } from 'react-router-dom'
import { Sidebar } from './Sidebar'

/** Sidebar on the left (navigation + conversations), page content on the right. */
export function AppShell({ children, wide = false }: { children: ReactNode; wide?: boolean }) {
  const path = useLocation().pathname
  const home = path === '/'
  // The chat takes the full width right of the sidebar; its input area sticks to the bottom of the screen.
  const chat = path === '/chat'
  return (
    <div className="min-h-screen">
      <Sidebar />
      <div className="flex min-h-screen flex-col lg:pl-64">
        <main
          className={`mx-auto w-full flex-1 ${
            chat
              ? 'max-w-none px-4 pt-14 sm:px-8 lg:pt-0'
              : home
                ? 'max-w-none pb-10' // the landing stage goes edge to edge; the rest is centered in the page
                : `px-4 pb-10 pt-16 sm:px-8 lg:pt-6 ${wide ? 'max-w-[110rem]' : 'max-w-7xl'}`
          }`}
        >
          {children}
        </main>
      </div>
    </div>
  )
}
