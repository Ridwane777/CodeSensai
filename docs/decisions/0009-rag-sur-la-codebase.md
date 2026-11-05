# ADR-0009 — RAG sur le projet : bge-m3, SQLite + numpy, indexation automatique

- **Statut** : Accepté (2026-11-01, validé par l'équipe) ; seuil (décision 8) et classement remplacés par [ADR-0032](0032-rag-hybride-et-reclassement.md)
- **Date** : 2026-10-11
- **Décideurs** : Ridwane NICO (Lot C), à valider par l'équipe
- **Lot concerné** : C (impacte A : `RagTool` attend la boucle ReAct)

## Contexte
La feature [R1] Basic RAG doit permettre de poser une question sur le code et
la documentation du projet et d'obtenir une réponse qui cite le bon passage
(Definition of Done ClickUp). Le catalogue décrit le pipeline : ingérer,
découper, calculer les embeddings, stocker dans une base vectorielle locale,
retrouver par similarité, injecter dans le contexte. Besoins détaillés :
[user stories R1](../user-stories/R1-basic-rag.md).

Contraintes :
- **Pas de framework LLM** ([ADR-0001](0001-pas-de-framework-llm.md)) : pas de
  LlamaIndex ni de LangChain ; les embeddings passent par l'API HTTP d'Ollama
  (`/api/embed`).
- **Questions en français, sur du code** : le modèle d'embeddings doit gérer
  les deux.
- **Machines de l'équipe sans GPU**, disque parfois presque plein : chaque
  dépendance et chaque Go comptent.
- **La boucle ReAct (Lot A) n'est pas livrée** : ce qui dépend d'elle ne doit
  pas bloquer R1.
- **Tout passage indexé peut être envoyé au modèle**, y compris sur le pod
  distant (ADR-0004) : l'indexation ne doit jamais toucher aux secrets.

Les décisions 1, 2 et 8 reposent sur des mesures :
[docs/performance/R1-rag.md](../performance/R1-rag.md).

## Options envisagées

**1. Base vectorielle et recherche**

| Option | Pour | Contre |
| --- | --- | --- |
| **SQLite + recherche exhaustive avec numpy** (retenu) | Même base que M1 (ADR-0007). Mesuré : 1,4 ms pour 2 000 passages, 18 ms pour 100 000. Pas d'extension SQLite à charger | Une dépendance (numpy), très répandue |
| SQLite + recherche en Python pur | Aucune dépendance | Mesuré à 192 ms pour 2 000 passages, 1,6 s pour 20 000, 8,3 s pour 100 000 : l'attente se voit à chaque question |
| sqlite-vec | Rapide | Extension C à charger dans SQLite, désactivée sur certaines installations de Python (dont macOS) : risque de « ça marche chez moi », pour un gain inutile à notre échelle |
| FAISS | Très rapide sur des millions de vecteurs, index approchés | Dépendance compilée et lourde ; les index approchés peuvent manquer le meilleur passage |
| ChromaDB | Base vectorielle complète | Plusieurs centaines de Mo de dépendances |

**2. Modèle d'embeddings** (mesuré sur 15 questions en français sur ce dépôt)

| Option | Pour | Contre |
| --- | --- | --- |
| **`bge-m3`** (retenu) | Bon fichier en 1re position 11/15, MRR 0,842 ; seul modèle qui sépare nettement les questions sans réponse (marge 0,057) | 1,2 Go ; indexation 2,2 fois plus lente que nomic (311 s contre 141 s sur 8 vCPU) |
| `nomic-embed-text` | Le plus léger (274 Mo) et le plus rapide | 8/15 en 1re position ; une question sans réponse (« Kafka ») score plus haut que certaines vraies questions : aucun seuil possible, US-R1-3 irréalisable |
| `qwen3-embedding:0.6b` | 10/15 en 1re position | Indexation 4,4 fois plus lente que nomic (615 s) ; marge du seuil très faible (0,025) |

**3. Découpage des fichiers**

| Option | Pour | Contre |
| --- | --- | --- |
| **Selon la structure** (retenu) : une fonction ou une classe Python par passage (`ast`), une section par titre en Markdown, des blocs de lignes qui se chevauchent ailleurs | Chaque passage garde son fichier et ses lignes, pour citer `fichier:lignes`. La mesure montre le problème des blocs fixes : une réponse qui n'est que dans `cli.py` est noyée dans un bloc de 40 lignes et ratée par les trois modèles | Plus de code (un découpeur par format) |
| Blocs de taille fixe partout | Plus simple | Coupe les fonctions et mélange des sujets dans un même passage |

**4. Comment les passages arrivent au modèle**

| Option | Pour | Contre |
| --- | --- | --- |
| **Les deux** (retenu) : injection automatique des meilleurs passages à chaque question, et `RagTool` (`search_codebase`) pour la boucle ReAct | Fonctionne avec le CLI actuel, et prêt pour le Lot A | Deux chemins à maintenir |
| Outil seulement | Plus « agentique » | Rien ne fonctionne avant la livraison du Lot A |
| Injection seulement | Fonctionne tout de suite | Le modèle ne peut pas chercher de lui-même une deuxième fois |

**5. Quand indexer**

| Option | Pour | Contre |
| --- | --- | --- |
| **Automatiquement, à la première question, puis seulement les fichiers modifiés** (retenu) | Rien à lancer à la main : l'expérience de Claude Code (qui, lui, cherche à la demande avec `grep` sans embeddings : on reprend l'expérience, pas le mécanisme). Une progression s'affiche | Une première question lente sur un nouveau projet |
| Commande explicite (`/index`) | Aucun délai surprise | Une étape que l'utilisateur doit connaître |
| Indexation complète à chaque lancement | Toujours à jour | Plusieurs minutes d'attente à chaque démarrage |

