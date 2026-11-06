# T3 — Recherche web : essais réels du moteur

> **Latest trial, 2026-11-06** ([report](essais/essai-2026-11-06.md)), qwen3:8b on the team laptop (CPU) and qwen3-coder:30b on a 24 GB GPU pod: isolated web search: ✅ `python.org` with both models, qwen3:8b on CPU 11 min 16, qwen3-coder:30b on GPU 10 s. Earlier measurements below.

Mesures du 2026-10-24, poste Linux (Docker local, image `sensai-browser`),
agent sur le pod RunPod (`qwen3-coder:30b`). Décision :
[ADR-0040](../decisions/0040-recherche-web-duckduckgo-et-repli-bing.md).
Chaque requête est mesurée une fois : ce sont des ordres de grandeur.

## Pourquoi changer : Bing ne répondait plus que sur le premier mot

Outil `web_search` appelé directement, image d'origine (Bing seul) :

| Requête | Trois premiers résultats |
| --- | --- |
| `python asyncio gather example` | python.org, python.org/downloads, online-python.com |
| `ollama tool calling activation` | ollama.com, ollama.com/download/windows, github.com/ollama/ollama |
| `Ollama tool calling official documentation` | identiques à la ligne précédente (les 10) |
| `tool calling ollama docs` | aucun résultat |

La page renvoyée contient bien la requête entière (titre de la page, champ de
recherche) : Bing la reçoit, mais sert une page dégradée au navigateur
automatisé. Dans l'essai complet du même jour, l'agent répondait « je n'ai pas
trouvé de documentation officielle » trois fois sur trois.

## Après : DuckDuckGo HTML, Bing en repli

Image reconstruite (`docker build -t sensai-browser:latest docker/browser`),
outil appelé directement :

| Requête | Durée | Trois premiers résultats |
| --- | --- | --- |
| `ollama tool calling activation` | 5,1 s | docs.ollama.com/capabilities/tool-calling, deepwiki.com/…/tool-calling, ollama.com/blog/tool-support |
| `Ollama tool calling official documentation` | 4,5 s | docs.ollama.com/capabilities/tool-calling, docs.ollama.com/index, lzw.me/…/tool-calling |
| `python asyncio gather example` | 4,7 s | pythontutorial.net/…/python-asyncio-gather, superfastpython.com/asyncio-gather, slingacademy.com/…/gather |
| `fastapi streaming response sse` | 5,1 s | fastapi.tiangolo.com/tutorial/server-sent-events, fastapi.tiangolo.com/reference/sse, devdojo.com/…/sse-with-fastapi |
| `comment configurer pytest pour un projet python` | 5,3 s | adamcours.fr/…/pytest, fr.w3docs.com/…/python-pytest, pasclairpython.fr/…/pytest |

Par l'agent (vrai CLI, pod) : « Cherche sur le web la documentation officielle
d'Ollama sur le tool calling » → un appel à `web_search`, 10 résultats, et la
réponse cite `docs.ollama.com/capabilities/tool-calling` (21,5 s pour le tour).

Le repli sur Bing est vérifié par les tests (page bloquée, page vide, aucun
résultat, budget de temps partagé), pas sur le site réel : DuckDuckGo n'a pas
bloqué depuis ce réseau pendant l'essai.

## Limites

- Une mesure par requête, un seul réseau.
- Le repli sur Bing donne aujourd'hui des résultats médiocres (premier mot
  seulement).
- Les deux moteurs sont lus en HTML : un changement de balisage peut vider
  les résultats sans erreur (tests sur des pages enregistrées).
