"""
Generation parameters (ADR-0057) and actual model throughput (tokens/s).

Which generation parameters to send, and what throughput (tokens/s) we get on
our own machines. This script plays the same set of questions with checkable
answers under several settings, several times each, and records per setting:

- accuracy: the answer contains what we expect (checked by a regex);
- stability: share of questions that give the same answer on every run;
- throughput: generated tokens / second (eval_count / eval_duration, figures
  returned by Ollama itself), and prompt reading speed.

The dataset was written before the measurement. Usage:

    python scripts/bench_generation.py --host http://<ollama-host>:11434 \
        --model qwen3-coder:30b --runs 3 --out docs/performance/data/generation.json

On the development laptop (qwen3:8b, reasoning off to measure the answer alone):

    ollama pull qwen3:8b
    python scripts/bench_generation.py --host http://localhost:11434 --model qwen3:8b \
        --think off --runs 1 --out docs/performance/data/generation-laptop-qwen3-8b.json

The questions were translated from French after the published measurements;
the regexes check the same answers.
"""
import argparse
import json
import re
import statistics
import time
from pathlib import Path

import requests

SYSTEM = "You are CodeSensai, a development assistant. Answer briefly."

# (question, regex the correct answer must contain)
CASES = [
    ("In Python, what does len([]) return? Answer with the value only.", r"\b0\b"),
    ("Which command runs the tests with pytest in quiet mode? Just the command.",
     r"pytest\s+(-q|--quiet)"),  # --quiet added after the local measurement: same option
    ("Fix this code so that an empty list returns 0, answer with the code only:\n"
     "def mean(grades):\n    return sum(grades) / len(grades)",
     # Fixed after the first measurement: "if grades else 0" is correct too.
     r"if\s+not\s+grades|len\(grades\)\s*==\s*0|if\s+grades\s+else\s+0"),
    ("What is the HTTP status code for a resource that was not found? Just the number.",
     r"\b404\b"),
    ("Write a Python function median(grades) that returns the median of a non-empty list. "
     # Fixed after the first measurement: sorting in place (.sort()) also gives the median.
     "Code only.", r"def\s+median\s*\(.*(sorted|\.sort\()"),
    ("Which Python standard library module reads JSON? One word.",
     r"\bjson\b"),
]

# "hard" set: the basic set is too easy and its grading regexes were widened afterwards.
# Written and committed BEFORE any measurement: its regexes no longer change after the runs.
# Arithmetic, complexity, commands, code fixes and multi-step reasoning.
HARD_CASES = [
    ("What does sorted([3, 1, 2], reverse=True) return in Python? The value only.",
     r"\[\s*3\s*,\s*2\s*,\s*1\s*\]"),
    ('What is "abc"[::-1] in Python? The value only.', r"cba"),
    ("What is the complexity of a binary search in a sorted list of n elements?",
     r"O\(\s*log\s*\(?\s*n\s*\)?\s*\)"),
    ("Which git command creates a branch named fix and switches to it? The command only.",
     r"git\s+(switch\s+-c|checkout\s+-b)\s+fix"),
    ("Which HTTP status code does an API return when a resource has just been created? "
     "The number only.",
     r"\b201\b"),
    ('Which exception does int("x") raise in Python? The name only.', r"\bValueError\b"),
    ("Which pytest option stops the suite at the first failure? The option only.",
     r"(?<![\w-])(-x|--exitfirst)\b"),
    ("Write the SQL query that counts the rows of the users table. The query only.",
     r"(?i)select\s+count\s*\(\s*\*\s*\)\s+from\s+users"),
    ("Which Docker command lists the running containers? The command only.",
     r"docker\s+(ps|container\s+ls)\b"),
    ("Which json module function turns a Python dict into a JSON string? The name only.",
     r"json\.dumps|\bdumps\b"),
    ("Which HTTP verb fully replaces an existing resource? One word.", r"\bPUT\b"),
    ("What does len(set([1, 1, 2])) return in Python? The value only.", r"(?<![\d.])2(?![\d.])"),
    ("What is the average complexity of a key lookup in a Python dict?",
     r"O\(\s*1\s*\)"),
    ("Fix this so the loop goes from 1 to n inclusive, code only: for i in range(1, n): print(i)",
     r"range\(\s*1\s*,\s*n\s*\+\s*1\s*\)"),
    ("Write a Python function is_palindrome(s) that returns True if s reads the same in "
     "both directions. Code only.", r"def\s+is_palindrome\s*\(.*(\[::-1\]|reversed)"),
    ("What does [x * x for x in range(1, 6)] return in Python? The value only.",
     r"\[\s*1\s*,\s*4\s*,\s*9\s*,\s*16\s*,\s*25\s*\]"),
    ("A file contains 3 functions of 10 lines and 2 functions of 4 lines. How many lines "
     "of functions in total? The number only.", r"(?<![\d.])38(?![\d.])"),
    ("A request takes 120 ms. We run 50 of them one after another. How many seconds in total? "
     "The number only.", r"(?<![\d.])6(?:[.,]0+)?(?![\d.])"),
    ("A test fails 1 time in 4. We run it twice in a row, independently. What is the "
     "probability that it passes both times? As a fraction.", r"9\s*/\s*16"),
    ("A sorted list contains 1024 elements. At most how many comparisons for a binary "
     "search? The number only.", r"(?<![\d.])(10|11)(?![\d.])"),
    ("In Python 3.9+, which operator merges two dicts a and b? The expression only.",
     r"a\s*\|\s*b|\{\s*\*\*a\s*,\s*\*\*b\s*\}"),
    ("Fix this code so it does not crash on an empty list, code only:\n"
     "def first(l):\n    return l[0]", r"(if\s+not\s+l|len\(l\)\s*==\s*0|if\s+l\b|IndexError)"),
]

