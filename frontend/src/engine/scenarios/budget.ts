import { end, say, start, think } from './helpers'
import type { Scenario } from './types'

const T = 't'

export const budget: Scenario = {
  id: 'budget',
  steps: [
    start(T),
    { delay: 150, event: { type: 'usage', used: 6900, budget: 8192, contextPct: 84 } },
    think(T, 's1', 'The context is nearing the limit (84 %): I summarize the oldest turns to free up space.'),
    { delay: 300, event: { type: 'compression', savedTokens: 1840 } },
    { delay: 150, event: { type: 'usage', used: 5060, budget: 8192, contextPct: 62 } },
    { delay: 300, event: { type: 'cache_hit', similarity: 0.94 } },
    ...say(
      T,
      "I condensed the older exchanges into a summary block (1,840 tokens freed) while keeping the important facts. This question was 94 % similar to a previous one: I answered from the cache, without calling the model.",
    ),
    { delay: 200, event: { type: 'eval_score', relevance: 0.91, faithfulness: 0.88 } },
    end(T),
  ],
}
