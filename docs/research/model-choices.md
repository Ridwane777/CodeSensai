# Model Choices for Sensai

Constraint from the project spec: all calls must go through the **Ollama HTTP API** directly (no LangChain/LlamaIndex/etc.), so we're picking among open-weight models runnable locally via `ollama pull`/`ollama run`.

## Criteria
- BFCL (Berkeley Function-Calling Leaderboard)
- Best efficient VRAM
- Lower hallucination rate
- Strong context window
- 2025/2026 models

## Scorecard against the 4 criteria

| Model | BFCL | VRAM (Q4_K_M) | Hallucination rate (Vectara HHEM) | Context window |
|---|---|---|---|---|
| Qwen3-Coder-30B-A3B | **69.1 (v3)** | ~19GB | not found (Qwen3-8B same-family proxy: 4.8%) | 256K native, extendable to 1M (YaRN) |
| Nemotron 3 Nano 30B-A3B | 53.76 (v4, harder test) | ~22.5GB | 9.6% | **1M native** |
| Devstral Small 2 24B | not published | **~14–19GB** (lowest of the 24-30B tier) | not found | 256K |
| Gemma 3 27B-IT | 59.1 (v3) / 29.5 (v4) | ~17GB | **4.4%** (12B same-family proxy - likely best-in-class) | 128K, no native Ollama tool-calling |
| Qwen3-8B | not found (8B-specific) | ~5GB (most efficient, but too small for agent core) | 4.8% | 128K-256K |
| DeepSeek-V3.2 | not comparable | too large to self-host (671B) | reported low, close to top models, no exact % found | 128K+ |
| DeepSeek-R1-Distill-Qwen-32B | not found | ~20GB | not found | 128K (reasoning distill, not tool-tuned) |

Reading this against the 4 criteria:
- **BFCL**: Qwen3-Coder-30B-A3B wins on a published number, but it's the easier v3 test - Nemotron's 53.76 is on the harder v4, so the two aren't a fair head-to-head.
- **VRAM efficiency**: Devstral Small 2 is the most efficient in the 24-30B tier (~14GB at Q4_K_M), meaning it could run with headroom to spare on a 24GB card - worth it if the extra margin matters for concurrent sessions or a bigger KV cache.
- **Hallucination rate**: no direct scores exist for the 24-30B checkpoints we care about; Gemma 3 and Qwen3 have the best numbers, but only at smaller (8-12B) sibling sizes, so treat this as a weak family-level signal, not a hard guarantee at 27-30B.
- **Context window**: Nemotron 3 Nano wins outright with a native 1M window; everything else tops out at 128K-256K native.

No single model wins on all 4 - see trade-off call below.

## Relevant benchmarks

There's no single "official" agentic benchmark - coverage differs by model/vendor. The three that matter for Sensai:

- **BFCL (Berkeley Function-Calling Leaderboard)** - closest thing to a standard for tool/function calling specifically. Covers single-call, multi-call, parallel calls, and multi-turn (agentic) tool use.
- **SWE-bench Verified** - standard for agentic *coding*: can the model autonomously fix a real GitHub issue using tools/file edits/tests. Most relevant if we build a sandboxed code-execution feature.
- **τ-bench (tau-bench)** - multi-turn agentic tool use with a simulated user and policy-following checks. Most relevant for multi-turn tutoring/state-tracking features.

## Scores gathered (web search, Sept 2026)

