"""
[Workstream B - Meric] Evaluation of the agent's answers by an LLM judge - feature
[EV1], ADR-0019.

A second model call scores each answer (relevance, coherence, 1 to 5) and
checks, claim by claim, that it is supported by the supplied passages
(faithfulness). Reports are JSON files that carry their metadata, so they can
be compared from one version to the next.

    sensai-eval run --dataset datasets/eval/ev1_sample.jsonl --out report.json
    sensai-eval compare report_a.json report_b.json

The judge's score is an estimate, not a measurement: see
docs/performance/EV1-evaluation.md.
"""
