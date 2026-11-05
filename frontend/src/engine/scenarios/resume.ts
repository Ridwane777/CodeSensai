import { act, end, obs, say, start, think } from './helpers'
import type { Scenario } from './types'

const T = 't'

export const resume: Scenario = {
  id: 'resume',
  steps: [
    start(T),
    { delay: 200, event: { type: 'usage', used: 1240, budget: 8192, contextPct: 15 } },
    think(T, 's1', 'Je cherche une session existante pour ce projet avant de répondre.'),
    act(T, 's1', 'session.load', { project: 'sensai' }),
    obs(T, 's1', 'Session 598e74dbd321 reprise (2 messages).', 38),
    think(T, 's2', 'Je relis le profil pour respecter tes préférences.'),
    act(T, 's2', 'profile.read', {}),
    obs(T, 's2', 'Profil : « réponds en français et utilise pytest ».', 12),
    ...say(
      T,
      "Re-bonjour ! J'ai repris notre dernière session (2 messages) et je garde en tête tes préférences : je réponds en français et j'utilise pytest. On continue où on s'était arrêtés ?",
    ),
    end(T),
  ],
}
