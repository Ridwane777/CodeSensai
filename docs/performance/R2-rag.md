# R2 — RAG avancé : mesures

> **Latest trial, 2026-11-06** ([report](essais/essai-2026-11-06.md)), qwen3:8b on the team laptop (CPU) and qwen3-coder:30b on a 24 GB GPU pod: the end-to-end RAG scenario passes with both models (see R1); the ranking measurements below are not redone by that trial. Earlier measurements below.

Décision : [ADR-0032](../decisions/0032-rag-hybride-et-reclassement.md).
User stories : [R2-advanced-rag.md](../user-stories/R2-advanced-rag.md).
Script : [`scripts/bench_rerank.py`](../../scripts/bench_rerank.py).

## Méthode

- **Date** : 2026-10-17.
- **Machines** : client sur un portable Intel i7-1355U (12 fils). Ollama 0.40.6 sur un pod RunPod, avec `bge-m3` (embeddings) et `qwen3-coder:30b` (reclassement).
- **Index** : le dépôt lui-même, découpé comme en R1, soit **2 001 passages**. On retire de l'index les fichiers qui contiennent les questions ou leurs réponses attendues (`docs/performance/`, les scripts de mesure, les user stories R2) : sinon la recherche trouverait la question au lieu de la réponse.
- **Questions** :
  - les 15 questions de R1 (`scripts/bench_rag.py`) ;
  - 10 questions **tenues à part**, écrites avant toute mesure et portant sur le code arrivé après R1. Elles servent à vérifier que le choix ne vaut pas seulement sur le jeu de R1 ;
  - les 3 questions **sans réponse** de R1 (Kafka, Stripe, e-mails).
- **Critères** :
  - bon fichier en 1re position ;
  - bon fichier dans les 5 premiers ;
  - MRR (1 / rang du bon fichier, en moyenne) ;
  - secondes par question.

```bash
python scripts/bench_rerank.py --host <hôte Ollama> --out r2.json   # les 4 variantes
python scripts/bench_rerank.py --host <hôte Ollama> --production    # le code livré
```

## Comparaison des variantes (seuil désactivé, 50 candidats)

| Méthode | R1 : 1er / top 5 / MRR | Tenu à part : 1er / top 5 / MRR | s/question |
| --- | --- | --- | --- |
| dense (R1 tel quel) | 5 / 12 / 0,541 | 3 / 8 / 0,514 | 1,07–1,74 |
| BM25 seul | 6 / 11 / 0,551 | 4 / 7 / 0,519 | 1,17–1,20 |
| hybride (RRF, k = 60) | 7 / 15 / 0,669 | 3 / 7 / 0,492 | 1,18–1,25 |
| hybride + reclassement par le modèle | **12 / 15 / 0,883** | **7 / 9 / 0,759** | 4,36–4,43 |

**Attention à la comparaison avec R1.** R1 annonçait 11/15 en 1re position.
Ici, le même dense obtient 5/15, parce que les documents de mesure (qui
recopiaient les questions) sont exclus de l'index. Les deux chiffres ne se
comparent pas. Toute la comparaison de R2 se fait dans les mêmes conditions,
avec ces fichiers exclus.

## Le code livré (`--production`)

Configuration : `RagIndex.search` avec `LlmReranker`, le seuil par défaut
0,54 et 5 passages, comme dans le CLI.

| Jeu | 1er | top 5 | s/question |
| --- | --- | --- | --- |
| R1 (15) | 11 | 13 | 4,13 |
| Tenu à part (10) | 8 | 9 | 4,58 |
| Sans réponse (3) | 0 passage pour chacune ✅ | | |

Critères des user stories :
- **US-R2-1** : battre les 11/15 de R1. La comparaison honnête se fait contre le dense dans les mêmes conditions, soit 5/15 → 11/15, et 3/10 → 8/10 sur le jeu tenu à part.
- **US-R2-3** : aucun passage n'est renvoyé pour les 3 questions sans réponse.

Le code livré obtient 13/15 dans le top 5, contre 15/15 pour la variante sans
seuil : avec le seuil à 0,54, deux questions perdent leur bon passage avant le
reclassement. C'est le prix à payer pour ne rien renvoyer aux questions sans
réponse.

## Le seuil

| | Score dense |
| --- | --- |
| Meilleur passage, questions sans réponse | 0,437 ; 0,503 ; **0,530** |
| Meilleur passage, les 3 vraies questions les plus faibles | **0,553** ; 0,558 ; 0,570 |

Le seuil passe de 0,50 à **0,54**, entre les deux. **La marge n'est que de
0,02 :** une autre formulation de question peut tomber du mauvais côté. Avec
3 questions sans réponse, l'échantillon est trop petit pour fixer le seuil
plus finement. On peut le régler avec `--rag-min-score`.

## Limites et suites

- **Le temps :** le reclassement ajoute environ 3 s à chaque question, puisque la recherche automatique tourne à chaque tour. `--no-rag-rerank` (ou `"rag_rerank": false` dans `config.json`) le coupe.
- **Le modèle :** les résultats valent pour `qwen3-coder:30b`. Un autre modèle de chat demande une nouvelle mesure.
- **La taille des jeux :** 25 questions, c'est peu. Un point de différence correspond à une seule question.
- **BM25 recalculé :** l'index BM25 est recalculé en mémoire après chaque mise à jour (2 001 passages, un temps imperceptible). À revoir au-delà de quelques dizaines de milliers de passages, par exemple avec SQLite FTS5.
- **Pas encore mesuré :** l'effet des filtres `kind` et `path` sur la qualité. Ils sont seulement testés en unitaire.
