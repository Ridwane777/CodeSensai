"""
Mesures de R2 (ADR-0032) : comment reclasser les passages trouvés par le RAG.

Compare, sur le vrai index de R1 (bge-m3, découpage par structure) :
- `dense`   : R1 tel quel (similarité des embeddings) ;
- `bm25`    : recherche par mots (BM25), sans embeddings ;
- `hybrid`  : les deux classements fusionnés par Reciprocal Rank Fusion ;
- `llm`     : `hybrid`, puis le modèle de chat reclasse les 10 premiers.

Deux jeux de questions : celui de R1 (15 questions, `bench_rag.py`) et un jeu
« tenu à part » de 10 questions sur le code arrivé depuis, écrit avant toute
mesure, pour vérifier que le choix ne vaut pas seulement sur le jeu de R1.

    python scripts/bench_rerank.py --host http://<hôte-ollama>:11434 --out r2.json
    python scripts/bench_rerank.py --host http://<hôte-ollama>:11434 --production

`--production` mesure le code livré à la place des variantes : `RagIndex.search`
avec `LlmReranker`, le seuil et le nombre de passages par défaut du CLI.

Résultats et choix : docs/performance/R2-rag.md.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import statistics
import sys
import tempfile
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

from bench_rag import NEGATIVES, QUESTIONS  # noqa: E402

from sensai.knowledge.rag import OllamaEmbedder, RagIndex  # noqa: E402
from sensai.knowledge.retrieval import (  # noqa: E402
    BM25,
    LlmReranker,
    reciprocal_rank_fusion,
)

# Écrit le 2026-10-17, avant toute mesure de R2 : le code arrivé après R1.
HELD_OUT: list[tuple[str, list[str]]] = [
    ("Comment l'agent met-il à jour une seule section du document d'état ?",
     ["src/sensai/knowledge/state_document.py", "src/sensai/tools/state_tool.py"]),
    ("Où sont stockés les faits que l'agent retient sur le projet ?",
     ["src/sensai/knowledge/facts.py"]),
    ("Que fait l'agent quand le modèle écrit un appel d'outil dans le texte ?",
     ["src/sensai/core/agent.py", "docs/decisions/0031-appels-d-outils-ecrits-en-texte.md"]),
    ("Quels fichiers l'outil de lecture refuse-t-il de lire ?",
     ["src/sensai/execution/file_permissions.py"]),
    ("Comment les secrets sont-ils masqués dans la sortie des outils ?",
     ["src/sensai/execution/guardrails.py"]),
    ("Comment une tâche planifiée décide-t-elle qu'elle doit être relancée ?",
     ["src/sensai/scheduling/runner.py", "src/sensai/scheduling/tasks.py",
      "docs/architecture/scheduling.md"]),
    ("Pourquoi la recherche web passe-t-elle par Bing ?",
     ["docs/decisions/0014-moteur-de-recherche-bing.md"]),
    ("Combien de mémoire et de CPU a le conteneur qui exécute le code ?",
     ["src/sensai/execution/sandbox/config.py", "docs/architecture/sandbox.md"]),
    ("Comment le juge LLM note-t-il la fidélité d'une réponse ?",
     ["src/sensai/eval/judge.py", "docs/decisions/0019-evaluation-par-juge-llm.md"]),
    ("Comment l'agent annule-t-il la dernière modification d'une section ?",
     ["src/sensai/knowledge/state_document.py"]),
]

# Fichiers qui contiennent les questions (ou leurs réponses attendues) : les
# indexer ferait trouver la question au lieu de la réponse.
EXCLUDED = ("docs/performance/", "scripts/bench_rag.py", "scripts/bench_rerank.py",
            "docs/user-stories/R2-advanced-rag.md")

LLM_PROMPT = (
    "Question : {question}\n\nPassages numérotés :\n{passages}\n\n"
    "Classe les numéros des passages du plus utile au moins utile pour répondre à la "
    "question. Réponds seulement en JSON : {{\"ordre\": [numéros]}}."
)


def build_index(host: str, db: Path) -> RagIndex:
    index = RagIndex(db, str(ROOT), OllamaEmbedder(host, "bge-m3"), model="bge-m3")
    index.update(ROOT)
    with sqlite3.connect(db) as conn:
        for prefix in EXCLUDED:
            conn.execute("DELETE FROM rag_chunks WHERE path LIKE ?", (prefix + "%",))
    index._matrix = None  # recharge l'index sans les fichiers exclus
    index._load()
    return index


def ranked(index: RagIndex, bm25: BM25, question: str, variant: str, host: str,
           model: str, depth: int = 10) -> list[dict]:
    dense = index.search(question, top_k=50, min_score=-1.0)
    if variant == "dense":
        return dense
    lexical = [index_row(index, i) | {"score": s} for i, s in bm25.search(question, 50)]
    if variant == "bm25":
        return lexical
    fused = reciprocal_rank_fusion([dense, lexical], key=lambda h: (h["source"], h["start"]))
    if variant == "hybrid":
        return fused
    head = fused[:depth]
    order = llm_order(host, model, question, head)
    return [head[i] for i in order] + fused[depth:]


def index_row(index: RagIndex, i: int) -> dict:
    source, start, end, text = index._rows[i]
    return {"source": source, "start": start, "end": end, "text": text}


def llm_order(host: str, model: str, question: str, hits: list[dict]) -> list[int]:
    passages = "\n\n".join(f"[{n}] {h['source']}\n{h['text'][:600]}" for n, h in enumerate(hits))
    response = requests.post(f"{host}/api/chat", json={
        "model": model, "stream": False, "format": "json",
        "messages": [{"role": "user", "content": LLM_PROMPT.format(
            question=question, passages=passages)}],
    }, timeout=300).json()
    try:
        order = [int(n) for n in json.loads(response["message"]["content"])["ordre"]]
    except (KeyError, ValueError, TypeError, json.JSONDecodeError):
        return list(range(len(hits)))
    seen = [n for i, n in enumerate(order) if 0 <= n < len(hits) and n not in order[:i]]
    return seen + [n for n in range(len(hits)) if n not in seen]


def score(questions, rank_fn) -> dict:
    top1 = top5 = 0
    reciprocal, timings = [], []
    for question, expected in questions:
        start = time.monotonic()
        hits = rank_fn(question)
        timings.append(time.monotonic() - start)
        files = []
        for h in hits:
            if h["source"] not in files:
                files.append(h["source"])
        position = next((i for i, f in enumerate(files) if f in expected), None)
        top1 += position == 0
        top5 += position is not None and position < 5
        reciprocal.append(1 / (position + 1) if position is not None else 0.0)
    return {"top1": top1, "top5": top5, "mrr": round(statistics.mean(reciprocal), 3),
            "n": len(questions), "seconds_per_question": round(statistics.mean(timings), 2)}


def production(index: RagIndex, host: str, model: str) -> dict:
    """Le chemin du CLI : fusion, reclassement, seuil et top 5 par défaut."""
    index.reranker = LlmReranker(host, model)
    results = {
        name: score(qs, lambda q: index.search(q))
        for name, qs in (("r1", QUESTIONS), ("held_out", HELD_OUT))
    }
    results["negatives_passages"] = [len(index.search(q)) for q in NEGATIVES]
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Mesures de reclassement pour R2")
    parser.add_argument("--host", required=True)
    parser.add_argument("--model", default="qwen3-coder:30b")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--production", action="store_true",
                        help="Mesurer le code livré au lieu de comparer les variantes")
    args = parser.parse_args()

    with tempfile.TemporaryDirectory() as tmp:
        index = build_index(args.host, Path(tmp) / "rag.db")
        if args.production:
            results = production(index, args.host, args.model)
            print(results)
            if args.out:
                args.out.write_text(json.dumps(results, indent=2), encoding="utf-8")
            return
        bm25 = BM25([f"{r[0]}\n{r[3]}" for r in index._rows])
        results = {"chunks": len(index._rows)}
        for variant in ("dense", "bm25", "hybrid", "llm"):
            results[variant] = {
                name: score(qs, lambda q, v=variant: ranked(index, bm25, q, v, args.host,
                                                            args.model))
                for name, qs in (("r1", QUESTIONS), ("held_out", HELD_OUT))
            }
            print(variant, results[variant], flush=True)
        # Scores denses des questions sans réponse : le seuil doit les écarter.
        results["negatives_best_dense"] = [
            index.search(q, top_k=1, min_score=-1.0)[0]["score"] for q in NEGATIVES]
        results["positives_best_dense"] = sorted(
            index.search(q, top_k=1, min_score=-1.0)[0]["score"] for q, _ in QUESTIONS + HELD_OUT)
        print("négatives :", results["negatives_best_dense"])
        print("positives (min) :", results["positives_best_dense"][:3])
    if args.out:
        args.out.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
