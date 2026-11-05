# Mesures de performance — [R1] Basic RAG

Mesures faites le 2026-10-11 pour trancher trois décisions de
[l'ADR-0009](../decisions/0009-rag-sur-la-codebase.md) : le modèle d'embeddings
(décision 2), la méthode de recherche (décision 1) et le seuil « rien trouvé »
(décision 8).

Script : [`scripts/bench_rag.py`](../../scripts/bench_rag.py). Résultats bruts :
[`data/R1-quality-2026-10-11.json`](data/R1-quality-2026-10-11.json) et
[`data/R1-search-2026-10-11.json`](data/R1-search-2026-10-11.json).

## Reproduire

```bash
pip install -e ".[dev]" numpy
ollama pull nomic-embed-text && ollama pull qwen3-embedding:0.6b && ollama pull bge-m3
python scripts/bench_rag.py quality --out quality.json   # mesure A
python scripts/bench_rag.py search  --out search.json    # mesure B
```

Le corpus de la mesure A est `git ls-files` : les résultats dépendent donc du
commit mesuré. Les chiffres ci-dessous portent sur la branche `lot-c/rag` au
commit `9a9724e` (M1 complète, R1 pas encore codée).

## Machines

| | Machine de mesure (résultats ci-dessous) | Premier essai (abandonné) |
|---|---|---|
| Type | VM Ubuntu 24.04.4, 8 vCPU AMD EPYC, 23 Go RAM, sans GPU | VM Azure Ubuntu 24.04.5, 2 vCPU AMD EPYC 7763, 7,7 Go RAM, sans GPU |
| Logiciels | Python 3.12.3 ; numpy et Ollama (CPU) installés le jour même (pip et script officiel) | Python 3.12.3, numpy 2.5.4, Ollama 0.40.3 (CPU) |
| Résultat | Mesures A et B complètes | Seul `nomic-embed-text` mesuré (arrêté : trop lent sur 2 vCPU) |

Les deux VM ont été préparées pour la mesure (Ollama, modèles, environnement
Python dans un dossier dédié) puis entièrement nettoyées. Le poste de
développement (disque plein à 97 %, sans GPU) n'a pas servi.

## Mesure A — quel modèle d'embeddings ?

**Méthode**
- Corpus : les 55 fichiers texte suivis par git (code, docs, tests, config),
  découpés en blocs de 40 lignes qui se chevauchent de 10, soit 106 passages.
  Chaque passage commence par son chemin de fichier. Le découpage est le même
  pour tous les modèles : on compare les modèles, pas le découpage.
- 15 questions en français sur le dépôt, chacune associée aux fichiers qui
  contiennent la réponse (liste dans le script). Une question est réussie au
  rang *k* si un de ces fichiers apparaît parmi les *k* premiers passages.
- 3 questions dont la réponse n'est pas dans le dépôt (Kafka, Stripe, e-mails)
  pour régler le seuil.
- Chaque modèle reçoit ses préfixes recommandés (`search_query:` /
  `search_document:` pour nomic, une instruction pour qwen3-embedding, rien
  pour bge-m3). Vecteurs normalisés, similarité cosinus, recherche exhaustive.

**Résultats**

| | `nomic-embed-text` | `qwen3-embedding:0.6b` | `bge-m3` |
|---|---|---|---|
| Bon fichier en 1re position | 8/15 | 10/15 | **11/15** |
| Dans les 3 premiers | 14/15 | 13/15 | **14/15** |
| Dans les 5 premiers | 14/15 | 14/15 | 14/15 |
| MRR (rang réciproque moyen) | 0,716 | 0,774 | **0,842** |
| Indexation des 106 passages | **141 s** | 615 s | 311 s |
| Temps médian par question (embedding + recherche) | **104 ms** | 487 ms | 202 ms |
| Taille du modèle | **274 Mo** | 639 Mo | 1,2 Go |

Sur le premier essai (2 vCPU), `nomic-embed-text` donnait le même score (8/15,
14/15) en 178 s : la qualité ne dépend pas de la machine, le temps si.

**Seuil « rien trouvé »** — score du meilleur passage pour chaque question :

| | Vraie question la plus faible | Question sans réponse la plus forte | Marge |
|---|---|---|---|
| nomic-embed-text | 0,676 | 0,698 | **négative** : aucun seuil ne sépare |
| qwen3-embedding:0.6b | 0,540 | 0,515 | 0,025 |
| bge-m3 | 0,524 | 0,467 | **0,057** |

**Questions ratées en 1re position avec bge-m3**

| Question | Rang du bon fichier | Premier passage renvoyé |
|---|---|---|
| Quel contrat chaque outil appelable par l'agent doit-il respecter ? | 2 | ADR-0003 (tool calling) |
| Qui doit relire une modification du registre d'outils ? | 2 | ADR-0002 (registre d'outils) |
| Que se passe-t-il si la base des sessions est corrompue ? | 8 | ADR-0007 |
| Combien d'itérations maximum la boucle de raisonnement peut-elle faire ? | 2 | `prompts/react_prompt.txt` |

