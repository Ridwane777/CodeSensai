# ADR-0040 — Recherche web : DuckDuckGo HTML d'abord, Bing en repli

- **Statut** : Accepté (2026-10-24) ; remplace l'[ADR-0014](0014-moteur-de-recherche-bing.md)
- **Date** : 2026-10-24
- **Décideurs** : Ridwane (lot C) et Meric (lot B)
- **Lot concerné** : B (`execution/sandbox/`, image `docker/browser`). Ne change ni l'interface de l'outil `web_search` ni son contrat.

## Contexte

L'[ADR-0014](0014-moteur-de-recherche-bing.md) a remplacé DuckDuckGo par Bing
le 2026-10-14 : DuckDuckGo servait un défi anti-robot (HTTP 202, page
« anomaly ») au réseau de développement. Il notait deux ❌ : « fragile par
nature » et « pas de moteur de repli ».

Essai complet du 2026-10-24 : l'agent ne trouvait pas la documentation
d'Ollama sur le tool calling. Mesure directe, même image, même jour :

| Requête | Bing : premiers résultats |
| --- | --- |
| `python asyncio gather example` | python.org, python.org/downloads, online-python.com, w3schools… |
| `ollama tool calling activation` | ollama.com, ollama.com/download/windows, github.com/ollama… |
| `Ollama tool calling official documentation` | **les mêmes 10 résultats** que la ligne précédente |

Bing reçoit bien la requête entière (elle figure dans le titre de la page et
dans le champ de recherche) mais ne répond que sur le **premier mot**. C'est
une page dégradée servie au navigateur automatisé, pas un défaut du code.

Même jour, DuckDuckGo HTML (image de test qui n'autorise que
`html.duckduckgo.com`) : 4 requêtes sur 4 avec des résultats pertinents, dont
`docs.ollama.com/capabilities/tool-calling` en premier pour les deux requêtes
Ollama, et la documentation FastAPI sur les SSE pour « fastapi streaming
response sse ». Aucun défi anti-robot depuis ce réseau.

## Options envisagées

| Option | Pour | Contre |
| --- | --- | --- |
| A. Garder Bing seul | Rien à changer | Mesuré : résultats sur le premier mot seulement ; l'outil est inutile en démo |
| B. DuckDuckGo HTML seul | Mesuré : pertinent (4/4) ; page faite pour les navigateurs sans JavaScript ; meilleure confidentialité | Bloqué sur un autre réseau le 2026-10-14 : on retomberait dans le même piège |
| C. **DuckDuckGo HTML d'abord, Bing en repli** (même conteneur, même budget de temps) | Pertinent quand DuckDuckGo répond ; l'outil sert encore si DuckDuckGo bloque ou ne trouve rien ; aucune clé | Deux pages HTML à suivre au lieu d'une ; si DuckDuckGo bloque, on retombe sur la page dégradée de Bing ; le conteneur peut joindre deux hôtes au lieu d'un |
| D. API de recherche (Brave Search API) ou SearXNG auto-hébergé | Contrat clair, plus de lecture de page | Clé d'API (secret, quota, coût) ou service à déployer ; non mesuré ici |

## Décision

Option C. `BrowserConfig.search_hosts = ("html.duckduckgo.com", "www.bing.com")`.
`BrowserSandbox.search` essaie chaque moteur dans l'ordre et garde le premier
qui renvoie des résultats. Il passe au suivant si la page est bloquée, vide,
inattendue, injoignable ou sans résultat ; il ne le fait pas si l'image
manque, si Docker est en panne ou si la requête est invalide (le second moteur
échouerait de la même façon). Les deux essais partagent le même budget de
temps (25 s par défaut, 45 s au plus) ; le repli n'est lancé que s'il reste au
moins 5 s.

Confinement inchangé dans son principe : le résolveur de Chromium et la
politique de l'image n'autorisent que ces deux hôtes, JavaScript reste coupé,
le conteneur reste jetable. Le moteur est reconnu à la page elle-même
(`result__a` pour DuckDuckGo, `b_algo` pour Bing) ; les liens de redirection
des deux moteurs sont décodés sur l'hôte et leurs liens internes écartés.

## Conséquences

- ✅ Résultats pertinents quand DuckDuckGo répond (mesures dans
  [web-search.md](../performance/web-search.md)).
- ✅ Un moteur de repli : un blocage de DuckDuckGo ne rend plus l'outil muet.
- ✅ Toujours aucune clé ni secret ; la requête part d'abord chez DuckDuckGo,
  plus protecteur que Microsoft.
- ❌ Deux pages HTML à suivre : si l'une change, ses résultats disparaissent
  sans erreur (tests sur des pages enregistrées, pas sur les sites réels).
- ❌ Le repli sur Bing donne aujourd'hui des résultats médiocres (premier mot
  seulement) : mieux que rien, pas une vraie solution de secours.
- ❌ Le conteneur peut joindre deux hôtes au lieu d'un (toujours aucun autre).
- ❌ Conditions d'utilisation : comme pour Bing, l'accès automatisé à
  DuckDuckGo n'est pas un usage garanti ; usage ponctuel d'un projet
  pédagogique (voir `docs/legal/`).
- Suivi : si les deux moteurs bloquent ou se dégradent, passer à l'option D
  derrière le même `BrowserSandbox` ; reconstruire l'image
  (`docker build -t sensai-browser:latest docker/browser`) après ce
  changement, l'ancienne n'autorise que Bing.
