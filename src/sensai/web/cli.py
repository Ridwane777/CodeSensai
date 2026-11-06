"""
[Lot D] `sensai-web` : lance le serveur web et sert l'interface (ADR-0035).

    sensai-web                      # http://127.0.0.1:8000, projet = dossier courant
    sensai-web --port 9000 --model qwen3-coder:30b --host <Ollama>

Les options du CLI (`sensai --help`) sont acceptées telles quelles. Le jeton
d'accès est généré à chaque démarrage et affiché une seule fois (ADR-0023) :
on le colle dans l'interface.
"""
from __future__ import annotations

import argparse
import secrets
import sys
import threading
from pathlib import Path

import requests

LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}
# src/sensai/web/cli.py -> racine du dépôt -> frontend/dist (npm run build).
DEFAULT_FRONTEND = Path(__file__).resolve().parents[3] / "frontend" / "dist"


def preload(host: str, model: str, num_ctx: int | None = None) -> None:
    """Charge le modèle en arrière-plan : la première question n'attend pas ~80 s.

    `num_ctx` (M2, ADR-0045) : même fenêtre que les requêtes de chat, sinon Ollama
    recharge le modèle à la première question.
    """
    payload: dict = {"model": model, "prompt": ""}
    if num_ctx:
        payload["options"] = {"num_ctx": num_ctx}
    try:
        requests.post(f"{host}/api/generate", json=payload, timeout=300).raise_for_status()
    except requests.RequestException as e:
        print(f"(avertissement : le modèle n'a pas pu être préchargé — {e})", file=sys.stderr)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="sensai-web",
        description="Serveur web de CodeSensei : l'API et l'interface.",
        epilog="Les options du CLI (sensai --help : --model, --host, --no-rag…) sont acceptées.",
    )
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--bind", default="127.0.0.1",
                        help="Adresse d'écoute (défaut : la machine locale seulement)")
    parser.add_argument("--allow-origin", action="append", default=[],
                        help="Origine autorisée en plus de l'interface servie ici (répétable)")
    parser.add_argument("--frontend", type=Path, default=DEFAULT_FRONTEND,
                        help="Dossier de l'interface construite (npm run build)")
    own, rest = parser.parse_known_args(argv)

    # Importés ici : `sensai-web --help` répond sans charger FastAPI ni le modèle.
    import uvicorn

    from sensai.config import get_settings
    from sensai.knowledge.memory import SESSIONS_FILE
    from sensai.web.runtime import WebRuntime
    from sensai.web.server import create_app

    settings = get_settings(rest, prog="sensai-web")
    # Paramètres de génération (ADR-0057) : appliqués à chaque appel de chat.
    from sensai.core.ollama_client import set_generation_options, set_request_timeout
    set_generation_options(settings.get("generation"))
    set_request_timeout(settings.get("request_timeout"))
    try:
        runtime = WebRuntime(settings, Path.cwd())
    except ValueError as e:  # règle d'entrée mal écrite (ADR-0027), profil…
        parser.error(f"config.json : {e}")
    purged = runtime.purge()

    token = secrets.token_urlsafe(32)
    app = create_app(runtime, token=token, allowed_origins=own.allow_origin,
                     frontend_dir=own.frontend)

    url = f"http://{own.bind}:{own.port}/"
    print(f"CodeSensei — interface web sur {url}")
    print(f"  modèle : {runtime.model} · projet : {runtime.project}")
    print(f"  sessions : {runtime.data_dir / SESSIONS_FILE}")
    if purged:
        print(f"  {purged} session(s) trop ancienne(s) supprimée(s) (--retention-days).")
    if not (own.frontend / "index.html").is_file():
        print("  (interface non construite : cd frontend && npm ci && npm run build ; "
              "l'API fonctionne seule)")
    if own.bind not in LOCAL_HOSTS:
        print(f"  ATTENTION : le serveur écoute sur {own.bind}, pas seulement sur cette machine. "
              "Toute personne qui a le jeton peut faire agir l'agent sur ce projet.")
    # Affiché une seule fois, jamais écrit dans un fichier ni dans une URL (ADR-0023).
    print(f"\n  Jeton d'accès (à coller dans l'interface) : {token}\n", flush=True)

    threading.Thread(
        target=preload, args=(runtime.host, runtime.model, runtime.num_ctx), daemon=True
    ).start()
    uvicorn.run(app, host=own.bind, port=own.port, log_level="warning")


if __name__ == "__main__":
    main()
