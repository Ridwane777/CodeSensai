# ADR-0024 — Extensions du contrat du Lot A : ce qu'on demande, et quoi faire si c'est refusé

- **Statut** : Accepté (2026-11-01, validé par l'équipe)
- **Date** : 2026-10-14
- **Décideurs** : Valentino (Lot D), à valider par Fresnel (Lot A)
- **Lot concerné** : D (impacte A pour trois ajouts au cœur)

## Contexte
Écrit **après** les user stories [US-WEB-6 à 12, 16](../architecture/web-api.md). Les features X2 (interruption,
bifurcation), X3 (export, partage), X4 (questions), EV3 (journal) et M1 (profil) ont besoin de comportements que le
contrat du Lot A ne décrit pas (section 3 de [web-api-alignement.md](../architecture/web/web-api-alignement.md)). Sans décision explicite,
l'interface les simulerait en silence, ou chaque lot inventerait sa propre version.

Principe : [ADR-0005](0005-interface-web-facade.md) autorise à compléter `core/` quand il manque quelque chose, mais
tout ajout au cœur est une demande au Lot A et un effet sur la CLI. On n'y touche donc **que ce qui ne peut pas se
faire ailleurs**.

## Options envisagées
| Option | Pour | Contre |
| --- | --- | --- |
| Tout mettre dans le cœur | Un seul endroit, la CLI en profite | Sept demandes au Lot A, dont certaines sans rapport avec le cœur (export, partage) |
| Tout mettre dans le serveur web | Aucune demande au Lot A | Impossible : une interruption ou une consommation de tokens se connaissent dans le cœur |
| **Minimum au cœur, le reste dans le serveur, avec un repli pour chaque extension** | Ne dépend du Lot A que là où c'est inévitable ; chaque story reste vérifiable si une demande est refusée | Plus de surface d'API à sécuriser et à tester |

## Décision
**Trois demandes au cœur (Lot A) :**
1. `Done.reason` accepte `"interrupted"` ; le serveur expose `POST /interrupt`.
2. Un événement `usage` (`prompt_tokens`, `completion_tokens`, `duration_ms`), lu dans le dernier morceau de la réponse d'Ollama.
3. `ToolReturn.data` (optionnel) transporte `ToolResult.data` (sources, traceback, différences de fichier).

**Cinq ajouts au serveur, sans toucher au cœur :**
4. **Bifurcation = nouvelle session** : `POST /fork {"at_message": n}` copie l'historique jusqu'au message `n`. Une branche est une session ordinaire.
5. **Question = outil** : l'agent demande par un outil `ask_user` (risque `read`) ; le serveur émet `question` et attend `POST /answer`, comme pour la confirmation. Le cœur ne connaît pas l'interface.
6. **Export** : `GET /export?format=json|md`, filtré des secrets ; le PDF reste côté navigateur.
7. **Partage** : voir [ADR-0023](0023-acces-a-l-api-web.md).
8. **Profil, configuration, santé** : routes simples au-dessus de `Profile` et de la configuration existantes.

**Repli si une demande est refusée** (chaque story le décrit) : l'interface coupe sa connexion pour interrompre ; estime la consommation en la signalant comme estimée ; n'affiche que le `content` des outils ; garde les branches en mémoire de page.

## Conséquences
- ✅ Seules trois demandes touchent au cœur, et chacune est justifiée par une story.
- ✅ Chaque extension a un repli : la démonstration reste honnête si le Lot A refuse.
- ❌ **Dépend du temps et de l'accord du Lot A**, alors que le rendu approche ; sans réponse, l'interface garde des comportements simulés pour X2, X4 et EV3.
- ❌ **Plus de surface à sécuriser** : chaque route ajoutée est une porte de plus (jeton, validation, filtrage).
- ❌ **Une branche qui est une session** encombre la liste des sessions, et une bifurcation copie l'historique (coût mémoire et disque proportionnel).
- ❌ **`ask_user` oblige le modèle à savoir quand demander** : si le modèle ne l'utilise pas, le formulaire ne s'affiche jamais, quel que soit le travail de l'interface. À mesurer, pas à supposer.
- Suivi : réponses du Lot A aux questions 1 à 3 de [web-api-alignement.md](../architecture/web/web-api-alignement.md) ; `docs/architecture/web/simule-vs-reel.md` à mettre à jour à chaque extension branchée. **Seuil de révision** : si le Lot A refuse les trois demandes au cœur, remplacer ce plan par les replis et le dire à la démo.
