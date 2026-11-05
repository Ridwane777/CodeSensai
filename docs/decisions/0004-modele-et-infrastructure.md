# ADR-0004 — Modèle et infrastructure : qwen3:8b en dev, qwen3-coder:30b sur RunPod

Date : 2026-09-22
Lot concerné : Tous
Statut : accepté — reprend le choix de docs/recherche/model-choices.md (Méric), validé en équipe

## Contexte
Aucune machine de l'équipe ne peut faire tourner un modèle agentique correct :
la config de référence ([infra-options.md](../recherche/infra-options.md)) a 4 Go de VRAM,
16 Go de RAM et 19 Go de disque libre. Or une boucle ReAct enchaîne plusieurs
générations par tour de conversation — ce qui est juste lent en chat devient
inutilisable quand chaque appel d'outil coûte une génération complète.

Méric a mesuré le terrain dans deux documents : [infra-options.md](../recherche/infra-options.md)
(Azure for Students, RunPod, coûts horaires) et [model-choices.md](../recherche/model-choices.md)
(BFCL, SWE-bench Verified, VRAM, taux d'hallucination, fenêtre de contexte,
limité aux modèles 2025/2026). Cet ADR ne refait pas ce travail : il transforme
sa conclusion en décision, pour qu'elle s'applique au code plutôt que de rester
dans un document que personne n'ouvre.

## Options considérées
- **Un seul modèle partout** — plus simple à expliquer, mais soit on prend un
  modèle assez petit pour la machine la plus faible (et on démontre l'agent sur
  un modèle qui rate ses appels d'outils), soit on impose à chacun un pod GPU
  payant en permanence, y compris pour écrire du code qui n'appelle jamais le
  modèle.
- **Deux modèles, un par usage** — retenu.

## Décision
- **Développement au quotidien : `qwen3:8b`.** ~5 Go en Q4, itération rapide,
  tool calling natif supporté par Ollama. C'est le défaut de `config.json` et
  de `DEFAULT_MODEL`.
- **Validation et démo : `qwen3-coder:30b`** (Qwen3-Coder-30B-A3B) sur un pod
  RunPod RTX 3090/4090, atteint via `--host http://<ip-du-pod>:11434`.
  Meilleur rapport qualité/VRAM sur une carte 24 Go, orienté agent, 256K de
  contexte pour les longues chaînes d'appels d'outils.
- **Second choix à A/B tester : `nemotron-3-nano:30b`** — même palier de VRAM,
  score BFCL publié sur le test v4 (plus dur), contexte 1M.
- **Écartés : Gemma 3 27B** (pas de tool calling natif dans Ollama),
  **DeepSeek-R1-Distill-Qwen-32B** (entraîné pour le raisonnement, pas pour
  l'appel d'outils), **DeepSeek-V3.2** (671B, hors de portée en auto-hébergé).
- Le pod RunPod ne tourne que pendant les sessions de test : facturation à la
  seconde, ~13-20 $/mois à 3 h/jour, contre ~5 $/jour pour un pod laissé allumé.

## Conséquences
- **Le host Ollama n'est plus supposé local.** `--host` et `config.json` sont
  les seuls points à changer pour basculer entre la machine de dev et le pod :
  aucune ligne de `core/ollama_client.py` ne bouge. C'est ce qui permet aux
  trois lots de coder sur `qwen3:8b` sans pod allumé.
- **Contrainte forte sur ADR-0003** : la décision d'utiliser le tool calling
  natif d'Ollama n'est tenable que si le modèle configuré le supporte. Les deux
  modèles retenus le supportent, et c'est précisément le motif d'exclusion de
  Gemma 3 — les deux ADR disent la même chose. À vérifier au démarrage plutôt
  que de laisser l'agent échouer en pleine session.
- Une fonctionnalité validée sur `qwen3:8b` peut se comporter autrement sur
  `qwen3-coder:30b`. Ne pas découvrir l'écart la veille de la démo :
  passer sur le pod dès que la boucle ReAct enchaîne deux outils.
- Le pod est joignable en HTTP sur le réseau : ne pas l'exposer sans filtrage,
  une instance Ollama ouverte est une API de génération ouverte à tous.
