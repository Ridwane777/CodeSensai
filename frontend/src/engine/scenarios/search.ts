import { act, end, obs, say, start, think } from './helpers'
import type { Scenario } from './types'

const T = 't'

export const search: Scenario = {
  id: 'search',
  steps: [
    start(T),
    think(T, 's1', 'The question is about the project code: I run a semantic search.'),
    act(T, 's1', 'rag.search', { query: 'session inconnue CLI', top_k: 5 }),
    obs(T, 's1', '5 passages found (bge-m3), relevance threshold 0.50.', 340),
    {
      delay: 160,
      event: {
        type: 'rag_sources',
        sources: [
          { path: 'src/sensai/cli.py', lines: '112-116', score: 0.83 },
          { path: 'tests/test_cli_persistence.py', lines: '1-40', score: 0.71 },
          { path: 'docs/decisions/0007-session-persistence.md', lines: '20-44', score: 0.62 },
        ],
      },
    },
    think(T, 's2', 'I check the top-ranked passage before answering.'),
    ...say(
      T,
      "In `src/sensai/cli.py`, lines 112-116, an `except KeyError` clause catches the unknown session id: the CLI prints a clear message and starts a blank session instead of crashing. The behavior is covered by `tests/test_cli_persistence.py`.",
    ),
    { delay: 120, event: { type: 'usage', used: 2310, budget: 8192, contextPct: 28 } },
    end(T),
  ],
}
