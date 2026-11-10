import { act, end, obs, say, start, think } from './helpers'
import type { Scenario } from './types'

const T = 't'

export const fix: Scenario = {
  id: 'fix',
  steps: [
    start(T),
    think(T, 's1', "I'll write the function, test it in the sandbox, then record the decision in the tracking document."),
    { delay: 200, event: { type: 'artifact_patch', section: 'Decisions', markdown: "- Added `average_latency(entries)` for the activity log (EV3)." } },
    act(T, 's1', 'sandbox.run', {
      language: 'python',
      code: 'def average_latency(entries):\n    return sum(e.ms for e in entries) / len(entries)',
    }),
    obs(T, 's1', 'ZeroDivisionError: division by zero (liste vide).', 410, false),
    think(T, 's2', "The empty-log case is not handled: I return 0.0 in that case."),
    act(T, 's2', 'sandbox.run', {
      language: 'python',
      code: 'def average_latency(entries):\n    if not entries:\n        return 0.0\n    return sum(e.ms for e in entries) / len(entries)',
    }),
    obs(T, 's2', '2 tests passed (non-empty list, empty list).', 380),
    { delay: 180, event: { type: 'artifact_patch', section: 'Decisions', markdown: "- Added `average_latency(entries)` for the activity log (EV3).\n- Empty log: returns `0.0` (initial failure fixed in the sandbox)." } },
    { delay: 120, event: { type: 'artifact_patch', section: 'Tests', markdown: '- `test_average_latency` ✅\n- `test_average_latency_empty` ✅' } },
    ...say(
      T,
      "Done: `average_latency` is written. The first attempt crashed on an empty log (division by zero); I fixed it and both tests pass. I recorded the decision and the tests in the tracking document.",
    ),
    { delay: 120, event: { type: 'usage', used: 3180, budget: 8192, contextPct: 39 } },
    end(T),
  ],
}
