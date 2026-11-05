# Architecture — CodeSensei

État au 2026-10-14 (`main`, après #73). Les décisions sont dans
[decisions/](../decisions/README.md) ; ce document décrit ce que fait le code.

## Use case
Un développeur seul (ou en petite équipe) sur un projet long, qui veut un
assistant capable de : se souvenir du contexte du code d'une session à
l'autre, exécuter et corriger du code de façon autonome, et expliquer son
raisonnement de façon transparente — tout en demandant confirmation avant
toute action risquée et sans jamais laisser fuiter de secrets.

## Vue d'ensemble

```
 sensai (CLI)        sensai-schedule (X5)        interface web (lot D, à venir)
      │                     │                          │
      └──────────┬──────────┴──────────────────────────┘
                 │  les mêmes événements : Token, Thought, ToolCall, ToolReturn, Error, Done
                 ▼
        Agent ReAct — core/agent.py                         lot A (A1)
        appelle le modèle → lit tool_calls → appelle un outil → recommence (6 appels max)
                 │  tool calling natif d'Ollama (ADR-0003)
                 ▼
        Passerelle — execution/gateway.py                   lot B (ADR-0006)
        politique de risque · validation des arguments · garde-fous EV2 ·
        confirmation A3 · délai (120 s) · nettoyage et validation du résultat
                 │
                 ▼
        Registre d'outils — core/tools.py + registry.py     contrat Tool commun (ADR-0002)
   ┌─────────────┬──────────────┬──────────────┬──────────────┬─────────────────┐
 run_code      read_file      write_file     web_search     search_codebase
 (T2, Docker)  (T4)           (T4)           (T3, Chromium  (R1, lot C, ajouté
                                              Docker, Bing)  par le CLI)
                 │
                 ▼
        Ollama (HTTP brut, core/ollama_client.py) : qwen3:8b en dev,
        qwen3-coder:30b et bge-m3 sur un pod RunPod pour la validation (ADR-0004)
```

Autour de la boucle :
- **Mémoire** (`knowledge/memory.py`, M1) : sessions et profil dans
  `~/.sensai` (SQLite), reprises au démarrage ; le profil est ajouté au
  prompt système.
- **RAG** (`knowledge/rag.py`, R1) : index du projet dans `~/.sensai/rag.db`,
  ouvert à la première question ; les meilleurs passages sont joints à chaque
  question, et l'outil `search_codebase` permet à l'agent de chercher lui-même
  (ADR-0009, ADR-0013). Les PDF, documents Office et EPUB sont convertis en
  Markdown dans un conteneur `sensai-docs` (`execution/sandbox/document_sandbox.py`)
  avant d'être indexés, et `read_file` les lit de la même façon ;
  `knowledge/documents.py` identifie le type d'un fichier par son contenu (ADR-0034). Depuis R2 (`knowledge/retrieval.py`, ADR-0032), chaque
  recherche fusionne les embeddings et BM25 (RRF), puis le modèle de chat
  reclasse les 10 premiers passages.
- **Document d'état** (`knowledge/state_document.py`, M4) : `SENSAI.md` dans
  le projet, ajouté au prompt système, modifié section par section par
  l'outil `update_state` ; journal et annulation dans `~/.sensai/state/`
  (ADR-0029).
- **Mémoire de faits** (`knowledge/facts.py`, M3) : triplets entité,
  attribut, valeur dans `~/.sensai/memory.db`, enregistrés par `save_fact`
  (confirmé) et retrouvés par `recall_facts` ; le prompt système liste les
  entités connues (ADR-0030).
- **Serveur web** (`web/runtime.py`, `web/server.py`, `web/cli.py`, X1) :
  `sensai-web` assemble le même agent que le CLI et l'expose en HTTP (flux
  SSE d'un tour, confirmation, interruption, branches, export) ; il sert
  aussi l'interface `frontend/` (ADR-0035).
- **Cache des réponses** (`knowledge/cache.py`, A6) : questions, réponses et
  empreintes des fichiers lus dans `~/.sensai/cache.db` ; une question proche
  (bge-m3, seuil 0,90, sans action ni nom différents) reçoit la réponse sans
  appel au modèle de chat (ADR-0033).
- **Prompts versionnés** (`knowledge/prompt_versions.py`, `prompts/`, A4) :
  l'agent charge la version active de chaque prompt (ADR-0010).
- **Outils d'équipe**, hors conversation : `sensai-prompt` (A4),
  `sensai-eval` (EV1, juge LLM, ADR-0019), le corpus adversarial
  `tests/adversarial/` (EV4, ADR-0018).

## Composants et responsabilités

| Composant | Fichier(s) | Lot | Rôle |
|---|---|---|---|
| Client Ollama | `core/ollama_client.py` | A | Appels HTTP bruts, streaming, outils dans le champ `tools` |
| Historique | `core/history.py` | A | Contexte de conversation envoyé au modèle |
| Agent (ReAct) | `core/agent.py` | A | Boucle d'appels d'outils, au plus 6 appels au modèle par tour |
| Événements | `core/events.py` | A | Ce qu'un tour émet — contrat CLI ↔ web ([api-contract.md](web/api-contract.md), [web-api.md](web/web-api.md)) |
| Contrat Tool, registre | `core/tools.py` | A | Protocole `Tool`, `ToolRegistry` |
| Registre partagé | `registry.py` | tous | Outils proposés au CLI et au planificateur : une ligne par outil |
| Passerelle | `execution/gateway.py`, `tool_policy.py`, `tool_validation.py`, `output_sanitizer.py` | B | Tout appel d'outil passe par elle ([tool-contract.md](tool-contract.md)) |
| Confirmation | `execution/human_in_loop.py`, `web_confirmation.py` | B | Confirmeur du terminal ; courtier pour le web (ADR-0015) |
| Garde-fous | `execution/guardrails.py` | B | Masquage des secrets et données personnelles (EV2) |
| Permissions fichiers | `execution/file_permissions.py` | B | Dossiers autorisés, fichiers sensibles refusés (ADR-0011) |
| Sandboxes | `execution/sandbox/` | B | Python et Chromium dans des conteneurs jetables ([sandbox.md](sandbox.md)) |
| Outils | `tools/*.py` | B, C | `run_code`, `read_file`, `write_file`, `web_search`, `search_codebase`, `update_state`, `save_fact`, `recall_facts` |
| Planificateur | `scheduling/`, `schedule_cli.py` | B | Tâches à intervalle, sans surveillance ([scheduling.md](scheduling.md)) |
| Évaluation | `eval/` | B | Juge LLM et détection des hallucinations ([EV1](../performance/EV1-evaluation.md)) |
| Mémoire, RAG, prompts | `knowledge/` | C | Sessions et profil, index du projet, registre des prompts |
| Configuration | `config.py` | A | Argument CLI > `config.json` > défaut ; valide les sections `tools` et `files` |
| Interface web | `web/` | D | À venir : façade au-dessus du même cœur (ADR-0005) |
| Outil MCP externe | `tools/mcp_tool.py` | D | Squelette : à écrire |
| Observabilité | `observability/` | D | À venir : journal des tours, alimente l'interface |

## Interfaces — les contrats qui relient les lots

Chaque capacité exposée à l'agent implémente le protocole `Tool`
(`core/tools.py`) :

```python
class Tool(Protocol):
    name: str
    description: str
    parameters: dict          # JSON Schema des arguments
    def run(self, **kwargs) -> ToolResult: ...
```

Un outil déclare aussi son `risk` (`read`, `network`, `write`, `execute`) :
sans risque déclaré, la passerelle le traite comme une exécution. L'agent ne
reçoit jamais le registre brut, seulement la passerelle : c'est elle qui
décide si un appel part, avec quelle confirmation, et ce qui revient au
modèle. Voir [ADR-0002](../decisions/0002-registre-d-outils-partage.md) et
[ADR-0006](../decisions/0006-passerelle-d-outils.md).

Second contrat, pour les interfaces : un tour d'agent émet des
**événements** (`core/events.py`), pas du texte — la CLI les affiche, le
planificateur les résume dans un compte rendu, le web les sérialisera en JSON.
Voir [ADR-0005](../decisions/0005-interface-web-facade.md).

## Contrat interface ⇄ moteur (proposé)

Le Lot D a figé le format d'échange avant d'avoir un backend
([ADR-0005](../decisions/0005-interface-web-facade.md),
[ADR-0020](../decisions/0020-interface-web-simulee.md)). Il est écrit en
TypeScript dans `frontend/src/contract/` et testé dans `frontend/tests/`.
**C'est une proposition, à valider avec le Lot A.**

L'interface ne connaît qu'une interface `Engine` :

| Commande (interface → moteur) | Effet |
|---|---|
| `send`, `interrupt` | envoyer un message ; interrompre la génération en cours |
| `editMessage` | bifurquer depuis un message modifié (branche) |
| `confirm`, `answer` | répondre à une demande de confirmation ou à un formulaire |
| `switchPersona` | changer d'agent sans effacer l'historique |

Le moteur répond par un flux d'événements typés : `turn_start`, `token`,
`thought` / `action` / `observation` (le raisonnement), `confirm_request`,
`question`, `usage`, `compression`, `artifact_patch`, `rag_sources`,
`web_results`, `guardrail`, `eval_score`, `cache_hit`, `agent_handoff`,
`error`, `done`. Deux implémentations : `MockEngine` (scénarios, utilisé par la
démo) et `HttpEngine` (squelette SSE, non branché ; routes `/messages`,
`/interrupt`, `/confirm`, `/answer`, `/persona` à confirmer).

## Pourquoi cette architecture (résumé)

- **`core/` vs `execution/` vs `knowledge/`** : découpage par
  responsabilité, pas par personne — résiste à un changement de répartition.
- **Une passerelle obligatoire entre l'agent et les outils** : les
  protections (confirmation, garde-fous, délais) sont écrites une fois, et
  aucun outil ne peut les oublier.
- **Un registre partagé** : un outil branché une fois arrive au CLI et au
  planificateur ; seule la politique change (confirmation d'un côté, refus
  systématique de l'autre).
- **`prompts/` comme fichiers versionnés, pas comme constantes Python** :
  exigence du Base Loop, et base d'A4.
- **`src/` layout + `pyproject.toml`** : package installable
  (`pip install -e .`), imports propres quel que soit le dossier d'où l'on
  lance les commandes.
- **`tests/` qui reflète `src/`** : chaque lot peut vérifier son module sans
  lancer tout le système.
- **`web/` et `observability/` dans le même lot** : la trace produite par
  l'un est ce que l'autre affiche.

## Décidé depuis la première version de ce document

- Isolation : Docker, conteneurs jetables ([ADR-0012](../decisions/0012-sandbox-docker-chromium.md)).
- Stockage vectoriel du RAG : SQLite + numpy ([ADR-0009](../decisions/0009-rag-sur-la-codebase.md)).
- Tool calling natif d'Ollama ([ADR-0003](../decisions/0003-tool-calling-natif-ollama.md)),
  utilisé par la boucle livrée dans #13.

## Limites connues (à corriger)

- Since 2026-11-01, tool results reach the model wrapped in
  `<tool_output trust="untrusted">` (`core/agent.py`, `fence_untrusted`; former
  gap EV4-OUT-14, [EV4 report](../securite/EV4-tests-adversariaux.md)).
