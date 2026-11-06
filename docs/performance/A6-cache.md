# A6 — Cache sémantique : mesures et essai réel

> **Latest trial, 2026-11-06** ([report](essais/essai-2026-11-06.md)), qwen3:8b on the team laptop (CPU) and qwen3-coder:30b on a 24 GB GPU pod: same question twice with the cache on: qwen3:8b on CPU 5 min 37 then **0.5 s** from the cache; qwen3-coder:30b on GPU 9.0 s then **1.8 s**. Identical question only: the rephrasing measurements below still stand. Earlier measurements below.

Décision : [ADR-0033](../decisions/0033-cache-semantique-prudent.md).
User stories : [A6-semantic-cache.md](../user-stories/A6-semantic-cache.md).
Script : [`scripts/bench_cache.py`](../../scripts/bench_cache.py).

## 1. Le seuil : reformulations contre pièges

**Méthode** (2026-10-18). Ollama 0.40.6 sur un pod RunPod, client sur un
portable Intel i7-1355U.

- **Questions** : deux jeux de questions de développeurs. Chaque question
  d'origine est accompagnée de reformulations, qui devraient être servies,
  et de pièges, qui ne doivent jamais l'être : même thème, mais une autre
  action, un autre objet ou un autre nom.
- **Jeu 1** (25 reformulations, 28 pièges) : écrit avant toute mesure.
- **Jeu tenu à part** (14 reformulations, 20 pièges) : écrit après la
  première mesure, mais avant d'écrire les règles.
- **Mesure** : similarité cosinus entre la question d'origine et chaque
  autre question.

```bash
python scripts/bench_cache.py --host <hôte Ollama> --model bge-m3 --out a6.json
```

**Résultat 1 : les embeddings seuls ne séparent pas les deux.**

| bge-m3 | Score |
| --- | --- |
| Piège le plus fort : « taille **maximale** » / « taille **minimale** d'un fichier indexé » | 0,925 |
| Puis « **lire** » / « **écrire** un fichier avec l'agent » | 0,907 |
| Puis « **activer** » / « **désactiver** le mode debug » | 0,895 |
| Reformulation la plus faible : « activer le mode debug » / « avoir plus de logs » | 0,588 |

**Résultat 2 : trois modèles d'embeddings, avec ou sans les règles.** Pour
chaque ligne, on prend le seuil le plus bas qui ne sert aucun piège sur les
deux jeux réunis (48 pièges), puis on compte les reformulations servies.

| Modèle | Seuls : seuil, reformulations servies | Avec les règles : seuil, reformulations servies |
| --- | --- | --- |
| **bge-m3** | 0,934 ; 4/39 | **0,876 ; 10/39** |
| qwen3-embedding:0.6b | 0,948 ; 1/39 | 0,862 ; 9/39 (première version des règles) |
| nomic-embed-text | 0,965 ; 0/39 | 0,908 ; 5/39 (première version des règles) |

Les règles (`knowledge/cache.py`, `conflict`) refusent deux questions dont
les noms (identifiants du code, mots avec majuscule ou chiffre) ou les
familles d'actions (créer, lire, écrire, supprimer, activer, désactiver,
démarrer, arrêter, augmenter, réduire…) diffèrent. Après la mesure des trois
modèles, « combien » et « nombre » ont été retirés de la famille
« compter » : ce sont des mots interrogatifs, qui bloquaient des
reformulations honnêtes. bge-m3 a été remesuré avec les règles corrigées
(tableau 3) ; les deux autres modèles ne l'ont pas été.

**Résultat 3 : bge-m3 et les règles corrigées, selon le seuil** (les deux
jeux réunis).

| Seuil | Reformulations servies | Pièges servis |
| --- | --- | --- |
| 0,70 | 19/39 | 8/48 |
| 0,80 | 16/39 | 5/48 |
| 0,85 | 12/39 | 2/48 |
| **0,90 (retenu)** | **7/39 (18 %)** | **0/48** |
| 0,94 | 2/39 | 0/48 |