| Model | BFCL | SWE-bench Verified | τ-bench | Notes |
|---|---|---|---|---|
| Qwen3-Coder-30B-A3B | ~69.1 (BFCL v3, base Qwen3-30B-A3B figure) | not separately published for this checkpoint | not found | MoE, 3.3B active params, ~19GB at Q4_K_M, 256K context |
| Devstral Small 2 (24B) | not published | **68.0%** | not found | Best hard agentic-coding number at this size class; matches much larger models |
| Devstral (original) 24B | not published | 46.8% | not found | Superseded by Devstral Small 2 |
| Qwen3-8B | not found (no clean 8B-specific number) | not benchmarked this way (not a coding-agent model) | not found | 2025 release, dense, ~5GB at Q4_K_M - fine for dev/orchestration, not for evaluating agentic features |
| Nemotron 3 Nano 30B-A3B | **53.76 (BFCL v4)** | not found | not found | MoE, 3.5B active, ~22.5GB VRAM at Q4_K_M, 1M context, runs via Ollama. BFCL v4 is a harder/newer test than v3, so not directly comparable to the Qwen3 v3 number above |
| Gemma 3 27B-IT | 59.1 (BFCL v3) / 29.5 (BFCL v4) | not found | not found | No native Ollama tool-calling - needs custom prompt/modelfile hacks to get function calling working at all. Weaker fit for an agentic project |
| DeepSeek-V3.2 | not directly comparable (framework-dependent, 72–74 range reported) | 72–74% (varies by eval harness) | not found | 671B MoE - far too large to self-host on our infra (24–80GB GPU tier); relevant only if we ever use a hosted API instead of Ollama |
| DeepSeek-R1-Distill-Qwen-32B | not found | not found | not found | Strong at math/reasoning (AIME, MATH-500) but not tuned or benchmarked for tool-calling - reasoning distill, not an agent model |

Caveat: vendors don't run every model through every benchmark, so this table has real gaps - not a clean apples-to-apples comparison. Treat SWE-bench Verified as the most trustworthy signal we have (hard, third-party-reproducible number) and BFCL as the second most trustworthy. Note BFCL v3 and v4 scores are not directly comparable to each other (v4 is harder).

