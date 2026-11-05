# ADR-0036 — Sortie structurée via le champ `format` d'Ollama (schéma JSON)

- **Statut** : Accepté
- **Date** : 2026-10-23
- **Décideurs** : Fresnel (Lot A)
- **Lot concerné** : A (`core/`)

## Contexte

[T5] Structured Output demande de pouvoir obtenir du modèle une réponse qui
respecte une forme précise (un objet JSON avec des champs et des types
donnés), pour qu'un programme puisse la consommer sans deviner où est
l'information dans un texte libre.

Le sujet interdit tout framework LLM : la solution doit passer par l'API
HTTP d'Ollama, comme le reste du projet (voir `core/ollama_client.py`).

## Options envisagées

| Option | Pour | Contre |
| --- | --- | --- |
| Demander le JSON dans le prompt (« réponds en JSON avec les champs... ») | Aucun code, aucune dépendance | Pas de garantie : le modèle ajoute du texte autour, oublie un champ, ou écrit du JSON invalide. Mesuré sur `qwen3-coder` : rate une fois sur trois sur une demande à 4 champs. |
| Champ natif `format` de l'API `/api/chat` d'Ollama (JSON Schema ou `"json"`) | Le décodage du modèle est contraint token par token : la sortie respecte la forme du schéma à coup sûr (noms de champs, types). Déjà le mécanisme utilisé pour le tool calling natif (ADR-0003) — même famille d'API. | Nécessite une version récente d'Ollama ; ne garantit que la *forme*, pas que les *valeurs* aient un sens ; ne se mélange pas avec les outils dans le même appel (voir Décision). |
| Valider après coup avec la bibliothèque `jsonschema` | Validation plus fine (formats, bornes numériques) | Nouvelle dépendance pour un problème que `format` résout déjà à la source ; ADR supplémentaire à écrire pour la justifier (règle du dépôt sur les dépendances majeures). |

## Décision

On utilise le champ `format` de l'API `/api/chat` d'Ollama, en lui passant le
schéma JSON demandé. `stream_chat_messages` (ADR existant sur
`ollama_client.py`) gagne un paramètre optionnel `format` qu'on transmet tel
quel dans le payload, exactement comme `tools`.

La sortie structurée est un appel **séparé** de la boucle ReAct
(`core/structured.py`, `run_structured_query`) : un seul aller-retour, sans
outils. Mélanger tool calling et `format` contraint dans le même appel n'est
pas un comportement documenté et stable de l'API Ollama ; séparer les deux
évite de deviner lequel gagne.

Exposée dans le chat via `/structured <fichier-schéma.json> <prompt>`, sur
le modèle des commandes `/schedule` et `/eval` (ADR-0028) : une commande qui
appelle le cœur (Lot A) sans passer par la boucle d'agent.

## Conséquences

- ✅ Garantie structurelle (noms de champs, types, imbrication) fournie par
  Ollama lui-même, sans dépendance supplémentaire.
- ✅ Même mécanisme que le tool calling natif (ADR-0003) : rien de nouveau à
  apprendre côté client HTTP, juste un champ de payload en plus.
- ❌ Pas de validation sémantique (un entier dans la bonne fourchette, un
  format de date correct, une valeur d'énumération respectée) : `format`
  garantit la forme, pas le sens. Si ça devient nécessaire, ce sera un
  nouvel ADR pour `jsonschema`, pas une réécriture de celui-ci.
- ❌ Suppose une version d'Ollama qui comprend `format` en JSON Schema (pas
  seulement `"json"`) ; sur une version trop ancienne, l'appel échoue ou
  Ollama ignore silencieusement la contrainte — `run_structured_query` lève
  `StructuredOutputError` si la réponse n'est malgré tout pas du JSON valide,
  mais ne peut pas distinguer ce cas d'un modèle indiscipliné.
- Suivi : si un schéma avec contraintes fines (regex, min/max, enum) est
  réellement nécessaire pour une feature du catalogue, réévaluer `jsonschema`
  à ce moment-là plutôt que par anticipation.
