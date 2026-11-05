[Lot D — Valentino] Logging & Monitoring [EV3] (ADR-0008, ADR-0053).

`journal.py` traces every agent turn in `<data_dir>/journal.db` (SQLite, mode
600): per turn, the session, the model time measured server-side, the
estimated tokens sent, the outcome and the interface (web or cli); per tool
call, the tool, its arguments (secrets masked by the EV2 filter, truncated),
its duration, its success and the agent (main or sub-agent role).

Written by the web turn loop (`web/runtime.py`) and the CLI turn loop
(`cli.py`) through `TurnRecorder`, which never raises: a journal failure is a
log warning. Read by `GET /api/journal` and `GET /api/journal/metrics` (Journal
page). Purged with `retention_days`; a deleted web session takes its rows with
it. Data and risks: `docs/legal/donnees-locales.md`.
