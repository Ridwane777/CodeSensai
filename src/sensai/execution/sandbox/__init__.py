"""
Isolated execution for the agent's tools (feature [T2]).

Two disposable Docker environments, never mixed:

- `PythonSandbox`: runs Python code with no network at all.
- `BrowserSandbox`: runs Chromium to search the web, with network limited to
  the search engine and nothing else on the machine reachable.

Both only produce data. Permissions, confirmation and filtering are the tool
gateway's job (docs/architecture/tool-contract.md), not theirs.
"""
