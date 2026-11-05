# ADR-0032 — RAG avancé : recherche hybride, fusion RRF et reclassement par le modèle (R2)

- **Statut** : Accepté
- **Date** : 2026-10-17
- **Décideurs** : Ridwane (lot C), choix délégué puis appuyé sur une mesure
- **Lot concerné** : C (Mémoire) ; aucun autre lot impacté (l'outil `search_codebase` garde son nom)

## Contexte
R1 retrouve les passages par la seule similarité des embeddings (bge-m3).
Il rate les noms exacts (`FactStore`, `memory.db`) et le bon fichier n'arrive
pas assez souvent en premier. R2 demande un reclassement, des filtres par
métadonnées et un score par passage (US-R2-1 à 3).

Contraintes : pas de framework LLM, Ollama 0.40.6 **n'a pas de `/api/rerank`**
(404 mesuré), et une seule machine GPU (le pod) partagée avec le modèle de chat.

Mesure (`scripts/bench_rerank.py`, index réel, fichiers qui contiennent les
questions exclus) sur 15 questions de R1 et 10 questions tenues à part,
écrites avant la mesure :

| Méthode | R1 : 1er / top 5 / MRR | Tenu à part : 1er / top 5 / MRR | s/question |
| --- | --- | --- | --- |
| dense (R1) | 5 / 12 / 0,54 | 3 / 8 / 0,51 | 1,1–1,7 |
| BM25 | 6 / 11 / 0,55 | 4 / 7 / 0,52 | 1,2 |
| hybride RRF | 7 / 15 / 0,67 | 3 / 7 / 0,49 | 1,2 |
| hybride + modèle | 12 / 15 / 0,88 | 7 / 9 / 0,76 | 4,4 |

## Options envisagées
| Option | Pour | Contre |
| --- | --- | --- |
| Garder le dense seul (R1) | Aucun travail, rapide | 5/15 en 1re position |
| BM25 seul | Pas d'embeddings, trouve les noms exacts | Pas de synonymes, pas mieux que le dense |
| Hybride BM25 + dense, fusion RRF (k=60, Cormack et al. 2009) | Rapide, sans réglage, 15/15 dans le top 5 sur R1 | Gain nul sur le jeu tenu à part |
| Cross-encoder dédié (bge-reranker) | Méthode standard, rapide une fois chargé | Ollama ne l'expose pas : il faudrait un serveur de plus ou torch en local |
| Hybride puis reclassement des 10 premiers par le modèle de chat, en un seul appel | Seul gain net sur les deux jeux (1er : 5→12 et 3→7) ; aucune dépendance de plus | +3 s par recherche, charge le modèle de chat |

## Décision
Hybride BM25 + embeddings fusionné par RRF, puis le modèle de chat reclasse les
10 premiers passages (réponse JSON). Si le modèle échoue (délai, JSON invalide),
on garde l'ordre de la fusion. Le reclassement se coupe par configuration.

## Conséquences
- ✅ Le bon fichier arrive en premier 12 fois sur 15 (contre 5) et 7 fois sur 10 sur le jeu tenu à part (contre 3).
- ✅ Aucune nouvelle dépendance : BM25 et RRF font environ 80 lignes en Python pur.
- ❌ Environ 3 s de plus par recherche, et un appel de plus au modèle de chat (coût GPU).
- ❌ Le résultat dépend du modèle de chat : un autre modèle demandera une nouvelle mesure.
- ❌ Le seuil de score (US-R2-3) a une marge très faible : la meilleure question sans réponse atteint 0,53 et la plus faible vraie question 0,553.
- ❌ L'index BM25 est recalculé en mémoire au chargement (acceptable pour quelques milliers de passages, à revoir au-delà de ~50 000).
- Suivi : `docs/performance/R2-rag.md`, `scripts/bench_rerank.py`. À revoir si Ollama ajoute `/api/rerank` ou si le délai devient gênant.
