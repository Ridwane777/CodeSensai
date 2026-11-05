# T5 — Sortie structurée : la réponse est-elle fondée sur le projet ?

Mesures du 2026-10-24 sur le pod RunPod (GPU, Ollama), modèle
`qwen3-coder:30b`, client Linux (Python 3.12). Décisions :
[ADR-0036](../decisions/0036-sortie-structuree-format-json-schema.md) et
[ADR-0039](../decisions/0039-sortie-structuree-fondee-sur-le-projet.md).
Tous les chiffres sont mesurés ; l'échantillon est petit (5 essais par
question).

## Reproduire

    python scripts/bench_t5.py <hôte Ollama> [essais]

Le script crée un projet jetable (`stats.py`, `texte.py`, `reglages.py`) et
pose trois questions dont la bonne réponse est connue. « Juste » : les noms de
fonctions attendus (signature ignorée) ou la bonne valeur du port.

## Résultats (5 essais par question)

| Question | Appel direct (ADR-0036) | Deux temps (ADR-0039) |
| --- | --- | --- |
| Fonctions de `stats.py` (une seule : `maximum`) | 0/5 — inventées (`mean`, `median`, `mode`…) | 5/5 |
| Fonctions de `texte.py` (`compter_mots`, `inverser`) | 0/5 — inventées | 5/5 |
| Port de `reglages.py` (8042) | 0/5 — 5000, 8080… | 5/5 |
| **Total** | **0/15**, 0,9 à 3,9 s | **15/15**, 3,7 à 15,8 s |

## Réglage trouvé en route

Premier passage en deux temps : 5 sur 9, puis 8 sur 9 une fois le contrôle
corrigé (il refusait `inverser(phrase)` au lieu de `inverser`). Le dernier
échec venait de la mise en forme : l'agent avait trouvé les deux fonctions,
mais le JSON rendait une liste vide. La consigne « ne laisse un champ vide que
si l'information n'y figure vraiment pas » l'a corrigé : 15 sur 15 ensuite.

## Limites

- Trois questions simples sur un petit projet ; un seul modèle.
- La mise en forme recopie la réponse de l'agent : une erreur de l'agent
  passe dans le JSON.
- Les noms gardent la forme écrite par l'agent (avec ou sans signature).