La question sur la base corrompue échoue avec les trois modèles (rang 15, 33
et 8) : la réponse n'est que dans le code de `cli.py`, et un bloc de 40 lignes
la noie dans du code voisin. C'est l'argument concret pour le découpage par
structure (décision 3).

## Mesure B — quelle méthode de recherche ?

**Méthode** : vecteurs aléatoires normalisés de 1 024 dimensions (la taille de
bge-m3), recherche des 5 plus proches par produit scalaire sur toute la
collection. Temps médian sur 20 recherches (3 pour 100 000 passages), sans
compter le calcul de l'embedding de la question.

| Passages | Python pur | numpy | Rapport |
|---|---|---|---|
| 300 | 24 ms | 0,27 ms | ×90 |
| 2 000 | 192 ms | 1,4 ms | ×130 |
| 20 000 | 1 614 ms | 4,5 ms | ×360 |
| 100 000 | 8 333 ms | 18 ms | ×455 |

Python pur croît linéairement (environ 0,08 ms par passage) ; numpy reste sous
20 ms à 100 000 passages.

## Recalibration du seuil avec le découpage livré

Mesure A relancée le même jour, pour bge-m3 seul, avec le vrai découpage de
`sensai.knowledge.rag` (`--chunker structure`), au commit `22b5262` (R1 codée).
Résultats bruts : [`data/R1-quality-structure-2026-10-11.json`](data/R1-quality-structure-2026-10-11.json).

```bash
python scripts/bench_rag.py quality --models bge-m3 --chunker structure
```

**Erreur de méthode corrigée.** Un premier essai a donné 1/15 en 1re position :
le corpus étant `git ls-files`, il contenait désormais les résultats de la
première mesure, son rapport et ce script — trois fichiers qui contiennent les
15 questions mot pour mot. La recherche trouvait la question au lieu de la
réponse. Le script exclut depuis `docs/performance/` et `scripts/bench_rag.py`
du corpus (`EXCLUDED_FROM_CORPUS`). Les fichiers d'une mesure ne doivent jamais
faire partie du corpus mesuré.

| bge-m3 | Blocs de 40 lignes (commit `9a9724e`) | Structure (commit `22b5262`) |
|---|---|---|
| Corpus | 55 fichiers, 106 passages | 61 fichiers, 339 passages |
| Bon fichier en 1re position | 11/15 | 6/15 |
| Dans les 3 premiers | 14/15 | 14/15 |
| Dans les 5 premiers | 14/15 | **15/15** |
| MRR | 0,842 | 0,683 |
| Indexation | 311 s | 433 s |
| Vraie question la plus faible | 0,524 | 0,524 |
| Question sans réponse la plus forte | 0,467 | 0,494 |

**Lecture.** Les deux colonnes ne sont pas strictement comparables : le corpus
a changé en même temps que le découpage (code, tests, user stories et ADR de R1
ajoutés). La baisse en 1re position vient surtout de passages pertinents absents
de la liste de réponses attendues, écrite pour l'ancien dépôt : « où sont
supprimées les sessions inactives ? » renvoie `src/sensai/cli.py:97`, qui
déclenche la purge ; « comment choisit-on la session à reprendre ? » renvoie la
user story M1 qui le décrit. Faiblesse réelle : les fichiers de tests remontent
souvent en premier, leurs docstrings décrivant le comportement mieux que le
code. Progrès réel : 15/15 dans les 5 premiers, et la question sur la base
corrompue, ratée par les trois modèles, remonte au 4e rang (8e avant).

