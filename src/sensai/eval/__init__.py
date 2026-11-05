"""
[Lot B — Méric] Évaluation des réponses de l'agent par un juge LLM — feature
[EV1], ADR-0019.

Un second appel au modèle note chaque réponse (pertinence, cohérence, de 1 à 5)
et vérifie, affirmation par affirmation, qu'elle est soutenue par les passages
fournis (fidélité). Les rapports sont des fichiers JSON qui portent leurs
métadonnées, pour qu'on puisse les comparer d'une version à l'autre.

    sensai-eval run --dataset datasets/eval/ev1_sample.jsonl --out rapport.json
    sensai-eval compare rapport_a.json rapport_b.json

Le score du juge est une estimation, pas une mesure : voir
docs/performance/EV1-evaluation.md.
"""
