"""
[Workstream D] `sensai-web`: starts the web server and serves the interface (ADR-0035).

    sensai-web                      # http://127.0.0.1:8000, project = current directory
    sensai-web --port 9000 --model qwen3-coder:30b --host <Ollama>

CLI options (`sensai --help`) are accepted as-is. The access token is
generated at every start and shown only once (ADR-0023): paste it into the
interface.
"""
from __future__ import annotations

import argparse
import secrets
import sys
import threading
from pathlib import Path

import requests

LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}
# src/sensai/web/cli.py -> repo root -> frontend/dist (npm run build).
DEFAULT_FRONTEND = Path(__file__).resolve().parents[3] / "frontend" / "dist"


def preload(host: str, model: str, num_ctx: int | None = None) -> None:
    """Loads the model in the background: the first question does not wait ~80 s.

    `num_ctx` (M2, ADR-0045): same window as chat requests, otherwise Ollama
    reloads the model on the first question.
    """
    payload: dict = {"model": model, "prompt": ""}
    if num_ctx:
        payload["options"] = {"num_ctx": num_ctx}
    try:
        requests.post(f"{host}/api/generate", json=payload, timeout=300).raise_for_status()
    except requests.RequestException as e:
        print(f"(warning: the model could not be preloaded - {e})", file=sys.stderr)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="sensai-web",
        description="CodeSensai web server: the API and the interface.",
        epilog="CLI options (sensai --help: --model, --host, --no-rag…) are accepted.",
    )
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--bind", default="127.0.0.1",
                        help="Listen address (default: the local machine only)")
    parser.add_argument("--allow-origin", action="append", default=[],
                        help="Allowed origin besides the interface served here (repeatable)")
    parser.add_argument("--frontend", type=Path, default=DEFAULT_FRONTEND,
                        help="Directory of the built interface (npm run build)")
    own, rest = parser.parse_known_args(argv)

    # Imported here: `sensai-web --help` answers without loading FastAPI or the model.
    import uvicorn

    from sensai.config import get_settings
    from sensai.knowledge.memory import SESSIONS_FILE
    from sensai.web.runtime import WebRuntime
    from sensai.web.server import create_app

    settings = get_settings(rest, prog="sensai-web")
    # Generation parameters (ADR-0057): applied to every chat call.
    from sensai.core.ollama_client import set_generation_options, set_request_timeout
    set_generation_options(settings.get("generation"))
    set_request_timeout(settings.get("request_timeout"))
    try:
        runtime = WebRuntime(settings, Path.cwd())
    except ValueError as e:  # badly written input rule (ADR-0027), profile…
        parser.error(f"config.json: {e}")
    purged = runtime.purge()

    token = secrets.token_urlsafe(32)
    app = create_app(runtime, token=token, allowed_origins=own.allow_origin,
                     frontend_dir=own.frontend)

    url = f"http://{own.bind}:{own.port}/"
    print(f"CodeSensai - web interface at {url}")
    print(f"  model: {runtime.model} · project: {runtime.project}")
    print(f"  sessions: {runtime.data_dir / SESSIONS_FILE}")
    if purged:
        print(f"  {purged} expired session(s) deleted (--retention-days).")
    if not (own.frontend / "index.html").is_file():
        print("  (interface not built: cd frontend && npm ci && npm run build; "
              "the API works on its own)")
    if own.bind not in LOCAL_HOSTS:
        print(f"  WARNING: the server listens on {own.bind}, not only on this machine. "
              "Anyone with the token can make the agent act on this project.")
    # Shown only once, never written to a file or a URL (ADR-0023).
    print(f"\n  Access token (paste it into the interface): {token}\n", flush=True)

    threading.Thread(
        target=preload, args=(runtime.host, runtime.model, runtime.num_ctx), daemon=True
    ).start()
    uvicorn.run(app, host=own.bind, port=own.port, log_level="warning")


if __name__ == "__main__":
    main()
