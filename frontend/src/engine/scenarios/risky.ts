import { act, end, obs, say, start, think } from './helpers'
import type { Scenario } from './types'

const T = 't'

export const risky: Scenario = {
  id: 'risky',
  steps: [
    start(T),
    think(T, 's1', "Deleting files is irreversible: I first check what the folder contains and whether I'm allowed to touch it."),
    act(T, 's1', 'files.list', { path: 'build/' }),
    obs(T, 's1', "12 files, 3.4 MB. The build/ folder is in the list of allowed paths.", 24),
    {
      delay: 200,
      event: {
        type: 'confirm_request',
        requestId: 'c-risky',
        title: 'Delete the build/ folder?',
        detail: '12 files · 3.4 MB · irreversible action. Folder allowed by the access policy.',
        risk: 'high',
      },
    },
    {
      delay: 100,
      waitFor: 'confirm',
      requestId: 'c-risky',
      deny: [
        ...say(T, "OK, I won't touch anything. The `build/` folder stays intact."),
        end(T),
      ],
    },
    act(T, 's2', 'files.delete', { path: 'build/', recursive: true }, 300),
    obs(T, 's2', 'build/ deleted (12 files).', 31),
    ...say(T, "Done: `build/` is deleted. It will be regenerated on the next build."),
    end(T),
  ],
}
