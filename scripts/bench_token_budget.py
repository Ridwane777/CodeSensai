"""
Mesures de M2 (budget de tokens) : le ratio `CHARS_PER_TOKEN = 4` est-il
le bon pour qwen3 ?

Contrairement à `bench_cache.py` (A6) et `bench_fewshot.py` (A7), qui
mesurent une similarité d'embeddings, ici on compare l'estimation grossière
(`len(texte) // 4`) au compte réel que l'API Ollama renvoie elle-même dans
`prompt_eval_count` pour un échange envoyé pour de vrai — c'est la mesure
suggérée par la revue de PR #97.

Pas encore exécuté (pas d'Ollama avec un modèle de chat disponible au
moment d'écrire ce script) : `CHARS_PER_TOKEN`, `DEFAULT_NUM_CTX`, la marge de
réponse (`RESPONSE_MARGIN_TOKENS`, dont dérive le budget par défaut) et
`DEFAULT_KEEP_RECENT` restent des **estimations**, pas des mesures (ADR-0045).
Faire tourner ce script avec le vrai modèle et reporter le résultat dans
docs/performance/M2-token-budget.md.

    python scripts/bench_token_budget.py --host http://<hôte-ollama>:11434 --model qwen3:8b
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sensai.knowledge.compression import CHARS_PER_TOKEN, count_tokens  # noqa: E402

# Quelques échanges de longueurs et de natures différentes (code, prose,
# français, anglais) : le ratio caractères/token varie avec la langue et la
# densité du texte, pas seulement sa longueur.
SAMPLES: list[str] = [
    "Explique-moi la fonction verifier_token du fichier auth.py.",
    "def verifier_token(token, secret):\n    return hmac.compare_digest(token, secret)\n",
    "Please summarize what changed in the last three commits, in English, "
    "with one bullet point per file touched.",
    "Le cache sémantique (A6) sert une réponse déjà donnée quand la nouvelle "
    "question est assez proche par les embeddings, sauf si un mot décisif "
    "diffère (ex. « taille maximale » contre « taille minimale »).",
]


def measure(host: str, model: str, text: str) -> tuple[int, int]:
    """(estimation, compte réel) pour `text` seul, comme message utilisateur."""
    response = requests.post(
        f"{host}/api/chat",
        json={"model": model, "messages": [{"role": "user", "content": text}],
              "stream": False},
        timeout=120,
    )
    response.raise_for_status()
    data = response.json()
    return count_tokens(text), data.get("prompt_eval_count", -1)


def main() -> None:
    parser = argparse.ArgumentParser(description="Calibrage du ratio caractères/token (M2)")
    parser.add_argument("--host", required=True)
    parser.add_argument("--model", required=True)
    args = parser.parse_args()

    print(f"Ratio actuel : {CHARS_PER_TOKEN} caractères/token\n")
    ratios = []
    for text in SAMPLES:
        estime, reel = measure(args.host, args.model, text)
        ratio_reel = len(text) / reel if reel > 0 else float("nan")
        ratios.append(ratio_reel)
        print(f"{len(text):5} car. | estimé {estime:4} tokens | réel {reel:4} tokens "
              f"| ratio réel {ratio_reel:.2f} car./token")
    moyenne = sum(ratios) / len(ratios)
    print(f"\nRatio réel moyen sur cet échantillon : {moyenne:.2f} caractères/token "
          f"(actuel : {CHARS_PER_TOKEN})")


if __name__ == "__main__":
    main()
