# ADR-0013 — Brancher l'outil de recherche du projet sur l'index ouvert par le CLI

- **Statut** : Accepté (2026-11-01, validé par l'équipe)
- **Date** : 2026-10-14
- **Décideurs** : Ridwane (lot C)
- **Lot concerné** : C ; A impacté (`cli.py`, où chaque lot enregistre ses outils)

## Contexte
L'ADR-0009 (décision 4) prévoit deux façons de donner le projet au modèle :
les passages ajoutés automatiquement à chaque question, et un outil,
`search_codebase` (`RagTool`), que le modèle appelle lui-même pendant la
boucle ReAct. Cet outil attendait la boucle (A1), arrivée dans `main` le
2026-10-14 (PR #12 et #13). Il reste à l'enregistrer dans le CLI.

Deux contraintes :
- **L'index n'existe pas au démarrage.** Le CLI ne l'ouvre qu'à la première
  question (ADR-0009, décision 5), pour ne pas imposer l'indexation à qui ne
  tape que des commandes. Or l'outil est enregistré au démarrage.
- **La passerelle coupe un outil au bout de 120 s** (`tool_timeout_s`,
  ADR-0006). La première indexation du dépôt (134 fichiers) a pris 4 min 30
  lors de l'essai réel du 2026-10-13, sur le pod RunPod.

## Options envisagées
| Option | Pour | Contre |
| --- | --- | --- |
| A. Indexer au démarrage, puis enregistrer l'outil avec l'index | Le plus simple à comprendre | Revient sur l'ADR-0009 : plusieurs minutes d'attente sur un nouveau projet, même pour taper `/profile` |
| B. L'outil indexe lui-même au premier appel | Démarrage instantané | La première indexation dépasse les 120 s de la passerelle : l'appel échoue, et l'indexation continue en arrière-plan en même temps que celle du CLI, sur la même base |
| **C. L'outil réutilise l'index que le CLI ouvre à la première question** (retenu) | Démarrage instantané. Le CLI indexe déjà avant de passer la main à l'agent : l'outil ne fait jamais d'indexation, donc jamais de délai dépassé. Le moins de code | L'outil dépend du CLI pour recevoir son index : une autre interface (le web, lot D) devra faire de même |

## Décision
`RagTool` est enregistré au démarrage **sans index**. À la première question,
le CLI ouvre l'index (comme aujourd'hui), puis le donne à l'outil, avant
d'appeler l'agent. Avec `--no-rag`, l'outil n'est pas enregistré : l'agent ne
le voit pas. L'outil déclare le risque `read`.

Ses réponses ont leur propre présentation (« Recherche "…" : n passages »),
sans la consigne des passages ajoutés automatiquement, qui dit qu'ils peuvent
être hors sujet. Il suit `--rag-min-score`, mais pas `--rag-top-k` : ce
réglage limite ce qui est ajouté à chaque question, et l'outil renvoie
toujours jusqu'à 5 passages. Ces deux points viennent de l'essai réel du
2026-10-14 : avec `--rag-top-k 1`, l'outil ne renvoyait que le passage du
README, et le modèle a répondu `qwen3:8b` au lieu de `bge-m3`.

## Conséquences
- ✅ Le démarrage reste instantané, et l'agent peut chercher dans le projet
  autant de fois qu'il veut, avec ses propres mots.
- ✅ Une seule indexation, faite au même endroit qu'aujourd'hui : aucun accès
  concurrent à la base.
- ✅ Avec le risque `read`, la passerelle l'autorise sans confirmation, comme
  `read_file`. Sans risque déclaré, elle le traitait comme une exécution et
  aurait demandé une confirmation à chaque recherche.
- ❌ Si l'indexation échoue (Ollama ou `bge-m3` indisponible), le CLI coupe la
  recherche pour la session : l'outil reste visible pour l'agent mais répond
  « Recherche indisponible ». Le modèle doit alors continuer sans.
- ❌ Chaque interface qui utilise l'agent devra donner l'index à l'outil :
  à signaler au lot D pour le web.
- ❌ La première question d'un nouveau projet reste lente (indexation), comme
  avec R1 aujourd'hui.
- ❌ Le modèle n'appelle pas toujours l'outil : quand les passages ajoutés
  automatiquement suffisent, il répond directement (observé lors de l'essai
  réel). C'est voulu, mais la démonstration demande une question qui les
  dépasse.
- Suivi : tests du CLI (l'outil reçoit l'index, il n'est pas proposé avec
  `--no-rag`, il ignore `--rag-top-k`) et de l'outil (risque `read`, sa propre
  présentation). Essai réel sur le pod le 2026-10-14 : le modèle a appelé
  `search_codebase` de lui-même, sans confirmation demandée.