**6. Ce qui n'est jamais indexé**

| Option | Pour | Contre |
| --- | --- | --- |
| **Le `.gitignore` du projet, plus une liste interdite en dur** (retenu) : `.git`, `.venv`, `node_modules`, `__pycache__`, binaires, fichiers trop gros, et `.env*`, `*.pem`, `*.key`, `id_rsa*`, fichiers de secrets | Les secrets restent exclus même si le `.gitignore` les oublie | Une liste à tenir à jour |
| `.gitignore` seul | Rien à maintenir | Un projet sans `.gitignore`, ou avec un `.gitignore` incomplet, enverrait ses secrets au modèle |

**7. Formats pris en charge**

| Option | Pour | Contre |
| --- | --- | --- |
| **Texte et Markdown (code compris) ; pour les autres formats, un conseil (quoi installer ou convertir)** (retenu) | Aucune dépendance. En attendant la boucle ReAct, l'indexation affiche elle-même les fichiers ignorés et le conseil | Les PDF ne sont pas lus (US-R1-4 limitée) |
| PDF via `pypdf` | Couvre directement les sujets de projet (US-R1-4) | Une dépendance, et une extraction souvent imparfaite (mise en page, colonnes) |

**8. Seuil « rien trouvé »**

| Option | Pour | Contre |
| --- | --- | --- |
| **Seuil de similarité réglé par la mesure, configurable** (retenu) : 0,50 pour bge-m3, au milieu de l'intervalle mesuré (vraie question la plus faible 0,524, question sans réponse la plus forte 0,467), confirmé avec le découpage livré (0,524 contre 0,494 : marge de 0,03) | Sous le seuil, rien n'est injecté et le modèle est prévenu (US-R1-3) ; valeur défendable par la mesure | Marge faible, à re-mesurer si le dépôt ou le modèle change |
| Seuil fixé à la main | Simple | Arbitraire, impossible à défendre |
| Pas de seuil | Toujours des passages | Des passages hors sujet sont injectés, et le modèle les cite comme s'ils répondaient |

## Décision
- Index dans SQLite, dans le dossier de données de M1 (`~/.sensai/`, droits
  `700`), rattaché au projet comme les sessions ; recherche exhaustive avec
  numpy.
- Embeddings `bge-m3` via `/api/embed` d'Ollama ; modèle configurable.
- Découpage par structure (Python via `ast`, Markdown par titres, blocs de
  lignes ailleurs), avec fichier et lignes pour chaque passage.
- Injection automatique des meilleurs passages à chaque question + `RagTool`
  pour la boucle ReAct.
- Indexation automatique à la première question, puis seulement des fichiers
  ajoutés, modifiés ou supprimés.
- Exclusions : `.gitignore` + liste interdite en dur, prioritaire.
- Texte et Markdown seulement ; les autres formats sont listés avec un
  conseil.
- Seuil de similarité configurable (`rag_min_score`), 0,50, confirmé par la
  recalibration du 2026-10-11.

## Conséquences
- ✅ Fonctionne sans la boucle ReAct : la DoD de R1 est atteignable avec le
  CLI actuel.
- ✅ Choix du modèle, de la recherche et du seuil fondés sur des mesures
  reproductibles.
- ✅ Les secrets ne peuvent pas être indexés, même avec un `.gitignore`
  incomplet.
- ✅ Une seule technologie de stockage pour M1 et R1.
- ❌ **Nouvelle dépendance : numpy.** Courante et sous licence BSD, mais la
  première dépendance du projet en dehors de `requests`.
- ❌ **1,2 Go de modèle à télécharger** (bge-m3), et une première question
  lente sur un nouveau projet (311 s pour ce petit dépôt sur 8 vCPU, plus sur
  un portable sans GPU).
- ❌ Le seuil 0,50 repose sur 3 questions sans réponse, et sa marge n'est que de
  0,03 avec le découpage livré : à re-mesurer quand le dépôt grossit ou si le
  modèle d'embeddings change.
- ❌ Essai réel sur CPU : avec 5 passages, la question envoyée est assez longue
  pour que qwen3:8b dépasse le délai de 60 s du client Ollama ; avec 2
  passages, la réponse cite le bon passage. Sur GPU (pod RunPod,
  qwen3-coder:30b), les 5 passages passent et la DoD est atteinte, sauf au
  premier appel, quand le chargement du modèle dépasse ce même délai : à
  précharger avant une démo. Voir docs/performance/R1-rag.md.
- ✅ Chaque ligne d'un passage est envoyée avec son numéro : sans cela, le
  modèle devinait les lignes à citer (ajouté après l'essai réel).
- ❌ PDF et autres formats non indexés : US-R1-4 ne fonctionne que sur du
  texte et du Markdown.
- ❌ Ce qui dépend de la boucle ReAct (appel de `RagTool`, outil « format non
  pris en charge ») attend le Lot A : sous-tâches ClickUp en « update
  required ».
- ❌ Au-delà de quelques centaines de milliers de passages, la recherche
  exhaustive ne suffira plus : passer alors à un index approché (FAISS,
  sqlite-vec).