Scoped to 2025/2026 releases only: Qwen3 family (2025), Qwen3.6 (2026), Devstral / Devstral Small 2 (2025), Gemma 3 (2025), DeepSeek-V3.2 (Dec 2025) and R1-Distill (2025), Nemotron 3 Nano (Dec 2025). Older generations (Qwen2.5, Devstral original's predecessor, etc.) are excluded from the recommendation below.

## Recommendation by infra

Per [infra-options.md](infra-options.md) (Azure free credit + RunPod split):

- **RunPod, RTX 3090/4090 (24GB)** → `qwen3-coder:30b` - best quality-per-GB on a 24GB card, purpose-built for tool-use/agentic workflows, 256K context gives headroom for long tool-call chains.
- **RunPod, A100 40/80GB** → could step up to `qwen3.6-27b` dense or larger, but `qwen3-coder:30b` likely already covers Sensai's needs - don't overspend RunPod budget on a model that won't be saturated.
- **Alternative on 24GB** → `nemotron-3-nano:30b` (Nemotron 3 Nano 30B-A3B) is a viable second option at the same VRAM tier, with a published BFCL v4 score (53.76) and a 1M context window. Worth an A/B test against `qwen3-coder:30b` since Qwen's number is on the older/easier BFCL v3.
- **Not recommended**: Gemma 3 27B (no native Ollama tool-calling, weaker BFCL scores) and DeepSeek-R1-Distill-Qwen-32B (reasoning-tuned, not tool-calling-tuned) for the agentic core. DeepSeek-V3.2 (671B) is out of reach for self-hosting on this infra entirely.
- **Azure T4 16GB (after GPU quota approval)** → too tight for `qwen3-coder:30b`; use `qwen3:8b` for orchestration/dev testing.
- **Azure CPU-only box (B4ms/D4s_v5)** → glue code only (FastAPI server, SQLite, cron), no inference - CPU-only generation is too slow for agentic multi-turn loops.

## Cost estimate: Qwen3-Coder-30B-A3B on RunPod

`qwen3-coder:30b` needs a 24GB card at minimum (~19GB at Q4_K_M), so pricing is for RunPod Community Cloud RTX 3090/4090 (Sept 2026):

| GPU | $/hr | 3hrs/day × 20 days (dev+testing) | 8hrs one-off (demo prep) |
|---|---|---|---|
| RTX 3090 (24GB) | $0.22/hr | **$13.20/month** | $1.76 |
| RTX 4090 (24GB) | $0.34/hr | **$20.40/month** | $2.72 |

Plus persistent storage if keeping a volume to avoid re-downloading the ~19GB model each session: **$1.75-2.50/month** for a 25GB volume at $0.07-0.10/GB/month. Skip the volume for infrequent use - the download itself is free, only pod uptime costs money.

Realistic total for the whole project: **$15-30** on an RTX 3090, **$25-45** on a 4090, assuming most glue/dev work happens on the free Azure CPU box and the GPU pod is only up for active agentic-feature testing. Billing is per-second, so stopping the pod between sessions (not just leaving it idle) is what keeps this near the low end - an idle-but-running pod on a 3090 still burns ~$5.30/day.

## Practical workflow

1. Develop and iterate against `qwen3:8b` locally or on the Azure CPU box for fast feedback.
2. Validate the final feature set against `qwen3-coder:30b` on a RunPod pod before the demo.
3. Spin the RunPod pod up only for active test sessions to control cost (billed per-second).
4. If a code-execution/self-correcting-agent feature is built, benchmark that path against `devstral:24b` (Devstral Small 2) as an alternative - it has the strongest published SWE-bench Verified number in this size class.

## Sources

- [Qwen3 Coder 30B A3B - Artificial Analysis](https://artificialanalysis.ai/models/qwen3-coder-30b-a3b-instruct)
- [Devstral 2: The best open-weights model for agentic coding - Cline](https://cline.bot/blog/devstral-2-release)
- [Devstral | Mistral AI](https://mistral.ai/news/devstral/)
- [AI Agent Tool Calling Benchmarks on GPU Cloud: BFCL v4, tau-Bench - Spheron](https://www.spheron.network/blog/tool-calling-benchmarks-bfcl-tau-bench-latency-optimization/)
- [Best Ollama Models 2026: 25+ Ranked by VRAM & SWE-Bench - Morph](https://www.morphllm.com/best-ollama-models)
- [Best Ollama Models for AI Agents 2026: Ranked by Tool Use - LocalAIMaster](https://localaimaster.com/blog/best-ollama-models-for-agents)
- [Best Open-Source LLM Models in 2026 - Hugging Face blog](https://huggingface.co/blog/daya-shankar/open-source-llms)
- [Best Ollama Models for Tool Calling: BFCL Ranked (2026) - LocalAIMaster](https://localaimaster.com/blog/best-ollama-models-tool-calling)
- [Gemma 3 27B Benchmark Scores & Evals - BenchmarkList](https://benchmarklist.com/models/google-gemma-3-27b-it/)
- [DeepSeek-V3.2: Pushing the Frontier of Open Large Language Models (arXiv)](https://arxiv.org/pdf/2512.02556)
- [Nemotron 3 Nano: Open, Efficient MoE Hybrid Mamba-Transformer Model for Agentic Reasoning (arXiv)](https://arxiv.org/pdf/2512.20848)
- [Nemotron 3 Nano 30B VRAM Requirements - WillItRunAI](https://willitrunai.com/models/nemotron-3-nano-30b)
- [DeepSeek R1 Distill Qwen 32B - Artificial Analysis](https://artificialanalysis.ai/models/deepseek-r1-distill-qwen-32b)
- [Vectara Hallucination Leaderboard (Hugging Face Space)](https://huggingface.co/spaces/vectara/leaderboard)
- [Nemotron 3 Nano: Complete Guide to Pricing, Context Window, Benchmarks & API - llm-stats](https://llm-stats.com/blog/research/nemotron-3-nano-launch)
- [Devstral Small 2 24B - specs, VRAM, benchmarks - BestLLMfor](https://bestllmfor.com/catalog/devstral-small-2/)
- [Devstral Small 2 24B Instruct VRAM Requirements - WillItRunAI](https://willitrunai.com/models/devstral-small-2-24b)
- [RTX 4090 GPU Rental | Specs and Pricing - Runpod](https://www.runpod.io/gpu-models/rtx-4090)
- [RunPod GPU Pricing: 39 GPUs from $0.12/hr (2026) - gpuperhour.com](https://gpuperhour.com/providers/runpod)
- [RunPod Pricing in 2026: What GPU Cloud Actually Costs - Flexprice](https://flexprice.io/blog/runprod-pricing-guide-with-gpu-costs)
