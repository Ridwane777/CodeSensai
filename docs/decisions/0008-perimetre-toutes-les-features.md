# ADR-0008 — Périmètre : implémenter les 28 features du catalogue

- **Statut** : Accepté ; en partie remplacé par ADR-0056 (2026-11-02)
- **Date** : 2026-10-11
- **Décideurs** : Fresnel SATIGNON (Lot A)
- **Lot concerné** : Tous

## Contexte
Le catalogue Sensai (`features_catalog.pdf`) liste 28 features : la base
obligatoire [B1] et 27 features optionnelles réparties en six familles
(Memory, Tools, RAG, Orchestration, Evaluation, UX). Le pré-scope validé au
bootstrap (« CodeSensei ») en retenait 13, dont 4 en bonus, réparties en
lots.

L'exigence communiquée à l'équipe le 2026-10-11 est d'implémenter **toutes**
les features du catalogue. Les 14 features absentes de la répartition
n'avaient donc aucun responsable.

Contrainte : le rendu final est le 2026-11-01, soit trois semaines, et le
sujet impose au moins deux user stories par feature.

## Options envisagées
| Option | Pour | Contre |
| --- | --- | --- |
| Garder le pré-scope (13 features) | Charge tenable, intégration maîtrisée. La page 1 du catalogue dit qu'un groupe avec moins de features bien intégrées est mieux évalué. | Ne répond pas à l'exigence posée à l'équipe. |
| Pré-scope + quelques features ★ peu coûteuses (T4, A5, X2) | Gain rapide, réutilise le code existant. | Ne répond pas non plus à l'exigence. |
| **Les 28 features** | Répond à l'exigence. Couverture complète du catalogue pour la démo. | Charge doublée : 27 features, au moins 54 user stories, en trois semaines. Moins de profondeur par feature, plus de points d'intégration. |

## Décision
On implémente les 28 features. Les 14 manquantes sont réparties par
proximité avec le code de chaque lot, et les 4 bonus deviennent obligatoires :

| Lot | Features ajoutées |
| --- | --- |
| A — Cerveau | A2 Multi-agents, M2 Token Budgeting, A5 Persona, A7 Optimisation de prompts |
| B — Mains | EV1 Évaluation et hallucinations, T4 Accès fichiers, X5 Planification |
| C — Mémoire | R2 RAG avancé, M3 Mémoire structurée, A6 Cache sémantique |
| D — Interface | X2 Branchement/interruption, T3 Recherche web, X3 Export, X4 Questions et formulaires |

## Conséquences
- ✅ Chaque feature du catalogue a un responsable et une échéance (tâches
  ClickUp créées le 2026-10-11, échéances au 18/10 ou au 25/10 selon leurs
  dépendances).
- ✅ Plusieurs ajouts réutilisent l'existant : T4 s'appuie sur la passerelle
  d'outils (ADR-0006), A6 et R2 sur les embeddings du RAG, M3 sur la base
  SQLite de M1.
- ❌ Moins de temps par feature : risque de features présentes mais peu
  approfondies, ce que le catalogue dit pénaliser.
- ❌ Le jalon d'intégration S2 (échéance 04/10) n'est pas atteint : on ajoute
  de la charge alors que les briques de base ne sont pas encore fusionnées.
- ❌ Plus de dépendances entre lots (R2/A6/EV1 attendent R1, M2 attend EV3,
  X2/X4 attendent le flux d'événements et la confirmation web).
- Suivi :
  - faire confirmer l'exigence par écrit au prochain Follow-up ;
  - **seuil de révision** : si au 18/10 les briques A, B et C ne sont pas
    fusionnées dans `main`, écrire un nouvel ADR qui retire en priorité les
    features les moins liées au cas d'usage (X5 Planification, X3 Export,
    A7 Optimisation de prompts) ;
  - user stories dans `docs/user-stories/`, deux par feature au minimum.
