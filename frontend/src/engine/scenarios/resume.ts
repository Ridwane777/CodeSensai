import { act, end, obs, say, start, think } from './helpers'
import type { Scenario } from './types'

const T = 't'

export const resume: Scenario = {
  id: 'resume',
  steps: [
    start(T),
    { delay: 200, event: { type: 'usage', used: 1240, budget: 8192, contextPct: 15 } },
    think(T, 's1', 'I look for an existing session for this project before answering.'),
    act(T, 's1', 'session.load', { project: 'sensai' }),
    obs(T, 's1', 'Session 598e74dbd321 reprise (2 messages).', 38),
    think(T, 's2', 'I reread the profile to respect your preferences.'),
    act(T, 's2', 'profile.read', {}),
    obs(T, 's2', 'Profile: "answer in English and use pytest".', 12),
    ...say(
      T,
      "Welcome back! I resumed our last session (2 messages) and I'm keeping your preferences in mind: I answer in English and use pytest. Shall we pick up where we left off?",
    ),
    end(T),
  ],
}
