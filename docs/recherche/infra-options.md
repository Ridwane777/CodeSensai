# Infra Options for Agentic AI

## Laptop specs (for reference)
- CPU: Intel i5-12450H (8 cores / 12 threads)
- RAM: 16GB total (often only ~5GB available under load)
- GPU: NVIDIA GTX 1650 Mobile (4GB VRAM) — driver installed but not currently loaded (Secure Boot likely blocking it)
- Disk: only ~19GB free

**Best local models given this hardware:**
| Model | Size | Notes |
|---|---|---|
| `qwen2.5:7b` / `qwen2.5-coder:7b` | ~4.7GB | Best agentic/tool-use quality at this size, tight but workable |
| `llama3.1:8b` | ~4.9GB | Solid tool-calling support, similar footprint |
| `qwen2.5:3b` / `qwen3:8b` | ~2GB | Fallback if RAM/disk stays tight |

---

## Azure for Students ($100 credit, no card required)

GPU SKUs (NC-series) usually need a quota increase request (support ticket, often approved within a day).

| VM | Specs | Good for |
|---|---|---|
| `Standard_B4ms` | 4 vCPU, 16GB RAM, no GPU | 7B models in CPU mode (Ollama) — usable but slow for agentic loops |
| `Standard_D4s_v5` | 4 vCPU, 16GB RAM, no GPU | Similar, better sustained CPU perf than burstable B-series |
| `Standard_NC4as_T4_v3` | 4 vCPU, 28GB RAM, 1x T4 16GB VRAM | 7B–14B models comfortably in q4/q5 — needs quota approval, burns credit fast (~$0.55/hr → ~180 hrs on $100) |

For agentic work (tool calling, multi-step reasoning), CPU-only inference gets painfully slow for the back-and-forth generations an agent loop needs. Request T4 quota if possible; otherwise `qwen2.5:7b` q4 is the practical ceiling on CPU.

---

## RunPod (pay-per-use GPU rental)

No student discount, but much cheaper per hour than Azure GPU, and no idle billing with serverless or by stopping pods when done.

| GPU | ~$/hr (Community Cloud) | Fits |
|---|---|---|
| RTX 3090 (24GB) | ~$0.20–0.35 | Up to 30B q4 models easily |
| RTX 4090 (24GB) | ~$0.35–0.70 | Same, faster |
| A100 40GB | ~$1.20–1.50 | 30B+ full precision or larger quantized |
| A100 80GB | ~$1.90–2.50 | 70B q4/q5 |

Plus storage if keeping a persistent volume: roughly $0.05–0.10/GB/month.

**Cost example:** ~3 hrs/day agentic dev/testing on an RTX 4090 (~$0.5/hr avg) ≈ **$45/month**. Spin up only for test sessions and it's much less — RunPod bills per-second while the pod is up.

---

## Recommendation

Split the workload:
- **Azure credit** → cheap CPU VM for agent orchestration code (framework, API glue, cron jobs) — doesn't need a GPU, so it's "always-on but light."
- **RunPod** → spin up on-demand only when running inference on a model bigger than the laptop/Azure CPU box can handle — "occasional heavy compute," no idle GPU cost.
