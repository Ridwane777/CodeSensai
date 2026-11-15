"""
M2 measurements (token budget): is the `CHARS_PER_TOKEN = 4` ratio right
for qwen3?

Unlike `bench_cache.py` (A6) and `bench_fewshot.py` (A7), which measure
embedding similarity, this compares the rough estimate (`len(text) // 4`)
with the actual count the Ollama API itself returns in `prompt_eval_count`
for an exchange that is really sent - the measurement suggested by the
PR #97 review.

Not run yet (no Ollama with a chat model was available when this script was
written): `CHARS_PER_TOKEN`, `DEFAULT_NUM_CTX`, the response margin
(`RESPONSE_MARGIN_TOKENS`, from which the default budget derives) and
`DEFAULT_KEEP_RECENT` are still **estimates**, not measurements (ADR-0045).
Run this script with the real model and report the result in
docs/performance/M2-token-budget.md.

    python scripts/bench_token_budget.py --host http://<ollama-host>:11434 --model qwen3:8b
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sensai.knowledge.compression import CHARS_PER_TOKEN, count_tokens  # noqa: E402

# A few exchanges of different lengths and kinds (code, prose, French,
# English): the characters/token ratio varies with the language and density
# of the text, not only its length. The French samples are intentional.
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
    """(estimate, actual count) for `text` alone, as a user message."""
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
    parser = argparse.ArgumentParser(description="Characters/token ratio calibration (M2)")
    parser.add_argument("--host", required=True)
    parser.add_argument("--model", required=True)
    args = parser.parse_args()

    print(f"Current ratio: {CHARS_PER_TOKEN} characters/token\n")
    ratios = []
    for text in SAMPLES:
        estimate, actual = measure(args.host, args.model, text)
        actual_ratio = len(text) / actual if actual > 0 else float("nan")
        ratios.append(actual_ratio)
        print(f"{len(text):5} chars | estimated {estimate:4} tokens | actual {actual:4} tokens "
              f"| actual ratio {actual_ratio:.2f} chars/token")
    mean = sum(ratios) / len(ratios)
    print(f"\nMean actual ratio on this sample: {mean:.2f} characters/token "
          f"(current: {CHARS_PER_TOKEN})")


if __name__ == "__main__":
    main()
