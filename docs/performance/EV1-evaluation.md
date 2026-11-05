# Évaluation des réponses et des hallucinations — [EV1]

Méthode, format des rapports, commandes pour reproduire et limites de
l'évaluation par juge LLM décidée dans
[l'ADR-0019](../decisions/0019-evaluation-par-juge-llm.md). Besoins :
[user stories EV1](../user-stories/EV1-evaluation-hallucinations.md).

**Résultat d'une exécution réelle : non mesuré.** Aucun serveur Ollama n'était
joignable sur la machine où EV1 a été écrit (2026-10-14) : tout ce qui est
testé l'est avec un juge simulé (`tests/eval/`), hors ligne. Aucune note de
pertinence, de cohérence ou de fidélité n'est donc donnée dans ce dépôt. La
section « Résultats » est à remplir après une exécution réelle, avec la machine
et les modèles utilisés. Ce qui a été vérifié sans serveur : lancée sans
Ollama, la commande écrit un rapport où les 5 cas de l'exemple sont en
`judge_error`, affiche l'erreur de connexion et se termine avec le code 0.

**Ce que ces notes sont : des estimations produites par un modèle**, pas des
mesures. Voir « Limites ».

## Ce que le juge évalue

Pour chaque cas (une question, une réponse, des passages de référence), un
seul appel au modèle juge (`POST /api/chat`, `stream: false`, `format: "json"`,
`temperature: 0`, `seed: 42`) renvoie :

| Champ | Contenu |
| --- | --- |
| `relevance` | entier de 1 à 5 : la réponse traite-t-elle la question ? |
| `coherence` | entier de 1 à 5 : la réponse est-elle claire et sans contradiction interne ? |
| `claims` | liste d'affirmations : `text`, `verdict`, `sources` (identifiants `S1`…), `explanation` |

Les ancres de chaque niveau (1 à 5) sont dans le prompt
[`prompts/judge/v1.txt`](../../prompts/judge/v1.txt). Pertinence et cohérence
ignorent l'exactitude des faits : c'est le rôle de la fidélité.

**Verdicts d'une affirmation** (fondés uniquement sur les passages fournis) :

| Verdict | Sens |
| --- | --- |
| `SUPPORTED` | un passage dit la même chose ou l'implique directement |
| `CONTRADICTED` | un passage dit le contraire |
| `UNVERIFIABLE` | aucun passage ne tranche (même si l'affirmation est vraie dans le monde) |

**Fidélité** (calculée par `eval/judge.py:faithfulness`, pas par le modèle) =
affirmations `SUPPORTED` / affirmations totales du cas ; `null` sans affirmation.
La moyenne de fidélité porte sur les cas qui en ont une (`n_faithfulness` donne
leur nombre).

**Garde-fous du code sur la sortie du juge :**
- JSON extrait tolérant : blocs ```` ```json ```` retirés, du premier `{` au dernier `}`.
- Notes hors de 1 à 5, ou non entières ; verdict inconnu ; `claims` absent : sortie refusée et relancée (2 relances au plus, avec la sortie fautive et un message correctif en français).
- `SUPPORTED` ou `CONTRADICTED` sans citation, ou avec un identifiant qui n'est pas dans les passages : l'affirmation devient `UNVERIFIABLE`, avec le drapeau `citation_invalide` et `verdict_original`.
- Toujours inexploitable, ou `OllamaError` : le cas est `judge_error` (début de la sortie brute conservé, 2 000 caractères au plus). Pas de note 0, pas de moyenne.

**Cas signalés (`flagged`)** : toutes les affirmations `CONTRADICTED` ou
`UNVERIFIABLE` du cas, avec leurs citations (identifiant, fichier, lignes).

## Le jeu de données

Fichier JSONL, une ligne par cas (`eval/dataset.py`) :

| Clé | | |
| --- | --- | --- |
| `id` | obligatoire, unique | |
| `question` | obligatoire | |
| `answer` | facultative | réponse à juger ; sans elle, `--generate` fait répondre l'agent, sinon le cas est `skipped` |
| `sources` | facultative | liste de textes, ou d'objets `{"source", "text"}` ; ignorée avec `--sources rag` |
| `notes` | facultative | ce que le cas doit montrer |

Une clé inconnue, un id en double, un JSON invalide : erreur qui nomme la ligne.

[`datasets/eval/ev1_sample.jsonl`](../../datasets/eval/ev1_sample.jsonl) contient
5 cas écrits à la main, avec des passages inventés et autosuffisants (ce ne sont
pas des extraits de ce dépôt). Chaque cas vise une situation ; la colonne
« intention » est ce que l'auteur attend du juge, **pas un résultat observé** :

| `id` | Situation | Intention |
| --- | --- | --- |
| `fidele` | réponse entièrement soutenue par la source | affirmations `SUPPORTED`, fidélité 1 |
| `contredit` | la réponse dit 7 jours, la source 30 | une affirmation `CONTRADICTED` |
| `inverifiable` | une phrase soutenue, une (reclassement BM25) absente de la source | une affirmation `UNVERIFIABLE` |
| `hors-sujet` | réponse cohérente mais sans rapport avec la question | pertinence basse, cohérence élevée |
| `sans-source` | aucun passage fourni | affirmation `UNVERIFIABLE` |

Cinq cas ne suffisent à aucune conclusion statistique : ils servent à vérifier
que la chaîne fonctionne et que le juge réagit aux situations évidentes.

## Origine des passages

- `--sources dataset` (défaut) : les `sources` de chaque ligne. Déterministe.
- `--sources rag` : l'index du projet courant (R1), ouvert par la même fonction que le CLI (`cli.open_rag_index`), avec `rag_model`, `rag_top_k` et `rag_min_score` de `config.json` ou leurs valeurs par défaut. Il indexe d'abord le projet (plusieurs minutes la première fois) et demande le modèle d'embeddings (`bge-m3`). Seul le contrat `.search(query, top_k, min_score)` est utilisé par `eval/sources.py:rag_sources`. Les tests n'utilisent qu'un faux index.

## Format du rapport

Fichier JSON écrit par `sensai-eval run` (`eval/report.py:run_eval`) :

| Clé | Contenu |
| --- | --- |
| `schema_version` | `1` |
| `created_at`, `sensai_version` | date UTC ; version du paquet (`inconnue` s'il n'est pas installé) |
| `judge` | `model`, `host`, `prompt_name` (`judge`), `prompt_version`, `prompt_sha256`, `temperature`, `seed`, `max_retries` |
| `dataset` | `path`, `sha256`, `n_cases` |
| `sources_mode` | `dataset` ou `rag` |
| `generator` | `model`, `host`, `system_prompt_version` si `--generate`, sinon `null` |
| `summary` | `n_cases`, `n_scored`, `judge_errors`, `skipped`, `source_errors`, `generation_errors`, `mean_relevance`, `mean_coherence`, `mean_faithfulness`, `n_faithfulness`, `claims_total`, `claims_flagged`, `flagged_claim_rate` |
| `cases[]` | `id`, `question`, `answer`, `answer_origin` (`dataset`/`generated`), `passages` (texte tronqué à 1 000 caractères), `status`, puis `scores`, `claims`, `flagged`, `attempts` (cas jugé) ou `error`/`raw` (en erreur) |

`status` : `ok`, `judge_error`, `skipped`, `source_error` (recherche des
passages impossible), `generation_error` (génération impossible ou vide).
**Les moyennes ne portent que sur les cas `ok`.** `flagged_claim_rate` =
affirmations signalées / affirmations totales, sur les cas `ok`.

## Comparer deux rapports

`sensai-eval compare A.json B.json [--out D.json] [--strict]` : écarts
**B moins A** de la pertinence, de la cohérence, de la fidélité, de la part
d'affirmations signalées et du nombre d'erreurs du juge, puis écarts par cas
sur les `id` communs (les `id` présents d'un seul côté sont listés).
`comparable` vaut `false`, avec un avertissement par réglage, si diffèrent :
le modèle du juge, le sha256 du prompt du juge, le sha256 du jeu de données,
l'origine des passages ou `schema_version`. Le générateur (modèle, prompt
système) est ce qu'on compare : il ne bloque pas. Code de sortie 0, sauf
`--strict` avec rapports non comparables (1), ou rapport illisible (2).

## Reproduire

```bash
pip install -e ".[dev]"
ollama pull qwen3:8b                      # juge par défaut = modèle de config.json
sensai-eval run --dataset datasets/eval/ev1_sample.jsonl --out rapports/a.json

# Même jeu de données, autre juge (autre modèle à télécharger au préalable) :
sensai-eval run --dataset datasets/eval/ev1_sample.jsonl --out rapports/b.json \
    --judge-model <autre-modèle>
sensai-eval compare rapports/a.json rapports/b.json         # signalera le changement de juge

# Comparer deux prompts système (jeu de données SANS clé « answer ») :
sensai-eval run --dataset questions.jsonl --out v1.json --generate
sensai-prompt use system v2
sensai-eval run --dataset questions.jsonl --out v2.json --generate
sensai-eval compare v1.json v2.json --strict
```

Sans installation, depuis le dépôt : `PYTHONPATH=src python -m sensai.eval.cli …`.
Versions du prompt du juge : `sensai-prompt history judge` ; une autre version
se choisit avec `--judge-prompt-version`. Tests (hors ligne) :
`pytest tests/eval`.

`--generate` : un seul tour de `stream_chat` avec le prompt système actif
(ou `system_prompt_path` de `config.json`), les passages et la question, avec le
modèle de `config.json`.

## Résultats

**Non mesuré.** À remplir après une exécution réelle, sous la forme : machine
(CPU/GPU, RAM), version d'Ollama, modèle du juge, modèle de l'agent, date,
rapport JSON joint dans `docs/performance/data/`, durée de la série.

## Limites

- **Auto-préférence.** Par défaut le juge est le même modèle que l'agent (`qwen3:8b`) : il peut favoriser ses propres formulations. Les notes absolues sont à lire avec cette réserve ; préférer des comparaisons avec le même juge, ou un juge d'une autre famille.
- **Biais du juge.** Un juge LLM peut préférer les réponses longues ou assurées, se laisser guider par la forme, ou se tromper sur une affirmation technique fine. Sa fiabilité n'a pas été comparée à une relecture humaine : non mesuré.
- **Non-déterminisme résiduel.** Température 0 et graine 42 réduisent la variation mais ne la suppriment pas (matériel, version d'Ollama). Un petit écart entre deux rapports n'est pas un signal ; relancer plusieurs fois donnerait un ordre de grandeur du bruit (non fait).
- **Échelle grossière.** Notes entières de 1 à 5 ; sur peu de cas, une moyenne bouge d'un cas à l'autre.
- **Découpage en affirmations instable.** Le nombre d'affirmations varie d'un appel à l'autre (et la consigne en limite 15) : la fidélité d'un cas est une fraction de quelques unités, très sensible à un verdict.
- **Langue.** Le prompt du juge est en français et les exemples du jeu de données aussi ; le comportement avec des réponses ou du code dans d'autres langues n'est pas mesuré.
- **Qualité des passages.** Le juge ne vaut que par ses passages : en mode `rag`, un passage manquant fait passer une affirmation vraie en `UNVERIFIABLE`. Ce n'est pas une hallucination détectée, mais une absence de preuve.
- **Injection.** La réponse jugée est du texte non fiable ; le prompt la présente comme une donnée mais ne rend pas le juge insensible à une réponse qui lui donne des ordres.
- **Générateur simplifié.** `--generate` n'exécute pas la boucle de l'agent (pas d'outils, pas de mémoire).
- **Panne silencieuse possible.** La commande se termine avec le code 0 même si tous les cas sont en `judge_error` (Ollama arrêté) : lire `summary.judge_errors`.
- **Mode `rag` non éprouvé en réel** : testé seulement avec un faux index.

## Améliorations possibles

- Mesurer l'accord du juge avec une relecture humaine sur un échantillon étiqueté (le prérequis pour accorder une confiance chiffrée aux scores).
- Répéter chaque cas n fois et rapporter la dispersion ; juge d'une autre famille de modèles pour réduire l'auto-préférence.
- Un code de sortie non nul quand aucun cas n'a pu être jugé, pour la CI.
- Étendre le jeu de données à des questions réelles sur le dépôt, avec les passages de l'index R1.
