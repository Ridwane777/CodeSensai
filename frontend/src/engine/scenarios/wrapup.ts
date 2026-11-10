import { end, say, start, think } from './helpers'
import type { Scenario } from './types'

const T = 't'

export const wrapup: Scenario = {
  id: 'wrapup',
  steps: [
    start(T),
    think(T, 's1', "I'm handing off to the reviewer agent, better suited for a recap."),
    { delay: 250, event: { type: 'agent_handoff', from: 'sensei', to: 'reviewer' } },
    { delay: 200, event: { type: 'artifact_patch', section: 'Recap', markdown: "- Session resumed, code searched, function written and tested, deletion confirmed, secret masked." } },
    ...say(
      T,
      "Session recap: session resumed, code searched, function written and tested, deletion confirmed by you, secret masked. You can schedule this recap every Monday (Scheduling tab) or export the session (Export tab).",
    ),
    end(T),
  ],
}
