# ADR-0038 — Multi-Agent Orchestration : agents spécialisés et passage de relais

- **Statut** : Accepté (2026-10-24)
- **Date** : 2026-10-24
- **Décideurs** : Ridwane (lot C) et Fresnel (lot A)
- **Lot concerné** : A (`tools/`, `prompts/`) ; impacte D (`web/runtime.py`)
  et l'exécution des outils de Meric (`execution/gateway.py`)

## Contexte

[ADR-0037](0037-delegation-sous-agent-outil.md) a livré `delegate_task` :
l'agent principal lance un sous-agent générique. Comparé au texte du
catalogue, ça ne suffit pas pour A2 :

> *Multi-agent orchestration has several **specialized** agents coordinate on
> a task, **passing work between them**.* (exemples : chercheur, rédacteur et
> critique dans CrewAI ; agents qui débattent dans AutoGen ; routeur LLM)

Tous les sous-agents étaient identiques (même prompt, mêmes outils) et
aucun ne recevait le travail d'un autre. Les essais sur le pod
(`qwen3-coder:30b`, détail dans
[`docs/performance/A2-orchestration.md`](../performance/A2-orchestration.md))
ont aussi montré cinq défauts de la version de l'ADR-0037 :

| Défaut mesuré | Chiffre |
| --- | --- |
| Le sous-agent ignore le prompt du projet (profil, faits) | fait retenu retrouvé 1 fois sur 3 sans, 3 sur 3 avec |
| La profondeur 2 fait tourner en rond | 120 s pour une réponse vide (3 redélégations) |
| Le sous-agent continue après l'abandon par la passerelle | 20 s de travail fantôme ; une écriture demandée 14 s après l'abandon |
| L'agent ne délègue jamais de lui-même (description seule) | 0 délégation sur 10 demandes |
| Le relecteur croit le développeur sur parole | travail faux validé 6 fois sur 6, sans ouvrir le fichier |

## Options envisagées

| Option | Pour | Contre |
| --- | --- | --- |
| Garder le seul `delegate_task` générique (ADR-0037) | Rien à ajouter | Ne correspond pas au sujet : ni spécialisation, ni passage de relais |
| Un framework multi-agent (CrewAI, AutoGen, LangGraph) | Rôles et relais tout faits | Interdit par le projet (pas de framework LLM, API HTTP d'Ollama seulement) ; contournerait la passerelle ADR-0006 |
| Rôles dans `delegate_task` + une chaîne fixe `team_task` (explorateur → développeur → relecteur, une correction au plus) | Réutilise la boucle ReAct et la même passerelle ; chaque rôle ne voit que ses outils ; chaîne déterministe, donc testable sans modèle | Chaîne figée (pas de débat libre) ; plus lente qu'un agent seul ; tout doit tenir dans le délai d'un outil |
| Des agents qui débattent librement (style AutoGen) | Plus souple | Nombre de tours imprévisible, difficile à borner dans 120 s, confirmations A3 imbriquées |
| Routeur de modèles (petit modèle pour les demandes simples) | Coût et latence plus bas | Demande un second modèle chargé sur le pod (mémoire GPU) : pas mesuré, reporté |

## Décision

1. **Agents spécialisés** : `delegate_task` prend un `role` parmi
   `explorateur` (lit et cherche), `developpeur` (peut écrire et exécuter,
   avec confirmation) et `relecteur` (lit et juge). Chaque rôle a ses
   consignes et **ne voit que ses outils** ; un appel hors rôle est refusé
   sans être exécuté.
2. **Passage de relais** : `team_task` enchaîne explorateur → développeur →
   relecteur ; chaque agent reçoit le travail du précédent. Le relecteur
   reçoit le **contenu exact écrit** par le développeur (capturé sur les
   appels `write_file`), pas seulement son compte rendu. S'il répond
   « À CORRIGER », le travail revient une fois au développeur. Chaque relais
   s'affiche dans le terminal.
3. **Corrections de l'ADR-0037** :
   - le sous-agent reçoit le prompt du projet ;
   - il ne redélègue pas (`MAX_DELEGATION_DEPTH = 1`, outils de délégation
     masqués) ;
   - il s'arrête à son échéance (120 s moins 30 s de marge) : plus d'outil ni
     de confirmation après, réponse partielle renvoyée, générateur refermé ;
   - la passerelle copie le contexte dans le thread de l'outil
     (`contextvars.copy_context()`), sans quoi la profondeur repartait de 0.
4. **Quand s'en servir** : règles dans le prompt système `v2` (registre A4) :
   déléguer à partir de trois fichiers, confier une modification de code à
   l'équipe, répondre soi-même à une question.

Le routeur de modèles n'est pas retenu pour l'instant (voir Suivi).

## Conséquences

- ✅ A2 correspond au texte du sujet : trois agents spécialisés qui se passent
  le travail, avec une critique qui peut renvoyer au développeur.
- ✅ Aucune nouvelle dépendance ; mêmes garde-fous et confirmations pour tous
  les agents (ADR-0006, A3, EV2) ; un rôle en lecture seule ne peut pas
  écrire, même si le modèle le tente.
- ✅ Chaîne déterministe : testée sans modèle (`tests/tools/test_team_tool.py`).
- ❌ Plus lent : une modification par l'équipe prend plusieurs fois le temps
  de l'agent seul (chiffres dans le document de mesures). On paie la
  vérification.
- ❌ Choix du modèle, pas garanti : les règles du prompt `v2` sont suivies
  dans la plupart des essais, pas tous (voir le document de mesures).
- ❌ Toute la chaîne tient dans le délai d'un seul outil (120 s par défaut) :
  une tâche longue s'arrête avant la fin, en le disant.
- ❌ Le relecteur ne juge que ce que le développeur a écrit avec
  `write_file` ; une modification faite autrement (par `run_code`) ne lui est
  pas montrée.
- Suivi : mesurer un routeur de modèles si un second modèle tient sur le pod ;
  revoir le délai si les tâches de l'équipe dépassent souvent 90 s. Si cet ADR
  est accepté, l'ADR-0037 passe au statut « Remplacé en partie par
  ADR-0038 » (seule sa ligne de statut change).
