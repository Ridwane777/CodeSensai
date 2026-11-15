"""
A7 measurements (automatic few-shot): where should `fewshot_min_score` go?

Same method as `scripts/bench_cache.py` (A6): for each example in the library,
we compute the similarity (bge-m3, cosine) with:
- **close questions**, which should receive that example;
- **distant questions**, which must **never** receive it - a bad example
  misleads the model more than an off-topic RAG passage, ADR-0044.

Not run yet (no Ollama with bge-m3 was available when this script was
written): `DEFAULT_MIN_SCORE = 0.75` in `knowledge/fewshot.py` is still an
**estimate**, not a measurement. Run this script with the real model and
report the results in docs/performance/A7-fewshot.md (PR #96 review).

    python scripts/bench_fewshot.py --host http://<ollama-host>:11434 --out a7.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sensai.knowledge.rag import OllamaEmbedder  # noqa: E402

# (example question, close questions that should receive it,
#  distant questions that must never receive it)
CASES: list[tuple[str, list[str], list[str]]] = [
    ("Explain the verify_token function",
     ["How does verify_token work?", "What is the verify_token function for?"],
     ["How do I run the project tests?", "How do I add a user?"]),
    ("How does the answer cache work?",
     ["Explain the semantic cache", "The A6 cache, how does it work?"],
     ["How do I configure RAG?", "How do I switch persona?"]),
    ("How do I add a user to the database?",
     ["How do I create a new user?", "What are the steps to add an account?"],
     ["How do I delete a user?", "How do I read a file with the agent?"]),
    ("What does the search_codebase tool do?",
     ["Explain search_codebase", "What is the code search tool for?"],
     ["What does the write_file tool do?", "How does the X5 scheduler work?"]),
    ("How do I change persona mid-session?",
     ["How do I switch persona?", "How do I use /persona use?"],
     ["How do I enable debug mode?", "How do I deploy to production?"]),
]


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    return float(a @ b / (np.linalg.norm(a) * np.linalg.norm(b)))


def measure(embed, cases) -> tuple[list, list]:
    """(score, example, question) for the close and distant questions."""
    close, far = [], []
    for example_q, near, distant in cases:
        vectors = [np.array(v) for v in embed([example_q, *near, *distant])]
        for i, text in enumerate([*near, *distant]):
            row = (round(cosine(vectors[0], vectors[i + 1]), 4), example_q, text)
            (close if i < len(near) else far).append(row)
    return close, far


def report(close: list, far: list) -> None:
    print(f"\n== {len(close)} close questions, {len(far)} distant questions ==")
    for threshold in (0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90):
        hits = sum(1 for row in close if row[0] >= threshold)
        wrong = [row for row in far if row[0] >= threshold]
        print(f"threshold {threshold:.2f}: {hits}/{len(close)} useful examples served, "
              f"{len(wrong)}/{len(far)} off-topic examples served "
              f"{[w[2] for w in wrong] if wrong else ''}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Automatic few-shot threshold (A7)")
    parser.add_argument("--host", required=True)
    parser.add_argument("--model", default="bge-m3")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()

    embed = OllamaEmbedder(args.host, args.model)
    close, far = measure(embed, CASES)
    report(close, far)
    if args.out:
        args.out.write_text(
            json.dumps({"close": close, "far": far}, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )


if __name__ == "__main__":
    main()
