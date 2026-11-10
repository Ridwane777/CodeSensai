"""
R2 measurements (ADR-0032): how to rerank the passages found by RAG.

Compares, on the real R1 index (bge-m3, structure-based chunking):
- `dense`   : R1 as is (embedding similarity);
- `bm25`    : keyword search (BM25), no embeddings;
- `hybrid`  : both rankings merged with Reciprocal Rank Fusion;
- `llm`     : `hybrid`, then the chat model reranks the top 10.

Two question sets: the R1 set (15 questions, `bench_rag.py`) and a "held-out"
set of 10 questions about code added since, written before any measurement,
to check that the choice does not only hold on the R1 set.

    python scripts/bench_rerank.py --host http://<ollama-host>:11434 --out r2.json
    python scripts/bench_rerank.py --host http://<ollama-host>:11434 --production

`--production` measures the shipped code instead of the variants:
`RagIndex.search` with `LlmReranker`, the CLI default threshold and passage count.

Results and choices: docs/performance/R2-rag.md.
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

# Written on 2026-10-17, before any R2 measurement: the code added after R1.
HELD_OUT: list[tuple[str, list[str]]] = [
    ("How does the agent update a single section of the state document?",
     ["src/sensai/knowledge/state_document.py", "src/sensai/tools/state_tool.py"]),
    ("Where are the facts the agent remembers about the project stored?",
     ["src/sensai/knowledge/facts.py"]),
    ("What does the agent do when the model writes a tool call in the text?",
     ["src/sensai/core/agent.py", "docs/decisions/0031-text-written-tool-calls.md"]),
    ("Which files does the read tool refuse to read?",
     ["src/sensai/execution/file_permissions.py"]),
    ("How are secrets masked in tool output?",
     ["src/sensai/execution/guardrails.py"]),
    ("How does a scheduled task decide that it must run again?",
     ["src/sensai/scheduling/runner.py", "src/sensai/scheduling/tasks.py",
      "docs/architecture/scheduling.md"]),
    ("Why does web search go through Bing?",
     ["docs/decisions/0014-bing-search-engine.md"]),
    ("How much memory and CPU does the code execution container get?",
     ["src/sensai/execution/sandbox/config.py", "docs/architecture/sandbox.md"]),
    ("How does the LLM judge score the faithfulness of an answer?",
     ["src/sensai/eval/judge.py", "docs/decisions/0019-llm-judge-evaluation.md"]),
    ("How does the agent undo the last change to a section?",
     ["src/sensai/knowledge/state_document.py"]),
]

# Files that contain the questions (or their expected answers): indexing them
# would find the question instead of the answer.
EXCLUDED = ("docs/performance/", "scripts/bench_rag.py", "scripts/bench_rerank.py",
            "docs/user-stories/R2-advanced-rag.md")

LLM_PROMPT = (
    "Question: {question}\n\nNumbered passages:\n{passages}\n\n"
    "Rank the passage numbers from most to least useful for answering the "
    "question. Answer only in JSON: {{\"order\": [numbers]}}."
)


def build_index(host: str, db: Path) -> RagIndex:
    index = RagIndex(db, str(ROOT), OllamaEmbedder(host, "bge-m3"), model="bge-m3")
    index.update(ROOT)
    with sqlite3.connect(db) as conn:
        for prefix in EXCLUDED:
            conn.execute("DELETE FROM rag_chunks WHERE path LIKE ?", (prefix + "%",))
    index._matrix = None  # reload the index without the excluded files
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
        order = [int(n) for n in json.loads(response["message"]["content"])["order"]]
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
    """The CLI path: fusion, reranking, default threshold and top 5."""
    index.reranker = LlmReranker(host, model)
    results = {
        name: score(qs, lambda q: index.search(q))
        for name, qs in (("r1", QUESTIONS), ("held_out", HELD_OUT))
    }
    results["negatives_passages"] = [len(index.search(q)) for q in NEGATIVES]
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Reranking measurements for R2")
    parser.add_argument("--host", required=True)
    parser.add_argument("--model", default="qwen3-coder:30b")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--production", action="store_true",
                        help="Measure the shipped code instead of comparing the variants")
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
        # Dense scores of unanswerable questions: the threshold must filter them out.
        results["negatives_best_dense"] = [
            index.search(q, top_k=1, min_score=-1.0)[0]["score"] for q in NEGATIVES]
        results["positives_best_dense"] = sorted(
            index.search(q, top_k=1, min_score=-1.0)[0]["score"] for q, _ in QUESTIONS + HELD_OUT)
        print("negatives:", results["negatives_best_dense"])
        print("positives (min):", results["positives_best_dense"][:3])
    if args.out:
        args.out.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
