# CodeSensai costs

This document separates what is **measured** from what is **estimated**. Each
estimate gives its method and assumptions, so it can be corrected with a real
figure (invoice, timesheet). Written on 2026-10-25.

## 1. Measured

| Item | Value | Source |
| --- | --- | --- |
| Project duration | 2026-09-22 → 2026-10-24 (33 calendar days) | `git log` |
| Team | 4 people | `git shortlog` |
| Activity | 291 commits, 42 merged PRs | `git log`, GitHub |
| Software and model licences | **€0**: Ollama (MIT), `qwen3-coder:30b` and `qwen3:8b` (Apache-2.0), MIT / Apache-2.0 libraries | [licenses.md](../legal/licenses.md) |
| Paid third-party services | **€0**: no API key; web search without an API ([ADR-0040](../decisions/0040-duckduckgo-web-search-with-bing-fallback.md)) | code, `docs/dependencies.md` |
| Run times | cold model load: 47 to 80 s; one agent turn: 4 to 90 s depending on the task | [trial run of 2026-10-24](../performance/trials/trial-2026-10-24.md) |

**Not measured**: the actual GPU spend. It is on the team's RunPod invoice,
which is not in the repository: report it here to replace estimate 2.1.

## 2. Estimated

### 2.1 GPU during development (RunPod)

- **Rate**: RunPod bills per second while a pod is running. Public price list
  checked on 2026-10-25 for a 24 GB GPU on Community Cloud: RTX 3090 or
  RTX A5000 ≈ $0.22/h, RTX 4090 ≈ $0.44/h; on Secure Cloud, about double
  (RTX 4090 ≈ $0.69/h). Source:
  [runpod.io/gpu-cloud/pricing](https://www.runpod.io/gpu-cloud/pricing).
- **Hours** (assumption): pods mostly on during trial runs, about 2 to 4 h per
  trial day, over 10 to 15 trial days, i.e. **20 to 60 hours**. Replace with
  the invoice total.
- **Estimate**: 20 h × $0.22 ≈ **$4** at the low end; 60 h × $0.69 ≈
  **$41** at the high end. Order of magnitude: **a few tens of dollars** for
  the whole project. Pod storage (models ≈ 20 GB) adds to it while the pod
  exists.

### 2.2 Development time

- **Method**: 4 people, 33 calendar days, alongside other commitments.
  Assumption: 2 to 4 h per person per working day (24 working days).
- **Estimate**: 4 × 24 × 2 to 4 h = **190 to 380 person-hours**.
- **Valuation** (indicative, for the business plan): at the cost of a junior
  developer in France, €35 to €45 per loaded hour (assumption), i.e.
  **€6,700 to €17,100**. It is by far the largest cost item.

### 2.3 Running cost for a user

CodeSensai is designed to run **locally**, for a single developer.

| Set-up | Direct cost | Assumptions |
| --- | --- | --- |
| Machine with a 24 GB GPU (30B model) | €0 of service; electricity | hardware already owned |
| Modest machine + `qwen3:8b` | €0 of service | smaller model: a feature validated on it may behave differently than with the 30B (ADR-0004); no comparative measurement in the repository |
| GPU rented by the hour (RunPod, Community) | ≈ $0.22 to $0.44/h of use | pod stopped when unused; 2 h per working day ≈ $9 to $18/month |

### 2.4 What other choices would cost

| Change | Extra cost | When it is justified |
| --- | --- | --- |
| Web search API (Brave Search API) | subscription and quota (check the price when choosing) | as soon as usage goes beyond a non-commercial project (retrospective, item 5) |
| Weekly end-to-end trial run on the pod | ≈ 1 GPU hour per week, i.e. $0.22 to $0.69 | always (retrospective, item 2) |

## 3. How to correct this document

1. Replace the hours assumption in 2.1 with the RunPod invoice total.
2. Replace 2.2 with a timesheet if the team kept one.
3. Recheck the rates in 2.1 and 2.4 on the update date (they change).
