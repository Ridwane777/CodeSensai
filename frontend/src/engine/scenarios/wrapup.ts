import { end, say, start, think } from './helpers'
import type { Scenario } from './types'

const T = 't'

export const wrapup: Scenario = {
  id: 'wrapup',
  steps: [
    start(T),
    think(T, 's1', "Je passe la main à l'agent relecteur, plus adapté pour un bilan."),
    { delay: 250, event: { type: 'agent_handoff', from: 'sensei', to: 'reviewer' } },
    { delay: 200, event: { type: 'artifact_patch', section: 'Bilan', markdown: "- Session reprise, recherche dans le code, fonction écrite et testée, suppression confirmée, secret masqué." } },
    ...say(
      T,
      "Bilan de la séance : session reprise, recherche dans le code, fonction écrite et testée, suppression confirmée par toi, secret masqué. Tu peux planifier ce bilan chaque lundi (onglet Planification) ou exporter la séance (onglet Export).",
    ),
    end(T),
  ],
}
