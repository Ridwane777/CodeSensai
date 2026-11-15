# Privacy policy - CodeSensai

*Version of 2026-10-29. Published by the CodeSensai project team; this text does not
replace a lawyer's advice. See the [risk analysis](README.md).*

## In short

CodeSensai runs **on your machine**. The team collects nothing: no account,
no usage statistics, no advertising, no central server. Your messages leave
your machine only to go to the **model server you configure** (`--host`),
and, if you create one, through a **share link** served by your own
`sensai-web` server.

## Which data, what for

| Data | Why | Where it is |
| --- | --- | --- |
| Your messages and the assistant's answers | Running the conversation: the model receives the history to keep the context | In memory during the session; on disk if session persistence (M1) is on |
| The code you paste or the assistant writes | Answering, and running it in the sandbox if you accept | Same; the sandbox (T2) is a throwaway Docker container, without network or access to your files, removed after each run |
| Text files you attach in the web chat (at most 3 per message) | Answering about them | Read in your browser and put **inside your message**: sent to the model server and saved in the session like any message ([local-data.md](local-data.md)) |
| The content of files the assistant reads (`read_file`) or writes (`write_file`), in the folder you start it from | Answering about your project, fixing a file if you accept | Sent to the model server like the rest of the conversation. Recognised secrets (API keys, private keys, tokens, passwords as `name = value`, e-mails, card numbers) are replaced by `[REDACTED:…]` before sending. Sensitive files (`.env*`, `.ssh`, `*.pem`, `*.key`…) are never read |
| The text of project documents (PDF, Word, Excel, PowerPoint…), converted for search and reading (#64) | Answering about the brief, a specification or a spreadsheet of the project | Converted on your machine, in a container without network; indexed in `~/.sensai/rag.db` like the code; useful passages go to the model server like the rest of the conversation ([ADR-0034](../decisions/0034-read-all-file-formats.md)) |
| Facts the agent keeps about the project (M3): versions, dependencies, owners, technical choices | Answering weeks later without you repeating yourself | `~/.sensai/memory.db`, saved only after your agreement, **with no automatic purge**; erasable with `/facts forget` ([local-data.md](local-data.md)) |
| The project state document and its log (M4) | Knowing where the project stands from one session to the next; undoing a change | `SENSAI.md` in the project (shared if you commit it); change log in `~/.sensai/state/`, purged after 30 days ([local-data.md](local-data.md)) |
| Cached questions and answers (A6), with the fingerprint of the files read | Answering an already asked question at once | `~/.sensai/cache.db` on your machine; only the question goes, for its embedding, to the same server as the RAG; `/cache clear` erases everything ([local-data.md](local-data.md)) |
| Scheduled tasks and their reports (X5) | Replaying a task without you | `~/.sensai/schedule/` on your machine ([local-data.md](local-data.md)) |
| Share links you create in the web interface (X3) | Letting someone read a conversation | `~/.sensai/shares.json` on your machine (mode `600`): a copy of the user and assistant messages with recognised secrets masked, and the SHA-256 of the link's token; expires after 7 days ([local-data.md](local-data.md)) |
| Your profile (name, preferences, instructions) | Personalising answers without repeating everything | `~/.sensai/profile.json` on your machine (M1) |
| The project folder path | Resuming the right conversation for the right project | `~/.sensai/sessions.db` on your machine (M1) |
| Copies of passages of your project (code, documentation) and their embeddings | Finding the passages useful to a question and adding them to the message sent to the model | `~/.sensai/rag.db` on your machine (R1). Never indexed: `.env*`, keys, files excluded by `.gitignore` ([local-data.md](local-data.md)) |

Legal basis (GDPR art. 6): performance of the service you request. No data
is used to train a model, sold, or shared for commercial purposes.

## Where your data goes

- **Local model** (`--host` default, `http://localhost:11434`): nothing
  leaves your machine.
- **Remote model on RunPod** (used by the team for the demo): your messages,
  and the history of the resumed session, are sent to the GPU pod rented by
  the team from **RunPod**, which then acts as host (processor within the
  meaning of GDPR art. 28).
  - RunPod states that it forbids its hosts from inspecting pod data, and
    claims GDPR compliance only for its **European data centres**.
  - The region of the team's pod is **to be confirmed**. Until it is, do
    not send personal or confidential data to that server: use a local
    model or `--new-session`.
- **Web search (`web_search` tool)**: the search text written by the model
  is sent to **DuckDuckGo**, and to **Bing (Microsoft)** if DuckDuckGo
  blocks or finds nothing, from a throwaway browser
  ([ADR-0040](../decisions/0040-duckduckgo-web-search-with-bing-fallback.md)).
  The engine that receives it can link it to your IP address. Only the
  query and a browser's usual headers are sent; neither your files nor the
  session history. Do not ask for searches about personal or confidential
  data, or disable the tool: `"tools": {"disabled": ["web_search"]}` in
  `config.json` (CLI and scheduled tasks).
- **Share links**: anyone who has the link and can reach your `sensai-web`
  server can read the copy **without the access token**, for 7 days. The
  server listens only on your machine by default (`127.0.0.1`). Deleting the
  conversation does not delete its links; revoking is done through the API
  only for now.
- **Future third-party services** (third-party MCP tool): when they are
  added, the part of the request sent to them will be described here,
  before they go live.

## How long

- Sessions: **deleted automatically after 30 days without a message**
  (configurable with `--retention-days`). A conversation you delete from the
  web sidebar is removed from the list at once, but its text stays in the
  free space of the database file until the next purge that removes a
  session ([local-data.md](local-data.md)).
- Share links: 7 days, removed from the file at the next server start.
- Profile: until you erase it.
- On the RunPod pod: the Ollama server does not store the conversations it
  receives through its API. The container disk is wiped when the pod stops;
  a persistent volume, if any, must contain only the model.

## Your rights

Everything is on your machine and under your control (GDPR art. 15 to 21):
- **access**: `/sessions`, `/profile`, the Memory page of the web interface;
- **rectify**: `/remember`;
- **erase**: `/forget` for the profile, the delete button of the web chat
  sidebar for a conversation, or delete the `~/.sensai` folder to erase
  everything.

For any question: the project team (see [legal notice](legal-notice.md)).
You can also contact the CNIL (www.cnil.fr).

## Security

Local files readable by you only (mode `600`, folder `700`). Points still
open, described honestly in the [risk analysis](README.md): recognised
secrets (API keys, tokens, private keys, passwords as `name = value`) are
masked in what tools return and in what you paste into the conversation; a
secret without a recognisable shape is not (L3). Access to the remote pod is
not protected yet (L2). Share links are readable without the access token
(L10), and deleted conversations remain in the database file until the next
purge (L11).
