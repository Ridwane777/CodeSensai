import { act, end, obs, say, start, think } from './helpers'
import type { Scenario } from './types'

const T = 't'

export const risky: Scenario = {
  id: 'risky',
  steps: [
    start(T),
    think(T, 's1', "Supprimer des fichiers est irréversible : je vérifie d'abord ce que contient le dossier et si j'ai le droit d'y toucher."),
    act(T, 's1', 'files.list', { path: 'build/' }),
    obs(T, 's1', "12 fichiers, 3,4 Mo. Le dossier build/ est dans la liste des chemins autorisés.", 24),
    {
      delay: 200,
      event: {
        type: 'confirm_request',
        requestId: 'c-risky',
        title: 'Supprimer le dossier build/ ?',
        detail: '12 fichiers · 3,4 Mo · action irréversible. Dossier autorisé par la politique d\'accès.',
        risk: 'high',
      },
    },
    {
      delay: 100,
      waitFor: 'confirm',
      requestId: 'c-risky',
      deny: [
        ...say(T, "D'accord, je ne touche à rien. Le dossier `build/` reste intact."),
        end(T),
      ],
    },
    act(T, 's2', 'files.delete', { path: 'build/', recursive: true }, 300),
    obs(T, 's2', 'build/ supprimé (12 fichiers).', 31),
    ...say(T, "C'est fait : `build/` est supprimé. Il sera régénéré au prochain build."),
    end(T),
  ],
}
