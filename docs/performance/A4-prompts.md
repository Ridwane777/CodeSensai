# Essai réel — [A4] Prompt Versioning

Ce document garde la trace de la vérification d'A4 avec un vrai modèle, en
plus des tests automatiques (`tests/knowledge/test_prompt_versions.py`,
`tests/test_prompt_cli.py`, `tests/test_config.py`,
`tests/test_prompts_registry.py`). Choix :
[ADR-0010](../decisions/0010-versionnement-des-prompts.md).

## Ce qui est vérifié
La Definition of Done : montrer l'historique des prompts système et revenir à
une ancienne version en une commande — et surtout que **changer de version
change réellement le comportement de l'agent**, puis que le retour en arrière
le rétablit.

## Machine et réglages
- VPS de l'équipe, 8 vCPU, 23 Go de RAM, **sans GPU**.
- Ollama 0.40.3 installé pour l'essai dans un dossier dédié, sans sudo, puis
  entièrement désinstallé (processus, dossier, clé `~/.ollama`, cache pip de
  l'essai).
- Modèle `qwen3:8b` (modèle de développement, ADR-0004), préchargé avant la
  première question.
- `sensai --no-rag --new-session` : RAG coupé et session vierge, pour isoler
  l'effet du prompt.
- Une copie du dossier `prompts/` de la branche : la `v2` d'essai n'est pas
  entrée dans le dépôt.

## Scénario
Même question à chaque lancement, posée en anglais : « What is a Python
decorator? Answer in two sentences. »

1. Lancement avec la version livrée (`system v1`).
2. `sensai-prompt show system > brouillon.txt`, ajout d'une ligne,
   `sensai-prompt save system brouillon.txt "impose le français…"`,
   `sensai-prompt diff system v1 v2`, `sensai-prompt use system v2`.
3. Lancement avec `system v2`.
4. Retour en arrière : `sensai-prompt use system v1`, puis lancement.

Différence entre v1 et v2, affichée par `sensai-prompt diff` :

```
@@ -9,3 +9,4 @@
 - Si tu ne sais pas, dis-le plutôt que d'inventer.
+- Réponds toujours en français, même si la question est posée dans une autre langue.
```

## Résultats (2026-10-12)

| Étape | Ligne affichée au lancement | Réponse (début) | Durée du lancement |
|---|---|---|---|
| 1. v1 | `prompts : system v1, memory v1` | « A Python decorator is a function that wraps another function… » (anglais) | 150 s |
| 3. v2 | `prompts : system v2, memory v1` | « Un décorateur en Python est une fonction qui enveloppe une autre fonction… » (français) | 101 s |
| 4. retour à v1 | `prompts : system v1, memory v1` | « A Python decorator is a function that wraps another function… » (anglais) | 106 s |

`sensai-prompt history system` après l'essai :

```
  v2  2026-10-12  Ridwane777        impose le français dans toutes les réponses
  v1  2026-09-22  fresnel-cyber     prompt initial (repris de prompts/system_prompt.txt)  (active)
```

`sensai-prompt check` : « Registre cohérent ». **La DoD est atteinte** : la
v2 n'a pas été effacée par le retour en arrière, et une seule commande a
suffi dans chaque sens.

## Limites
- Un scénario, une exécution par version : l'essai montre que le mécanisme
  agit sur le modèle, pas un taux de réussite.
- La durée inclut le démarrage du CLI et la génération sur CPU ; elle ne mesure
  pas A4, dont les commandes répondent instantanément.
- La consigne testée (la langue) a un effet facile à observer ; l'effet d'un
  changement plus fin demande une évaluation sur plusieurs questions (EV1),
  prévue dans les évolutions de l'ADR-0010.
