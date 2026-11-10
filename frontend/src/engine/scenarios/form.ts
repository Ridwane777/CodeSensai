import { act, end, obs, say, start, think } from './helpers'
import type { Scenario } from './types'

const T = 't'

export const form: Scenario = {
  id: 'form',
  steps: [
    start(T),
    think(T, 's1', "I need three pieces of information before preparing the deployment: let me ask you."),
    {
      delay: 200,
      event: {
        type: 'question',
        requestId: 'q-deploy',
        title: 'Prepare the deployment',
        fields: [
          { id: 'env', kind: 'choice', label: 'Environnement', options: ['staging', 'production'] },
          { id: 'tag', kind: 'text', label: 'Version to deploy', placeholder: 'e.g. v0.3.0' },
          { id: 'tests', kind: 'toggle', label: 'Run the tests first' },
        ],
      },
    },
    { delay: 100, waitFor: 'answer', requestId: 'q-deploy' },
    think(T, 's2', 'Thanks, I am preparing the plan with your answers.', 380),
    act(T, 's2', 'deploy.plan', { env: '{{env}}', tag: '{{tag}}', run_tests: '{{tests}}' }),
    obs(T, 's2', 'Plan ready: target {{env}}, version {{tag}}.', 120),
    ...say(T, "Plan ready: deploying **{{tag}}** to **{{env}}**. Nothing runs until you ask me to."),
    end(T),
  ],
}