Le seuil est fixé à 0,90 plutôt qu'au minimum mesuré (0,876, « que retourne
`load_settings` » / « quels paramètres prend `load_settings` »), pour garder
une marge sur des questions jamais vues.

**Variante écartée : la vérification par le modèle de chat.** Les embeddings
proposent un candidat, puis qwen3-coder répond oui ou non à la question
« même question ? ». Sur le jeu 1, elle sert 21/25 reformulations et 1/28
piège, en ~1,2 s de plus. Elle est écartée parce qu'elle appelle le modèle,
ce qui va contre la lettre de la feature, et parce qu'elle sert 1 piège
(ADR-0033).

## 2. Essai réel dans le CLI (2026-10-18)

`sensai --model qwen3-coder:30b --host <pod>` lancé dans ce dépôt (2 235
passages indexés), avec cinq entrées à la suite :

| Entrée | Résultat |
| --- | --- |
| « Comment lancer les tests du projet ? » | Réponse du modèle en 16,8 s, enregistrée |
| La même question | **Servie depuis le cache** (similarité 1,00), avec la question d'origine et sa date |
| « Comment je lance les tests du projet ? » | **Servie depuis le cache** (similarité 0,92) |
| « Comment ignorer un test qui échoue ? » (piège) | **Non servie** : réponse du modèle (`@pytest.mark.skip`…) en 11,3 s |
| `/cache` | « 2 réponse(s) en mémoire, servie(s) 2 fois, environ 34 s gagnées » |

**Temps d'une réponse servie** : la même consultation (`AnswerCache.lookup`)
a été répétée 10 fois sur la base de l'essai. Médiane **1,06 s**, maximum
1,37 s, contre 16,8 s pour la réponse du modèle. Presque tout ce temps est
l'aller-retour vers le pod pour l'embedding de la question, à travers le
proxy HTTPS de RunPod ; la recherche dans la base est négligeable.

## 3. Critères des user stories

| Critère | État |
| --- | --- |
| US-A6-1 : une reformulation servie en moins d'une seconde, sans appel au modèle de chat | **Non atteint pour le temps** : 1,06 s en médiane avec le pod distant. L'appel au modèle de chat est bien évité. Avec Ollama sur la même machine, l'aller-retour réseau disparaît (non mesuré ici) |
| US-A6-1 : taux de réponses servies mesuré | 7/39 reformulations (18 %) au seuil retenu |
| US-A6-2 : aucun piège servi | 0/48 au seuil 0,90 |
| US-A6-2 : invalidation quand un fichier source change | Testé (`tests/knowledge/test_cache.py`) |
| US-A6-2 : pas de cache après une écriture ou une exécution, ni pour une question qui dépend de la conversation | Testé (seuls `read_file` et `search_codebase` sont admis ; `standalone`) |
| US-A6-3 : mention, question d'origine et date ; `/again`, `/cache`, `/cache clear` | Vu dans l'essai réel et testé |

## 4. Limites

- **Un cache prudent** : environ une reformulation sur cinq est servie. Les synonymes absents des listes (« passer en » pour « activer ») font refuser une vraie reformulation.
- **Des jeux petits** : 48 pièges et 39 reformulations. Un contraire absent des listes passe si la similarité dépasse 0,90.
- **Des jeux pas totalement indépendants** : l'auteur des règles avait vu les deux jeux. Le second a été écrit avant les règles.
- **Les défauts sont resservis** : une réponse en cache est rejouée telle quelle, défauts compris. Dans l'essai, la première réponse citait à tort un test sur `sujet.pdf`. `/again` redemande au modèle et remplace l'entrée.
- **La mémoire de faits n'est pas suivie** : le cache suit les fichiers lus par la réponse et `SENSAI.md`, pas la mémoire de faits (M3) ni le profil. Une réponse appuyée sur `recall_facts` n'est jamais mise en cache, mais le prompt système contient la liste des entités connues.
- **L'expiration se fait à la lecture** : une entrée de plus de 30 jours est retirée quand une question la retrouve. Les entrées qu'aucune question ne retrouve restent dans `~/.sensai/cache.db` jusqu'à `/cache clear`.
