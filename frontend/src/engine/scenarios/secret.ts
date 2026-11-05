import { act, end, obs, say, start, think } from './helpers'
import type { Scenario } from './types'

const T = 't'

export const secret: Scenario = {
  id: 'secret',
  steps: [
    start(T),
    think(T, 's1', "Le fichier `.env` peut contenir des secrets : je lis, puis je laisse la règle de sortie décider ce qui peut s'afficher."),
    act(T, 's1', 'files.read', { path: '.env' }),
    obs(T, 's1', '3 lignes lues.', 9),
    { delay: 180, event: { type: 'guardrail', kind: 'secret', message: 'Secret détecté (clé API) : valeur masquée avant affichage.' } },
    ...say(
      T,
      "J'ai bien lu `.env`, mais je ne peux pas afficher la clé API : elle est masquée par la règle de confidentialité (`••••••••`). Je peux en revanche te confirmer qu'elle est définie.",
    ),
    end(T),
  ],
}