**Seuil : 0,50 confirmé** (décision de l'équipe, 2026-10-11). Il sépare encore
toutes les vraies questions (≥ 0,524) des questions sans réponse (≤ 0,494),
mais la marge n'est plus que de 0,03. À re-mesurer avec ce script quand le
dépôt grossit ou si le modèle d'embeddings change.

## Essai du CLI réel

Même machine, commit `22b5262`, chat `qwen3:8b` et embeddings `bge-m3` servis
par Ollama sur CPU, sur le dépôt Sensai lui-même.

| Vérification | Résultat |
|---|---|
| Indexation automatique à la 1re question, avec progression | ✅ 67 fichiers, 386 passages |
| « Où est configuré Kafka dans ce projet ? » | ✅ « Aucune configuration Kafka n'a été trouvée dans les fichiers du projet analysés. » |
| Relance sans modification | ✅ 0 fichier réindexé |
| Relance après modification de `README.md` | ✅ 1 fichier réindexé |
| « Où vérifie-t-on qu'une session inconnue ne fait pas planter le CLI ? », 5 passages (défaut) | ❌ « Ollama ne répond pas (timeout) », y compris modèle déjà chargé |
| Même question, 2 passages (`--rag-top-k 2`) | ✅ Cite `tests/test_cli_persistence.py:155-160`, le test qui le vérifie ; réponse en ~6 min 45 sur CPU |

**Ce que l'essai révèle**
- Avec 5 passages, le message envoyé est long : sur CPU, qwen3:8b met plus de
  60 s à le lire avant d'écrire le premier mot, et `core/ollama_client.py`
  (Lot A) coupe la connexion au bout de 60 s.
- Ollama servait qwen3:8b avec une fenêtre de contexte de 4 096 tokens (valeur
  par défaut, lue avec `ollama ps`) : un long historique (M1) plus des passages
  (R1) peuvent être tronqués sans avertissement.
- Avec 2 passages, le modèle a affirmé que `cli.py` ne traite pas explicitement
  une session inconnue, alors qu'il le fait (`except KeyError`) : le passage de
  `cli.py` n'était pas retenu, et le modèle a extrapolé.

## Essai sur GPU (pod RunPod, conditions de la démo)

Configuration de l'ADR-0004 : le code et le CLI tournent sur le poste de
développement, le modèle sur un pod RunPod joint par `--host` (port 11434 exposé
par le proxy HTTP de RunPod). Chat `qwen3-coder:30b` (18,6 Go), embeddings
`bge-m3`, Ollama 0.40.3. Variables du pod : `OLLAMA_HOST=0.0.0.0`,
`OLLAMA_MODELS=/workspace/ollama`, `OLLAMA_CONTEXT_LENGTH=16384` ; `ollama ps`
a indiqué une fenêtre de 32 768 tokens pour qwen3-coder:30b (21,7 Go de VRAM).
5 passages par question (réglage par défaut).

**Premier passage (commit `4da5de9`)**

| Vérification | Résultat |
|---|---|
| Indexation du dépôt | ✅ 66 fichiers, 387 passages, moins de 2 min (≈ 7 min sur 8 vCPU) |
| Question sur le code, modèle pas encore chargé | ❌ timeout : charger 18,6 Go dans le GPU dépasse les 60 s du client |
| Même question, modèle chargé | ✅ bon code et bon test cités, réponse en quelques secondes ; ❌ lignes de `cli.py` fausses (123-127 cité, code ligne 112) |
| « Où est configuré Kafka ? » | ✅ « Aucune configuration Kafka n'a été trouvée » |
| « Bonjour » / « C'est quoi une closure ? » | ❌ réponse détournée vers les passages (« la pertinence est de 0.51… ») |
| Relance sans modification / après modification | ✅ 0 puis 1 fichier réindexé |

Diagnostic des lignes fausses : le passage envoyé couvrait `cli.py:97-136`
(fonction `main` découpée en fenêtres) et contenait le bon code ; le modèle a
deviné la ligne, faute de pouvoir compter dans le passage.

**Corrections (commit `a0dd3b3`)** : chaque ligne d'un passage est précédée de
son numéro dans le fichier, le score n'est plus montré au modèle, et la
consigne lui dit d'ignorer les passages sans rapport et de répondre normalement.

**Second passage (commit `a0dd3b3`, modèle préchargé)**

| Question | Résultat |
|---|---|
| « Où vérifie-t-on qu'une session inconnue ne fait pas planter le CLI ? » | ✅ `src/sensai/cli.py:112-116` (exact) et `tests/test_cli_persistence.py:155-160`, code recopié fidèlement |
| « Bonjour, réponds en une phrase. » | ✅ réponse normale |
| « C'est quoi une closure en Python ? » | ✅ bonne réponse ; ⚠️ suivie d'une source inutile (`docs/decisions/TEMPLATE.md:14-15`) |
| « Où est configuré Kafka dans ce projet ? » | ✅ pas de configuration trouvée ; ⚠️ cite ce rapport, qui mentionne Kafka |

Les 4 questions ont reçu leur réponse en 25 s au total. La **Definition of
Done de R1 est atteinte** sur la configuration de démonstration.

Limites de cet essai : un seul passage par question type ; le dépôt indexé
contient ses propres rapports de mesure (d'où la citation de ce fichier pour
Kafka) ; le délai de 60 s du client reste un risque au premier appel tant que le
modèle n'est pas préchargé (à précharger avant une démo).

## Essai de l'outil `search_codebase` avec l'agent (2026-10-14)
Choix : [ADR-0013](../decisions/0013-branchement-de-l-outil-rag.md). Pod RunPod
(Community Cloud, GPU de 24 Go), Ollama 0.40.3, `qwen3-coder:30b` et `bge-m3`,
dépôt de 139 fichiers (1 074 passages), dossier de données jetable.

| Essai | Réglage | Ce que fait le modèle | Résultat |
| --- | --- | --- | --- |
| 1 | défaut (5 passages ajoutés) | Répond sans appeler l'outil : les passages ajoutés suffisent | Purge juste (`cli.py:167`) ; place `bge-m3` dans `cli.py` au lieu de `config.py` |
| 2 | `--rag-top-k 1` | Appelle `search_codebase` (`"variable DEFAULT_EMBED_MODEL"`), sans confirmation | ❌ L'outil, limité lui aussi à 1 passage, renvoie le README : le modèle répond `qwen3:8b`. Le résultat commence par la consigne des passages automatiques (« ignore-les ») |
| 3 | `--rag-top-k 1`, après correction | Appelle l'outil deux fois, une par question, avec ses propres mots | ✅ 5 passages par recherche, présentés comme une recherche demandée. `_chunk_markdown`, `rag.py:261` (juste) ; `DEFAULT_EMBED_MODEL` de `rag.py` (juste, cite la ligne d'usage 304 au lieu de la définition, ligne 42) |

