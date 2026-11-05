import { act, end, obs, say, start, think } from './helpers'
import type { Scenario } from './types'

const T = 't'

export const form: Scenario = {
  id: 'form',
  steps: [
    start(T),
    think(T, 's1', "Il me manque trois informations avant de préparer le déploiement : je te les demande."),
    {
      delay: 200,
      event: {
        type: 'question',
        requestId: 'q-deploy',
        title: 'Préparer le déploiement',
        fields: [
          { id: 'env', kind: 'choice', label: 'Environnement', options: ['staging', 'production'] },
          { id: 'tag', kind: 'text', label: 'Version à déployer', placeholder: 'ex. v0.3.0' },
          { id: 'tests', kind: 'toggle', label: 'Lancer les tests avant' },
        ],
      },
    },
    { delay: 100, waitFor: 'answer', requestId: 'q-deploy' },
    think(T, 's2', 'Merci, je prépare le plan avec tes réponses.', 380),
    act(T, 's2', 'deploy.plan', { env: '{{env}}', tag: '{{tag}}', run_tests: '{{tests}}' }),
    obs(T, 's2', 'Plan prêt : cible {{env}}, version {{tag}}.', 120),
    ...say(T, "Plan prêt : déploiement de **{{tag}}** vers **{{env}}**. Rien n'est lancé tant que tu ne me le demandes pas."),
    end(T),
  ],
}
