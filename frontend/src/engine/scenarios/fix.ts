import { act, end, obs, say, start, think } from './helpers'
import type { Scenario } from './types'

const T = 't'

export const fix: Scenario = {
  id: 'fix',
  steps: [
    start(T),
    think(T, 's1', "Je vais écrire la fonction, la tester dans le bac à sable, puis noter la décision dans le document de suivi."),
    { delay: 200, event: { type: 'artifact_patch', section: 'Décisions', markdown: "- Ajout de `average_latency(entries)` pour le journal d'activité (EV3)." } },
    act(T, 's1', 'sandbox.run', {
      language: 'python',
      code: 'def average_latency(entries):\n    return sum(e.ms for e in entries) / len(entries)',
    }),
    obs(T, 's1', 'ZeroDivisionError: division by zero (liste vide).', 410, false),
    think(T, 's2', "Le cas « journal vide » n'est pas géré : je renvoie 0.0 dans ce cas."),
    act(T, 's2', 'sandbox.run', {
      language: 'python',
      code: 'def average_latency(entries):\n    if not entries:\n        return 0.0\n    return sum(e.ms for e in entries) / len(entries)',
    }),
    obs(T, 's2', '2 tests passés (liste pleine, liste vide).', 380),
    { delay: 180, event: { type: 'artifact_patch', section: 'Décisions', markdown: "- Ajout de `average_latency(entries)` pour le journal d'activité (EV3).\n- Journal vide : renvoie `0.0` (échec initial corrigé dans le bac à sable)." } },
    { delay: 120, event: { type: 'artifact_patch', section: 'Tests', markdown: '- `test_average_latency` ✅\n- `test_average_latency_empty` ✅' } },
    ...say(
      T,
      "Voilà : `average_latency` est écrite. Le premier essai a planté sur un journal vide (division par zéro), je l'ai corrigée et les deux tests passent. J'ai noté la décision et les tests dans le document de suivi.",
    ),
    { delay: 120, event: { type: 'usage', used: 3180, budget: 8192, contextPct: 39 } },
    end(T),
  ],
}
