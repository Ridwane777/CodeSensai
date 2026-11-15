"""
Measurements behind the R1 (Basic RAG) choices - see docs/performance/R1-rag.md.

Two independent measurements:

- `quality`: for each embedding model, on the CodeSensai repository itself,
  how many questions find the right file in the first 1, 3, 5 passages;
  indexing and search time; scores of questions with no answer, to tune the
  "nothing found" threshold.
- `search`: speed of brute-force search, pure Python versus numpy, on
  synthetic vectors from 300 to 100,000 passages.

`--chunker lines` (default of the first measurement) splits into 40-line
blocks, identical for every model; `--chunker structure` uses the real
splitting of `sensai.knowledge.rag` (functions, classes, sections), to
recalibrate the threshold on what ships.

The questions were translated from French after the published measurements.

Usage:
    python scripts/bench_rag.py quality --host http://localhost:11434
    python scripts/bench_rag.py search
"""
from __future__ import annotations

import argparse
import json
import math
import platform
import random
import statistics
import subprocess
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]

MODELS = ["nomic-embed-text", "qwen3-embedding:0.6b", "bge-m3"]

# Prefixes recommended by each model: without them, nomic and qwen3-embedding
# are at a disadvantage and the comparison would not be fair.
QUERY_PREFIX = {
    "nomic-embed-text": "search_query: ",
    "qwen3-embedding:0.6b": (
        "Instruct: Given a question about a software project, retrieve the code or "
        "documentation passage that answers it\nQuery: "
    ),
    "bge-m3": "",
}
DOC_PREFIX = {"nomic-embed-text": "search_document: ", "qwen3-embedding:0.6b": "", "bge-m3": ""}

# Question -> files containing the answer (any one is enough).
QUESTIONS: list[tuple[str, list[str]]] = [
    ("Which model do we use in development and which one for the demo?",
     ["docs/decisions/0004-model-and-infrastructure.md", "docs/research/model-choices.md"]),
    ("Why don't we use LangChain or LlamaIndex?",
     ["docs/decisions/0001-no-llm-framework.md"]),
    ("How is the session to resume chosen at startup?",
     ["src/sensai/knowledge/memory.py", "docs/decisions/0007-session-persistence.md"]),
    ("Where are sessions inactive for 30 days deleted?",
     ["src/sensai/knowledge/memory.py", "docs/decisions/0007-session-persistence.md"]),
    ("How is the user profile added to the system prompt?",
     ["src/sensai/knowledge/memory.py"]),
    ("Which contract must every tool callable by the agent follow?",
     ["src/sensai/core/tools.py", "docs/decisions/0002-shared-tool-registry.md"]),
    ("How is the Ollama response received as a stream?",
     ["src/sensai/core/ollama_client.py"]),
    ("How is config.json found when sensai is started from another directory?",
     ["src/sensai/config.py"]),
    ("How should git branches be named?", ["CONTRIBUTING.md"]),
    ("Who must review a change to the tool registry?",
     [".github/CODEOWNERS", "CONTRIBUTING.md"]),
    ("Why must the web interface not reimplement the agent?",
     ["docs/decisions/0005-web-interface-facade.md"]),
    ("What happens if the session database is corrupted?", ["src/sensai/cli.py"]),
    ("Which personal data is stored on disk?",
     ["docs/legal/local-data.md"]),
    ("What is the maximum number of iterations of the reasoning loop?",
     ["src/sensai/core/agent.py"]),
    ("Which commands should be run before requesting a review?",
     ["CONTRIBUTING.md", ".github/pull_request_template.md"]),
]
# Questions whose answer is not in the repository: used to tune the threshold.
NEGATIVES = [
    "Where is the Kafka broker configured?",
    "How are Stripe payments processed?",
    "Which service sends the sign-up confirmation emails?",
]

TEXT_SUFFIXES = {".py", ".md", ".txt", ".json", ".toml", ".yml", ".yaml", ""}
CHUNK_LINES = 40
OVERLAP = 10


# Files that contain the questions themselves (this script, its results, its
# report): indexing them would find the question instead of the answer.
EXCLUDED_FROM_CORPUS = ("docs/performance/", "scripts/bench_rag.py")


def corpus_files() -> list[Path]:
    """Files tracked by git, minus the files of the measurement itself."""
    out = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.split()
    return [ROOT / f for f in out
            if Path(f).suffix in TEXT_SUFFIXES and not f.startswith(EXCLUDED_FROM_CORPUS)]


def chunk(path: Path) -> list[dict]:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    rel = str(path.relative_to(ROOT))
    chunks, start = [], 0
    while start < max(len(lines), 1):
        end = min(start + CHUNK_LINES, len(lines))
        text = "\n".join(lines[start:end]).strip()
        if text:
            chunks.append({"source": rel, "start": start + 1, "end": end,
                           "text": f"{rel}\n{text}"})
        if end >= len(lines):
            break
        start = end - OVERLAP
    return chunks


def embed(host: str, model: str, texts: list[str], batch: int = 16) -> list[list[float]]:
    vectors = []
    for i in range(0, len(texts), batch):
        r = requests.post(f"{host}/api/embed",
                          json={"model": model, "input": texts[i:i + batch]}, timeout=600)
        r.raise_for_status()
        vectors.extend(r.json()["embeddings"])
    return vectors


def normalize(v: list[float]) -> list[float]:
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


