import type { ReactNode } from 'react'
import { useLocation } from 'react-router-dom'
import { Sidebar } from './Sidebar'

/** Barre latérale à gauche (navigation + conversations), contenu de la page à droite. */
export function AppShell({ children, wide = false }: { children: ReactNode; wide?: boolean }) {
  const path = useLocation().pathname
  const home = path === '/'
  // Le chat occupe toute la largeur à droite de la barre latérale ; sa zone de saisie colle au bas de l'écran.
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
                ? 'max-w-none pb-10' // la scène d'accueil va d'un bord à l'autre ; la suite se recentre dans la page
                : `px-4 pb-10 pt-16 sm:px-8 lg:pt-6 ${wide ? 'max-w-[110rem]' : 'max-w-7xl'}`
          }`}
        >
          {children}
        </main>
      </div>
    </div>
  )
}
