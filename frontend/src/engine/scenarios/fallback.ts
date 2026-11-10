import { end, say, start, think } from './helpers'
import type { Scenario } from './types'

const T = 't'

export const fallback: Scenario = {
  id: 'fallback',
  steps: [
    start(T),
    think(T, 's1', "I don't have a clear lead for this request: I'll suggest some examples."),
    ...say(
      T,
      "I'm not sure I understood. For example, I can search the project code, write and test a function, prepare a deployment, search the web or summarize the session. Tell me what you want to do!",
    ),
    end(T),
  ],
}
