# ADR-0033 — Cache sémantique prudent : embeddings bge-m3, règles « mots décisifs » et seuil 0,90 (A6)

- **Statut** : Accepté ; modifié par ADR-0056 (2026-11-02 : cache désactivé par défaut)
- **Date** : 2026-10-18
- **Décideurs** : Ridwane (lot C), après mesure et validation du seuil
- **Lot concerné** : C (Mémoire) ; le CLI (fichier partagé) affiche les réponses servies

## Contexte
A6 demande de « mettre en cache les réponses et les servir directement pour
des requêtes sémantiquement proches (comparaison par embeddings), sans appeler
le modèle ». Ce qui se fait ailleurs (Redis LangCache, GPTCache, LiteLLM) :
embeddings, puis un seuil de similarité. Les mêmes sources signalent le
risque principal, le faux positif, et LiteLLM conseille d'exclure du cache les
boucles d'agent et les conversations à plusieurs tours.

Mesure (`scripts/bench_cache.py`) sur deux jeux écrits avant les mesures
concernées : 39 reformulations, qui devraient être servies, et 48 pièges,
qui ne doivent jamais l'être (« taille maximale » et « minimale », « lire » et
« écrire un fichier », « Python » et « JavaScript »).

| Méthode | Seuil sans piège | Reformulations servies | Pièges servis | Appel au modèle de chat |
| --- | --- | --- | --- | --- |
| bge-m3 seul | 0,934 | 4/39 | 0/48 | non |
| qwen3-embedding:0.6b seul | 0,948 | 1/39 | 0/48 | non |
| nomic-embed-text seul | 0,965 | 0/39 | 0/48 | non |
| bge-m3 + règles | 0,876 (retenu : 0,90) | 10/39 (7/39 à 0,90) | 0/48 | non |
| bge-m3 + vérification oui/non par qwen3-coder (jeu 1 seulement) | 0,60 | 21/25 | 1/28 | oui, ~1,2 s |

Avec bge-m3 seul, un piège atteint 0,92 (« taille maximale » et « minimale »),
alors que des reformulations honnêtes descendent à 0,59 : aucun seuil ne
sépare les deux.

## Options envisagées
| Option | Pour | Contre |
| --- | --- | --- |
| Embeddings seuls, seuil bas (0,70) | À la lettre du catalogue ; sert 34/39 reformulations | Sert 34/48 pièges : des réponses fausses avec aplomb |
| Embeddings seuls, seuil sûr (0,934) | À la lettre ; aucune erreur mesurée | Sert 4/39 reformulations : le cache ne sert presque jamais |
| Autre modèle d'embeddings (qwen3-embedding, nomic) | Rien à coder | Mesuré moins bon que bge-m3 |
| Embeddings, puis vérification par le modèle de chat | 21/25 servies | 1 piège servi ; appelle le modèle (contraire à la lettre de la feature) ; ~1,5 s par réponse |
| **Embeddings bge-m3 + règles « mots décisifs », seuil 0,90** | Aucun piège sur les deux jeux ; aucun appel au modèle de chat ; réutilise le modèle du RAG | Sert seulement 7/39 reformulations (18 %) |

Les règles (`knowledge/cache.py`, `conflict`) refusent deux questions qui
n'ont pas les mêmes noms (identifiants du code, mots avec majuscule ou
chiffre) ou pas les mêmes familles d'actions (créer, lire, écrire, supprimer,
activer, désactiver, démarrer, arrêter, augmenter, réduire…).

## Décision
Embeddings bge-m3, règles « mots décisifs », seuil 0,90 (marge au-dessus
du piège le plus fort mesuré, 0,876). Une entrée n'est servie que si elle a le
même projet et le même modèle de chat, n'a pas expiré, et que les fichiers
dont la réponse s'est servie n'ont pas changé. Ne sont jamais mis en cache :
les tours où l'agent a écrit ou exécuté, et les questions qui dépendent de la
conversation.

## Conséquences
- ✅ Aucun piège servi sur 48 mesurés ; aucun appel au modèle de chat pour une réponse servie.
- ✅ Pas de nouveau modèle : bge-m3 sert déjà au RAG.
- ❌ Le cache est prudent : environ une reformulation sur cinq est servie ; les autres repartent vers le modèle.
- ❌ Les règles sont des listes de mots (français et anglais) : un contraire absent de la liste passe si la similarité dépasse 0,90. 48 pièges, c'est peu.
- ❌ L'auteur des règles avait vu les deux jeux : le second a été écrit avant les règles, mais il n'est pas totalement indépendant.
- ❌ Un appel d'embedding de plus par question (quelques dixièmes de seconde).
- Suivi : `docs/performance/A6-cache.md`, `scripts/bench_cache.py`. À revoir si un piège réel passe, ou pour la vérification par le modèle si l'équipe accepte de s'écarter de la lettre de la feature.