Durées (une mesure) : essai 1, 2 min 52 s dont la première indexation ;
essai 3, 34 s, index déjà à jour.

Ce que l'essai a changé : l'outil a sa propre présentation et ignore
`--rag-top-k` (ADR-0013). Il a aussi montré que la valeur par défaut
`"bge-m3"` est écrite deux fois (`config.py` et `rag.py`) : à regrouper.

## Ce qu'on en conclut

- **Modèle : `bge-m3`.** Le plus précis, et le seul qui laisse une marge nette
  pour le seuil « rien trouvé » ; nomic, plus rapide, rend US-R1-3 impossible.
- **Recherche : numpy.** Python pur suffirait jusqu'à ~2 000 passages, mais
  numpy garde la recherche négligeable quelle que soit la taille du projet,
  pour une dépendance courante.
- **Seuil : 0,50**, au milieu de l'intervalle mesuré, confirmé avec le
  découpage livré (marge réduite à 0,03, voir plus haut).

## Limites

- 15 questions écrites par l'équipe, sur un seul dépôt et un petit corpus
  (106 passages). Un écart d'une ou deux questions entre modèles n'est pas
  significatif ; l'écart sur le seuil l'est davantage.
- 3 questions sans réponse seulement : le seuil est une première estimation.
- Les temps d'indexation dépendent de la machine (8 vCPU ici) ; ils seront plus
  longs sur un portable sans GPU, ce qui compte pour la première question d'un
  projet (indexation automatique, décision 5).
- La comparaison entre découpages est faussée par l'évolution du corpus, et la
  liste de réponses attendues date de l'ancien dépôt.
- Les essais du CLI réel (CPU puis GPU) portent sur quelques questions : ils
  démontrent le fonctionnement, pas une qualité moyenne.

## Coûts

Aucun coût monétaire mesuré pour les VM, fournies par un membre de l'équipe ;
Ollama et les modèles sont gratuits. Le pod RunPod est facturé à l'heure tant
qu'il tourne (fourchette de `docs/recherche/infra-options.md` : 0,20 à 0,70 $/h pour une
RTX 3090/4090) ; la durée exacte de l'essai n'a pas été relevée. Coût d'usage pour
l'utilisateur : 1,2 Go de disque pour bge-m3, plus la taille de l'index (non
mesurée sur un vrai projet — à ajouter avec l'implémentation).
