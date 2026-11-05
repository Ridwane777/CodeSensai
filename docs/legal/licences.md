# Licences

*Version du 2026-10-14. Projet étudiant ; ce texte ne remplace pas l'avis
d'un juriste.* La liste complète des dépendances, avec leur rôle et leur
plan B, est dans [dependances.md](../dependances.md).

## Ce que nous utilisons

| Composant | Licence | Ce qu'elle nous impose | Vérifié |
| --- | --- | --- | --- |
| Ollama | MIT | Garder la notice de copyright si on redistribue Ollama (on ne le fait pas : chacun l'installe) | Page GitHub officielle |
| Qwen3-8B (`qwen3:8b`) | Apache-2.0 | Garder la licence et la notice si on redistribue les poids ; signaler les modifications. Usage commercial autorisé. | Fiche Hugging Face officielle |
| Qwen3-Coder-30B-A3B-Instruct (`qwen3-coder:30b`) | Apache-2.0 | Idem | Fiche Hugging Face officielle |
| `nemotron-3-nano:30b` (candidat) | **Non vérifiée** | À lire **avant** de l'utiliser : les modèles NVIDIA ont souvent une licence propre | — |
| `requests` | Apache-2.0 | Idem Apache | Métadonnées du paquet |
| `docker` (SDK Python) | Apache-2.0 | Idem Apache | Métadonnées du paquet |
| `puremagic` | MIT | Garder la notice | Métadonnées du paquet |
| `fastapi`, `pydantic`, `pydantic_core`, `anyio`, `h11`, `annotated-types`, `annotated-doc`, `typing-inspection` | MIT | Garder la notice | Métadonnées des paquets |
| `uvicorn`, `starlette`, `click`, `httpcore`, `httpx` (tests) | BSD-3-Clause | Garder la notice | Métadonnées des paquets |
| `opentelemetry-api` (dépendance de FastAPI) | Apache-2.0 | Garder la notice et les mentions de modification | Métadonnées du paquet |
| `typing_extensions` | PSF-2.0 | Garder la notice | Métadonnées du paquet |
| MarkItDown, dans l'image `sensai-docs` (pas installé dans CodeSensei) | MIT | Garder la notice si l'image est distribuée | Dépôt microsoft/markitdown |
| `rich`, `markdown-it-py`, `mdurl`, `wcwidth` | MIT | Garder la notice | Métadonnées du paquet |
| `prompt_toolkit` | BSD-3-Clause | Garder la notice ; ne pas utiliser le nom des auteurs pour promouvoir le projet | Métadonnées du paquet |
| `Pygments` (dépendance de `rich`) | BSD-2-Clause | Garder la notice | Métadonnées du paquet |
| `numpy` | BSD-3-Clause (et 0BSD, MIT, Zlib, CC0-1.0 pour des parties incluses) | Garder la notice | Métadonnées du paquet |
| `bge-m3` (embeddings du RAG) | MIT | Garder la notice si on redistribue les poids | Fiche Hugging Face officielle |
| Chromium (image `sensai-browser`, construite localement) | BSD-3-Clause et licences de ses composants | Rien tant qu'on ne redistribue pas l'image (chacun la construit) | Paquet Debian `chromium` |
| `urllib3`, `charset-normalizer` | MIT | Garder la notice | Métadonnées du paquet |
| `idna` | BSD-3-Clause | Garder la notice ; ne pas utiliser le nom des auteurs pour promouvoir le projet | Métadonnées du paquet |
| `certifi` | MPL-2.0 | Copyleft **au niveau du fichier** : seules les modifications de ses propres fichiers devraient être publiées. On ne les modifie pas. | Métadonnées du paquet |
| Portrait de l'IA (`frontend/public/ai/portrait.webp`, dérivé du PNG fourni par Valentino) | **Non vérifiée** | À établir **avant tout rendu public** : où cette image a été produite, quelles conditions d'usage s'appliquent, si sa réutilisation est permise. Elle portait le texte « TURNOVER MARKETING », marque d'un tiers : `frontend/scripts/prepare_ai_frames.py` l'efface par défaut. Ne pas présenter l'image comme originale tant que ce point n'est pas réglé. | Fichier fourni ; origine non documentée |
| `framer-motion` | MIT | Garder la notice | Métadonnées des paquets |
| `pytest`, `ruff` et les dépendances de `pytest` (`iniconfig`, `pluggy` : MIT ; `packaging` : Apache-2.0 ou BSD-2-Clause ; `Pygments` : BSD-2-Clause) | — | Rien : ce sont des outils de dev, pas livrés avec le produit | Métadonnées du paquet |

Aucune dépendance actuelle n'est sous licence « copyleft fort » (GPL, AGPL),
qui obligerait à publier le code de CodeSensei sous la même licence. **À
vérifier pour chaque nouvelle dépendance** (MCP, framework web…) dans la PR
qui l'ajoute. Les moteurs de recherche (DuckDuckGo, Bing en repli) ne sont pas des
bibliothèques mais des services : leurs conditions sont traitées au risque L8 de l'[analyse](README.md).

Les **réponses du modèle** : la licence Apache-2.0 couvre les poids du modèle,
pas ce qu'il génère. Le code produit avec CodeSensei appartient à
l'utilisateur, mais il peut ressembler à du code existant sous licence :
c'est une raison de plus de le relire.

## La licence de CodeSensei lui-même : décision à prendre

Le dépôt n'a **pas de fichier `LICENSE`**. Par défaut, le code est donc
« tous droits réservés » au profit de ses auteurs : personne, pas même un
membre de l'équipe après le projet, n'a formellement le droit de le
réutiliser ou de le publier.

| Option | Pour | Contre |
| --- | --- | --- |
| Pas de licence (situation actuelle) | Rien à faire | Réutilisation juridiquement floue, y compris pour les auteurs ; empêche de publier le projet en portfolio proprement |
| MIT | Simple, compatible avec toutes nos dépendances, la plus répandue | N'importe qui peut réutiliser le code, y compris commercialement, sans rien rendre |
| Apache-2.0 | Même liberté que MIT, plus une clause explicite sur les brevets ; même licence que `requests` et les modèles Qwen | Un peu plus lourde (fichier NOTICE, mention des modifications) |
| AGPL-3.0 | Oblige quiconque propose CodeSensei en service en ligne à publier ses modifications | Freine toute réutilisation commerciale, ce qui contredit un éventuel modèle économique (voir `docs/business/`) |

À vérifier aussi : le **règlement d'the school** sur la propriété du code
produit pendant les projets, avant de choisir. La décision prise fera l'objet
d'un ADR.
