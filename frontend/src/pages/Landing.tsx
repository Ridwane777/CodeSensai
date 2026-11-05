import { animate, motion, useReducedMotion } from 'framer-motion'
import { useEffect, useState } from 'react'
import { SUGGESTIONS } from '../engine/router'
import { LandingHero } from '../features/hero/LandingHero'
import { GlassCard } from '../ui/GlassCard'

function CountUp({ to }: { to: number }) {
  const reduced = useReducedMotion()
  const [v, setV] = useState(reduced ? to : 0)
  useEffect(() => {
    if (reduced) return setV(to)
    const c = animate(0, to, { duration: 1.1, ease: 'easeOut', onUpdate: (x) => setV(Math.round(x)) })
    return () => c.stop()
  }, [to, reduced])
  return <>{v}</>
}

const STATS = [
  { value: 28, label: 'Fonctionnalités du catalogue' },
  { value: 4, label: "Lots d'équipe" },
  { value: SUGGESTIONS.length, label: 'Scénarios de démo' },
  { value: 0, label: 'Framework LLM' },
]

const GROUPS = [
  { name: 'Base', icon: '›_', items: ['CLI avec streaming'] },
  { name: 'Mémoire et contexte', icon: '◔', items: ['Sessions et profil', 'Budget de tokens', 'Mémoire structurée', "Document d'état"] },
  { name: 'Outils', icon: '⚙', items: ['MCP', 'Bac à sable', 'Recherche web', 'Accès fichiers', 'Sortie structurée'] },
  { name: 'RAG', icon: '⌕', items: ['RAG de base', 'RAG avancé'] },
  { name: 'Orchestration', icon: '⟲', items: ['Raisonnement ReAct', 'Multi-agents', 'Confirmation humaine', 'Versions de prompts', 'Persona', 'Cache sémantique', 'Optimisation de prompts'] },
  { name: 'Évaluation', icon: '✓', items: ['Évaluation automatique', 'Garde-fous', 'Journal et métriques', 'Tests adverses'] },
  { name: 'Interface', icon: '◧', items: ['Interface web', 'Branches', 'Export et partage', 'Questions et formulaires', 'Planification'] },
]

export default function Landing() {
  return (
    <>
      <LandingHero />

      <div className="mx-auto max-w-7xl px-4 sm:px-8">
        <section aria-label="Le projet en chiffres" className="mt-10 grid grid-cols-2 gap-y-8 rounded-3xl border border-line bg-surface/60 py-7 sm:grid-cols-4">
          {STATS.map((s, i) => (
            <motion.div
              key={s.label}
              initial={{ opacity: 0, y: 16 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.3 + i * 0.06, duration: 0.5 }}
              className="px-4 sm:border-l sm:border-line sm:first:border-l-0 sm:px-8"
            >
              <p className="text-3xl font-semibold tracking-tight sm:text-4xl"><CountUp to={s.value} /></p>
              <p className="mt-1 text-sm text-muted">{s.label}</p>
            </motion.div>
          ))}
        </section>

        <section id="parcours" className="scroll-mt-6 pb-16 pt-16" aria-labelledby="parcours-titre">
          <motion.div initial={{ opacity: 0, y: 24 }} whileInView={undefined} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.6 }}>
            <h2 id="parcours-titre" className="max-w-2xl text-3xl font-bold leading-tight tracking-tight sm:text-4xl">
              Tout le parcours, en <span className="text-accent">28 fonctionnalités</span>
            </h2>
            <p className="mt-3 max-w-xl text-muted">Les sept familles du catalogue Sensai, chacune mise en scène dans la démo.</p>
          </motion.div>
          <div className="mt-10 grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {GROUPS.map((g, i) => (
              <motion.div key={g.name} initial={{ opacity: 0, y: 24 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.04 * i, duration: 0.45 }} whileHover={{ y: -3 }}>
                <GlassCard className="h-full rounded-3xl p-5 transition-colors duration-200 hover:border-accent/40">
                  <div className="mb-3 flex items-center justify-between">
                    <span className="grid h-10 w-10 place-items-center rounded-full bg-accent-soft text-accent-strong" aria-hidden="true">{g.icon}</span>
                    <span className="rounded-full border border-line px-2.5 py-0.5 text-xs font-bold">{g.items.length}</span>
                  </div>
                  <h3 className="text-lg font-extrabold">{g.name}</h3>
                  <ul className="mt-2 space-y-1 text-sm text-muted">
                    {g.items.map((it) => <li key={it}>{it}</li>)}
                  </ul>
                </GlassCard>
              </motion.div>
            ))}
          </div>
        </section>
      </div>
    </>
  )
}
