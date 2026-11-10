import { act, end, obs, say, start, think } from './helpers'
import type { Scenario } from './types'

const T = 't'

export const secret: Scenario = {
  id: 'secret',
  steps: [
    start(T),
    think(T, 's1', 'The `.env` file may contain secrets: I read it, then let the output rule decide what can be shown.'),
    act(T, 's1', 'files.read', { path: '.env' }),
    obs(T, 's1', '3 lignes lues.', 9),
    { delay: 180, event: { type: 'guardrail', kind: 'secret', message: 'Secret detected (API key): value masked before display.' } },
    ...say(
      T,
      'I did read `.env`, but I cannot show the API key: it is masked by the privacy rule (`••••••••`). I can confirm, however, that it is set.',
    ),
    end(T),
  ],
}