NUM_PREDICT = 512
REQUEST_TIMEOUT_S = 180

SETTINGS = {
    "ollama-defaults": {},
    "t0-seed": {"temperature": 0, "seed": 42},
    "t0.2-p0.9": {"temperature": 0.2, "top_p": 0.9},
    "t0.7-p0.9": {"temperature": 0.7, "top_p": 0.9},
    "t1.0": {"temperature": 1.0},
}


def ask(host, model, question, options, num_ctx, think=None):
    payload = {"model": model, "stream": False,
               "messages": [{"role": "system", "content": SYSTEM},
                            {"role": "user", "content": question}],
               # num_predict is capped for every setting: without a limit, a high-temperature
               # generation may never stop (one request hung for 600 s on 2026-11-02).
               "options": {**options, "num_ctx": num_ctx, "num_predict": NUM_PREDICT}}
    # qwen3 (including qwen3:8b) reasons by default before answering: `think` turns it
    # off or keeps it on; when not sent, the model does as it pleases.
    if think is not None:
        payload["think"] = think
    started = time.monotonic()
    try:
        r = requests.post(f"{host.rstrip('/')}/api/chat", json=payload, timeout=REQUEST_TIMEOUT_S)
        r.raise_for_status()
        body = r.json()
    except requests.exceptions.Timeout:
        # Counted as a wrong answer, not as a crash of the measurement.
        body = {"message": {"content": ""}, "timed_out": True}
    message = body.get("message", {})
    return {
        # The model as Ollama names it in its response, not the script argument.
        "served_model": body.get("model", ""),
        "text": message.get("content", ""),
        "timed_out": bool(body.get("timed_out")),
        "thinking_chars": len(message.get("thinking") or ""),
        "wall_s": round(time.monotonic() - started, 2),
        "eval_count": body.get("eval_count", 0),
        "eval_s": body.get("eval_duration", 0) / 1e9,
        "prompt_count": body.get("prompt_eval_count", 0),
        "prompt_s": body.get("prompt_eval_duration", 0) / 1e9,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--host", required=True)
    parser.add_argument("--model", default="qwen3-coder:30b")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--num-ctx", type=int, default=8192)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--set", choices=["basic", "hard"], default="basic", dest="case_set",
                        help="Question set: basic (6, the first measurement) or hard (22)")
    parser.add_argument("--think", choices=["model", "on", "off"], default="model",
                        help="qwen3 reasoning: off to measure the answer alone, "
                             "on to keep it (counted in eval_count), model: not sent")
    args = parser.parse_args()
    think = {"model": None, "on": True, "off": False}[args.think]
    cases = HARD_CASES if args.case_set == "hard" else CASES

    # The model must be installed: otherwise Ollama answers 404 without saying so clearly.
    tags = requests.get(f"{args.host.rstrip('/')}/api/tags", timeout=30).json()
    installed = {m.get("name") for m in tags.get("models", [])}
    if args.model not in installed and f"{args.model}:latest" not in installed:
        raise SystemExit(f"{args.model} is not installed on {args.host}: "
                         f"run `ollama pull {args.model}` (installed: {sorted(installed)})")

    # Load the model outside the measurement: the first call pays for loading.
    served = ask(args.host, args.model, "Hello.", {}, args.num_ctx, think)["served_model"]
    results = {}
    for name, options in SETTINGS.items():
        answers, rows = {}, []
        for _ in range(args.runs):
            for i, (question, pattern) in enumerate(cases):
                row = ask(args.host, args.model, question, options, args.num_ctx, think)
                row["case"], row["ok"] = i, bool(re.search(pattern, row["text"], re.S))
                answers.setdefault(i, []).append(row["text"].strip())
                rows.append(row)
        gen = [r["eval_count"] / r["eval_s"] for r in rows if r["eval_s"]]
        read = [r["prompt_count"] / r["prompt_s"] for r in rows if r["prompt_s"]]
        results[name] = {
            "options": options,
            "accuracy": round(sum(r["ok"] for r in rows) / len(rows), 3),
            "stable_cases": sum(len(set(v)) == 1 for v in answers.values()),
            "cases": len(cases),
            "gen_tokens_per_s_median": round(statistics.median(gen), 1) if gen else None,
            "prompt_tokens_per_s_median": round(statistics.median(read), 1) if read else None,
            "wall_s_median": round(statistics.median(r["wall_s"] for r in rows), 2),
            "rows": rows,
        }
        r = results[name]
        stable = f"{r['stable_cases']}/{r['cases']}"
        print(f"{name:16} accuracy {r['accuracy']:.0%}  stable {stable}  "
              f"generation {r['gen_tokens_per_s_median']} tok/s  reading "
              f"{r['prompt_tokens_per_s_median']} tok/s  {r['wall_s_median']} s/answer",
              flush=True)
        save(args, served, results)
    save(args, served, results)


def save(args, served, results) -> None:
    """Writes the results obtained so far: called after each setting."""
    if args.out:
        report = {"model": served, "requested_model": args.model, "think": args.think,
                  "case_set": args.case_set, "runs": args.runs, "num_ctx": args.num_ctx,
                  "num_predict": NUM_PREDICT, "date": time.strftime("%Y-%m-%d"),
                  "results": results}
        args.out.write_text(json.dumps(report, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
