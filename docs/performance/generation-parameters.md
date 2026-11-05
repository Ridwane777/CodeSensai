# Generation parameters and generation speed (ADR-0057)

Two questions: which generation settings to send, and how fast the model
generates (tokens/s) on the machines we use, instead of published benchmark
figures. One reproducible script measures both. Done: the parameters and
the speed of `qwen3-coder:30b` on the pod's GPU, and the speed of `qwen3:8b` on
a team laptop without GPU (2026-11-02, section below).

## Method

- **Script**: [`scripts/bench_generation.py`](../../scripts/bench_generation.py).
  The question set (6 questions whose right answer is checked by a regular
  expression: a value, a command, a code fix, a function) was written before
  any measurement.
- **Settings compared**: the model's own defaults (nothing sent), `temperature`
  0 with a fixed `seed`, `temperature` 0.2 / `top_p` 0.9 (the project's default),
  `temperature` 0.7 / `top_p` 0.9, `temperature` 1.0. `num_ctx` 8192 for all.
- **Each setting**: every question 3 times. Recorded per setting:
  - accuracy: share of answers that match;
  - stability: questions that gave the same answer at every try;
  - generation speed: median of `eval_count / eval_duration`, the figures
    Ollama returns itself;
  - prompt reading speed: `prompt_eval_count / prompt_eval_duration`;
  - median wall time per answer.
- **The first call** (model loading) is made before measuring and not counted.
- **Reproduce**:
  `python scripts/bench_generation.py --host http://<pod>:11434 --model qwen3-coder:30b --runs 3 --out docs/performance/data/generation.json`

## Results (2026-11-01, measured)

**Machine**: RunPod pod with a 24 GB GPU, Ollama, `qwen3-coder:30b`, `num_ctx`
8192, 3 runs of the 6 questions per setting (18 answers each). Raw data:
[generation-2026-11-01.json](data/generation-2026-11-01.json).

| Setting | Accuracy | Stable questions (same answer 3 times) | Generation (tok/s, median) | Prompt reading (tok/s, median) | s / answer (median) |
| --- | --- | --- | --- | --- | --- |
| model's own defaults (nothing sent) | 100 % | 4 / 6 | 115.3 | 712.9 | 0.96 |
| `temperature` 0, `seed` 42 | 100 % | **6 / 6** | 118.5 | 2438.7 | 1.02 |
| **`temperature` 0.2, `top_p` 0.9 (project default)** | 100 % | **6 / 6** | 119.0 | 2828.2 | 0.99 |
| `temperature` 0.7, `top_p` 0.9 | 100 % | 4 / 6 | 97.5 | 2975.0 | 1.10 |
| `temperature` 1.0 | 100 % | 4 / 6 | 115.9 | 2916.7 | 1.04 |

**Reading:**

- **Accuracy does not separate the settings** on these six short questions:
  every setting answered all of them right. The question set is too easy to rank
  settings on correctness (see Limits).
- **Stability does**: at `temperature` 0 or 0.2, each question got the same
  answer three times out of three; with the model's defaults, 0.7 or 1.0, two
  questions out of six changed from one try to the next. For a coding assistant
  that must give the same command or the same fix twice, this is what we want:
  **the ADR-0057 defaults (0.2 / 0.9) are kept**.
- **Generation speed** is about **115–119 tokens/s** on this GPU whatever the
  setting (97.5 at 0.7 is one setting's median, not explained by this run: it
  may be noise from the shared pod). A typical short answer takes about 1 s.
- **Prompt reading** is much slower for the first setting (713 tok/s against
  2 400–3 000): it ran first, before Ollama's prompt cache was warm. It says
  nothing about the defaults themselves.

**Correction made after the runs, said openly:** the first scoring gave 67–78 %
accuracy on the pod and 83 % in the withdrawn laptop measure (made with `llama3`, see below). Reading the answers showed that three
checks were too strict: the `moyenne` fix written as
`return sum(notes) / len(notes) if notes else 0`, a `mediane` that sorts in place
with `notes.sort()`, and `pytest --quiet` (the long form of `-q`) are right but
were rejected. The three regular expressions were widened in the script, and the
accuracy was recomputed **from the recorded answers, without running anything
again** (the `rescored` field of each JSON says so). The in-place sort does
modify the caller's list: a real code-review remark, but not a wrong median.

## Harder question set (2026-11-02, measured)

First run's limits: six easy questions (100 % everywhere) and checks widened
after the run. A second set of **22 questions** (computation, complexity,
commands, code fixes, multi-step reasoning) was written with its checks and
**committed before any run** (commit `763a4f4`); the checks were not changed
afterwards. Same pod, `qwen3-coder:30b`, `num_ctx` 8192, 3 runs per setting,
answers capped at 512 tokens for every setting (commit `af56e75`: one
uncapped request had stalled for 600 s). Raw data:
[generation-hard-2026-11-02.json](data/generation-hard-2026-11-02.json).

| Setting | Accuracy (official checks) | Stable questions (same answer 3 times) | Generation (tok/s, median) | s / answer (median) |
| --- | --- | --- | --- | --- |
| model's own defaults | 91 % | 17 / 22 | 50.0 | 0.96 |
| `temperature` 0, `seed` 42 | 91 % | **22 / 22** | 54.5 | 0.91 |
| **`temperature` 0.2, `top_p` 0.9 (project default)** | 91 % | 21 / 22 | 56.2 | 0.92 |
| `temperature` 0.7, `top_p` 0.9 | 91 % | 17 / 22 | 53.4 | 0.85 |
| `temperature` 1.0 | 91 % | 18 / 22 | 55.4 | 0.90 |

**Reading:**

- **Accuracy is the same for every setting** (91 %). The two questions failed
  everywhere are, read by hand, **right answers written in LaTeX** (`O(\log n)`
  and `\frac{9}{16}`), a notation the checks did not foresee. The checks stay
  as committed; read by hand, every setting answered all 22 questions right.
- **Stability separates the settings again**: 22/22 at `temperature` 0, 21/22
  at 0.2, 17–18/22 for the model's defaults, 0.7 and 1.0. The default 0.2 keeps
  nearly all the stability of 0; the difference is one question in three runs.
- **Generation speed** was about 50–56 tokens/s in this run, against 115–119 the
  day before for the same model on the same pod setup. The pod's GPU is rented
  and shared; we do not explain the difference and do not compare the two runs'
  speeds.

## On the team's own machine (measured 2026-11-02)

Generation speed measured **on our own machine**. Machine: a
team laptop, Intel Core i7-1355U, 14 GB of RAM, **no GPU**, Ollama on the CPU.
Model: `qwen3:8b`, the project's development model (the name in the JSON is the
one Ollama returned in its answers). Basic set (6 questions), 3 runs per
question, `--think off`, `num_ctx` 8192, answers capped at 512 tokens. Data:
[generation-laptop-qwen3-8b-2026-11-02.json](data/generation-laptop-qwen3-8b-2026-11-02.json).