def dot(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


def machine() -> dict:
    cpuinfo = Path("/proc/cpuinfo").read_text().splitlines()
    return {
        "python": platform.python_version(),
        "system": platform.platform(),
        "cpu": next((line.split(":", 1)[1].strip() for line in cpuinfo
                     if line.startswith("model name")), platform.processor()),
        "cores": sum(line.startswith("processor") for line in cpuinfo),
    }


def structure_chunks(path: Path) -> list[dict]:
    from sensai.knowledge.rag import chunk_file

    rel = str(path.relative_to(ROOT))
    return [{"source": c.source, "start": c.start, "end": c.end, "text": f"{rel}\n{c.text}"}
            for c in chunk_file(path, rel)]


def bench_quality(host: str, models: list[str], chunker: str = "lines") -> dict:
    files = corpus_files()
    split = structure_chunks if chunker == "structure" else chunk
    chunks = [c for f in files for c in split(f)]
    results = {"chunker": chunker, "corpus_files": len(files), "corpus_chunks": len(chunks),
               "models": {}}
    for model in models:
        t0 = time.perf_counter()
        doc_vecs = [normalize(v) for v in
                    embed(host, model, [DOC_PREFIX[model] + c["text"] for c in chunks])]
        index_s = time.perf_counter() - t0

        hits = {1: 0, 3: 0, 5: 0}
        rr, latencies, pos_top, details = [], [], [], []
        for question, targets in QUESTIONS:
            t0 = time.perf_counter()
            q = normalize(embed(host, model, [QUERY_PREFIX[model] + question])[0])
            scored = sorted(((dot(q, d), c) for d, c in zip(doc_vecs, chunks, strict=True)),
                            key=lambda s: s[0], reverse=True)
            latencies.append(time.perf_counter() - t0)
            sources = [c["source"] for _, c in scored]
            rank = next((i + 1 for i, s in enumerate(sources) if s in targets), None)
            for k in hits:
                hits[k] += rank is not None and rank <= k
            rr.append(1 / rank if rank else 0.0)
            pos_top.append(scored[0][0])
            details.append({"question": question, "rank": rank,
                            "top3": [f"{c['source']}:{c['start']}" for _, c in scored[:3]],
                            "top_score": round(scored[0][0], 4)})

        neg_top = []
        for question in NEGATIVES:
            q = normalize(embed(host, model, [QUERY_PREFIX[model] + question])[0])
            neg_top.append(max(dot(q, d) for d in doc_vecs))

        n = len(QUESTIONS)
        results["models"][model] = {
            "hit@1": f"{hits[1]}/{n}", "hit@3": f"{hits[3]}/{n}", "hit@5": f"{hits[5]}/{n}",
            "mrr": round(sum(rr) / n, 3),
            "index_seconds": round(index_s, 1),
            "query_ms_median": round(statistics.median(latencies) * 1000),
            "positive_top_score_min": round(min(pos_top), 4),
            "positive_top_score_median": round(statistics.median(pos_top), 4),
            "negative_top_score_max": round(max(neg_top), 4),
            "negative_top_scores": [round(s, 4) for s in neg_top],
            "details": details,
        }
        print(f"{model}: hit@1 {hits[1]}/{n}  hit@5 {hits[5]}/{n}  "
              f"index {index_s:.1f}s", flush=True)
    return results


def bench_search(sizes: list[int], dims: int = 1024, seed: int = 42) -> dict:
    import numpy as np

    rng = random.Random(seed)
    results = {"dims": dims, "sizes": {}}
    for n in sizes:
        vecs = [normalize([rng.gauss(0, 1) for _ in range(dims)]) for _ in range(n)]
        matrix = np.array(vecs, dtype=np.float32)
        reps = 20 if n <= 20_000 else 3
        queries = [normalize([rng.gauss(0, 1) for _ in range(dims)]) for _ in range(reps)]

        py_times, np_times = [], []
        for q in queries:
            t0 = time.perf_counter()
            sorted(range(n), key=lambda i, q=q: dot(q, vecs[i]), reverse=True)[:5]
            py_times.append(time.perf_counter() - t0)
            qa = np.array(q, dtype=np.float32)
            t0 = time.perf_counter()
            scores = matrix @ qa
            np.argpartition(-scores, 5)[:5]
            np_times.append(time.perf_counter() - t0)
        results["sizes"][n] = {
            "python_ms_median": round(statistics.median(py_times) * 1000, 2),
            "numpy_ms_median": round(statistics.median(np_times) * 1000, 3),
            "repetitions": reps,
        }
        print(f"{n:>7} passages: python {results['sizes'][n]['python_ms_median']} ms, "
              f"numpy {results['sizes'][n]['numpy_ms_median']} ms", flush=True)
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("measure", choices=["quality", "search"])
    parser.add_argument("--host", default="http://localhost:11434")
    parser.add_argument("--models", nargs="+", default=MODELS)
    parser.add_argument("--sizes", nargs="+", type=int, default=[300, 2_000, 20_000, 100_000])
    parser.add_argument("--chunker", choices=["lines", "structure"], default="lines")
    parser.add_argument("--out", type=Path, help="JSON results file")
    args = parser.parse_args()

    data = {"machine": machine(), "date": time.strftime("%Y-%m-%d %H:%M")}
    if args.measure == "quality":
        data["quality"] = bench_quality(args.host, args.models, args.chunker)
    else:
        data["search"] = bench_search(args.sizes)
    if args.out:
        args.out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
