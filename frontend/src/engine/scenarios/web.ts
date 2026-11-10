import { act, end, obs, say, start, think } from './helpers'
import type { Scenario } from './types'

const T = 't'

export const web: Scenario = {
  id: 'web',
  steps: [
    start(T),
    think(T, 's1', "You want recent information: I'm running a web search."),
    act(T, 's1', 'web.search', { query: 'pytest latest version' }),
    obs(T, 's1', '2 results kept.', 760),
    {
      delay: 160,
      event: {
        type: 'web_results',
        results: [
          { title: 'pytest : documentation officielle', url: 'https://docs.pytest.org/' },
          { title: 'pytest on PyPI', url: 'https://pypi.org/project/pytest/' },
        ],
      },
    },
    think(T, 's2', "I'm reading the PyPI page with the external tool (MCP) to confirm."),
    act(T, 's2', 'mcp.fetch', { url: 'https://pypi.org/project/pytest/' }),
    obs(T, 's2', 'Page read through the MCP server.', 540),
    ...say(
      T,
      "The current version is listed on pytest's PyPI page; I'm giving you both sources rather than quoting a number from memory, which could be outdated.",
    ),
    end(T),
  ],
}