| Setting | Accuracy | Stable (3 runs alike) | Generation | Prompt reading | Time per answer |
| --- | --- | --- | --- | --- | --- |
| Ollama defaults | 100 % | 5/6 | 4.8 tok/s | 10.4 tok/s | 6.64 s |
| t0 + seed | 100 % | 6/6 | 4.5 tok/s | 10.1 tok/s | 6.87 s |
| t0.2, top_p 0.9 (our default) | 100 % | 5/6 | 4.6 tok/s | 10.4 tok/s | 6.67 s |
| t0.7, top_p 0.9 | 100 % | 5/6 | 4.6 tok/s | 10.5 tok/s | 6.90 s |
| t1.0 | 100 % | 5/6 | 7.8 tok/s | 17.4 tok/s | 3.97 s |

**Reading.** About **4.5–4.8 tokens/s** on the CPU, roughly **25 times slower**
than `qwen3-coder:30b` on the pod's GPU (115–119 tok/s). The questions are
short, so one answer takes about 7 s; an agent turn with several tool calls and
a long prompt (system prompt, retrieved chunks, history) reads thousands of
tokens at about 10 tok/s, i.e. minutes per turn. The t1.0 row, measured last,
is faster on both reading and generation; temperature does not change the
speed of the hardware, so this is most likely a machine effect (load, power
state); we do not explain it and do not use it. Accuracy is 100 % for every
setting on this easy set; stability is best at t0 + seed (6/6), as on the pod.

`qwen3-coder:30b` cannot run on this machine.

A first laptop measure was published on 2026-11-01 under the name `qwen3:8b`,
but it had been made with `llama3` (8B); it was withdrawn. The script now writes
the model name returned by Ollama itself, so a measure cannot carry the wrong
model name again.

**To reproduce it:**

```bash
ollama pull qwen3:8b
python scripts/bench_generation.py --host http://localhost:11434 --model qwen3:8b \
    --set basic --think off --out docs/performance/data/generation-laptop-qwen3-8b-2026-11-02.json
```

`--think off` turns off qwen3's reasoning so that the speed of the answer itself
is measured (`--think on` keeps it; its tokens are then counted in
`eval_count`). The model name written in the JSON is the one Ollama reports in
its answers, not the script's argument.

## Limits

- Six short questions in the first run; 22 in the second, still short answers.
  Neither tests long agent turns with tool calls.
- Three runs per setting: a difference of one stable question is not significant.
- The question set has short answers: it measures generation speed well, but
  real turns are dominated by prompt reading, which grows with the context.
