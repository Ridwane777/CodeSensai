# ADR-0035 — Interface web réelle : serveur FastAPI `sensai-web`, même agent que le CLI

- **Statut** : Accepté (2026-11-01, validé par l'équipe)
- **Date** : 2026-10-18
- **Décideurs** : Ridwane (avec l'accord de Christopher, lot D)
- **Lot concerné** : D (interface web) ; touche C (mémoire, RAG, cache), B (confirmation web, ADR-0015) et A (contrat d'événements)
- **Remplace en partie** : [ADR-0020](0020-interface-web-simulee.md) (l'interface ne tourne plus seulement sur un moteur simulé) ; s'appuie sur [ADR-0022](0022-transport-sse-et-modele-d-execution.md), [ADR-0023](0023-acces-a-l-api-web.md) et [ADR-0024](0024-extensions-du-contrat-web.md)

## Contexte
L'interface du lot D (`frontend/`) est complète, mais elle joue des scénarios
écrits à l'avance (`MockEngine`, ADR-0020). Le serveur web n'existe pas :
`src/sensai/web/` est vide, et il n'y a qu'un prototype jetable
(`docs/conception/web_facade_spike.py`, 15 tests). Le `HttpEngine` du
navigateur est un squelette « non branché ».

Ce qui existe et doit être réutilisé tel quel : la boucle d'agent et ses
événements (lot A, `to_wire`), la confirmation web (`WebConfirmationBroker`,
lot B, ADR-0015), les sessions (`SessionStore`, M1) et toutes les features
de `main` : RAG avec reclassement (R2), cache (A6), faits (M3), `SENSAI.md`
(M4), lecture des documents (#64), garde-fous (EV2).

Les décisions de transport (SSE, agent dans un thread), d'accès (jeton, écoute
locale) et d'extensions du contrat sont déjà prises (ADR 0022 à 0024) et
vérifiées par le prototype. Il reste à choisir comment livrer le vrai serveur.

## Options envisagées
| Option | Pour | Contre |
| --- | --- | --- |
| Garder l'interface simulée | Aucun travail | Ne prouve rien de l'intégration ; l'équipe veut une vraie interface |
| `http.server` de la bibliothèque standard | Aucune dépendance | Pas de flux asynchrone propre, tout le routage et la validation à écrire ; c'est ce que FastAPI fait déjà |
| Flask | Connu, simple | Synchrone : un flux SSE par tour bloque un worker, et la confirmation attend dans le même processus (ADR-0022) |
| **FastAPI + Uvicorn** (retenu) | Ce que proposaient ADR-0022 et le prototype testé ; flux asynchrone, validation des entrées (pydantic), client de test | Trois dépendances directes (fastapi, uvicorn, et httpx pour les tests) et leurs dépendances |

**Comment assembler l'agent côté serveur**

| Option | Pour | Contre |
| --- | --- | --- |
| Reprendre l'agent minimal du prototype | Simple | Le web n'aurait ni RAG, ni cache, ni mémoire, ni garde-fous d'entrée : deux produits différents |
| Extraire l'assemblage du CLI dans un module partagé | Une seule source | Réécrit le CLI (UI, interruption, tests existants) juste avant la démo : risque de régression |
| **Un module `web/runtime.py` qui assemble les mêmes pièces que le CLI** (retenu) | Mêmes outils, mêmes règles, même stockage ; le CLI n'est pas touché | L'assemblage est écrit deux fois : un changement du CLI doit être reporté (tests de parité pour le détecter) |

## Décision
1. **`sensai-web`** lance un serveur FastAPI sur `127.0.0.1` (ADR-0023). Il
   génère un jeton aléatoire, l'affiche une fois dans la console, et sert
   aussi l'interface construite (`frontend/dist`) : même origine, donc pas de
   CORS par défaut. Les options du CLI (`--model`, `--host`, `--no-rag`…)
   s'appliquent.
2. **Même agent que le CLI** : le registre partagé, la recherche dans le
   projet, `update_state`, `save_fact` et `recall_facts`, la passerelle avec
   les garde-fous, le filtre d'entrée, le cache sémantique, et les sessions
   enregistrées dans `~/.sensai/sessions.db`. Une session web est une session
   du CLI : on peut la reprendre d'un côté ou de l'autre.
3. **Le flux** est celui du lot A (`to_wire` : `token`, `thought`,
   `tool_call`, `tool_return`, `error`, `done`), plus les extensions de
   l'ADR-0024 que le serveur peut produire sans toucher au cœur :
   `done.reason = "interrupted"`, `confirm_request` (broker du lot B),
   `rag_sources`, `cache_hit` et `guardrail` (entrée bloquée).
4. **Le navigateur traduit** ce flux vers le modèle d'affichage de
   l'interface, dans un adaptateur unique (`frontend/src/engine/wire.ts`).
5. **Les routes** suivent `web-api.md`, avec les corrections relevées dans
   `web-api-alignement.md` (`confirm_id`) : sessions (créer, lister, lire),
   message (flux SSE), confirmation, interruption, bifurcation (`fork` = une
   nouvelle session), export filtré des secrets, santé, configuration sans
   adresse ni chemin, profil, faits et document d'état en lecture.
6. **Au démarrage**, les sessions trop anciennes sont purgées comme dans le
   CLI (`--retention-days`) : c'est l'issue #65.
7. **Ce qui reste simulé**, et affiché comme tel : la consommation de jetons
   (`usage`), la compression, les notes d'évaluation, le passage entre
   agents, les questions par formulaire (`ask_user`), les personas et le lien
   de partage. Sans serveur joignable, l'interface repasse en démonstration.

## Conséquences
- ✅ Une vraie interface : chaque réponse vient du vrai agent, avec les mêmes outils, mémoires et garde-fous que le CLI.
- ✅ Les sessions sont partagées entre le CLI et le web.
- ✅ Une seule commande (`sensai-web`) sert l'API et l'interface : pas de CORS, pas de deuxième serveur.
- ❌ L'assemblage de l'agent existe en deux exemplaires (CLI et web) ; des tests de parité le surveillent, mais un oubli reste possible.
- ❌ Trois dépendances de plus (FastAPI, Uvicorn, httpx en dev), avec leurs dépendances (starlette, pydantic, anyio…).
- ❌ Un seul utilisateur à la fois par jeton, sur la machine locale : pas de comptes, pas d'accès distant sans option explicite.
- ❌ Plusieurs pages de l'interface (agents, qualité, prompts, planification) restent des démonstrations.
- Suivi : tests de l'API et du flux (`tests/web/`), tests de l'adaptateur (`frontend/tests/`), essai réel sur le pod dans un navigateur. À revoir pour partager l'assemblage avec le CLI après la démo.
