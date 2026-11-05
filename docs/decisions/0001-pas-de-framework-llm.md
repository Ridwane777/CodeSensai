# ADR-0001 — Pas de framework LLM, appels HTTP bruts à Ollama

Date : 2026-09-21
Lot concerné : Tous
Statut : accepté — contrainte du sujet

## Contexte
Le sujet Sensai interdit explicitement l'usage de frameworks LLM
(LangChain, LlamaIndex, Haystack ou équivalent) et impose que tous les
appels au modèle passent par l'API HTTP d'Ollama directement.

## Options considérées
- Utiliser un framework malgré tout et le justifier au Keynote — écarté,
  contrevient directement à une contrainte obligatoire du sujet.
- Construire une petite couche d'abstraction maison au-dessus de `requests`
  — retenu.

## Décision
Tous les appels au modèle passent par `core/ollama_client.py`, qui wrappe
`requests` en HTTP brut. Aucune dépendance à un framework d'orchestration
LLM n'est ajoutée à `requirements.txt`.

## Conséquences
- On code nous-mêmes le streaming, la gestion d'historique et le
  function-calling (via `core/tools.py`) — plus de travail, mais c'est
  explicitement l'objectif pédagogique du module.
- Le client Ollama reste petit et entièrement lisible par les 3 membres de
  l'équipe (test de profondeur du bootstrap).
