# ADR-0014 — Moteur de la recherche web : Bing (page HTML) à la place de DuckDuckGo

- **Statut** : Remplacé par [ADR-0040](0040-recherche-web-duckduckgo-et-repli-bing.md)
- **Date** : 2026-10-14
- **Décideurs** : Meric Gbemetonou (Lot B), après constat sur la machine de développement
- **Lot concerné** : B (outil `web_search`, sandbox navigateur). Ne change ni l'interface de l'outil ni son contrat.

## Contexte
L'outil `web_search` ([ADR-0012 sandbox](0012-sandbox-docker-chromium.md)) lit la
page de résultats d'un moteur avec Chromium dans un conteneur jetable, puis
extrait titre, URL et extrait. Le moteur initial était DuckDuckGo
(`html.duckduckgo.com/html/`).

Constat du 2026-10-14, depuis le réseau de développement : DuckDuckGo répond
**HTTP 202 avec une page « anomaly » (défi anti-robot)** au lieu des résultats.
Résultat côté outil : un dump vide ou une page de défi, et un message
« le moteur n'a pas pu être joint » qui masquait la vraie cause. Le moteur
bloque ce réseau ; ce n'est pas un bogue du parseur.

Mesuré le même jour avec Bing : `curl` et Chromium (dans l'image du projet)
reçoivent une page de résultats avec 10 `<li class="b_algo">`.

Autre constat, indépendant du moteur : avec
`--blink-settings=scriptEnabled=false`, `chromium --dump-dom` n'affiche **rien**
(mesuré sur Bing). JavaScript reste désactivé par la politique d'entreprise de
l'image (`"JavascriptEnabled": false`, vérifié avec une page de test dont le
script ne s'exécute pas) ; le drapeau est retiré de la ligne de commande.

## Options envisagées
| Option | Pour | Contre |
| --- | --- | --- |
| A. DuckDuckGo `/html/` (statu quo) | Aucun compte, bonne image de confidentialité | **Bloqué ici** (HTTP 202, défi anti-robot) ; rien ne garantit que ça passe sur le réseau de la démo |
| B. DuckDuckGo « lite » | Page plus simple | Même fournisseur, même anti-robot probable ; non testé |
| C. **Bing, page HTML** (`www.bing.com/search?q=`) | Testé : résultats servis à `curl` et à Chromium ; aucune clé, aucun secret ; structure stable (`b_algo`, `b_caption`) | Analyse d'une page, pas d'une API ; liens de redirection à décoder ; conditions d'utilisation (voir ❌) |
| D. Brave Search (page HTML) | Index indépendant | Non testé ; protections anti-robot inconnues |
| E. SearXNG auto-hébergé | Pas de blocage par moteur, agrège plusieurs sources | Un service de plus à déployer et à maintenir ; il interroge lui-même des moteurs qui peuvent le bloquer |
| F. API Bing payante | Contrat clair, pas de scraping | Clé d'API (secret), quota et coût ; offre à revérifier ; sort du périmètre « sans service payant » |

Seules A et C ont été testées sur la machine. B, D, E et F sont écartées sur
lecture, pas sur mesure.

## Décision
Option C. L'outil interroge `https://www.bing.com/search?q=<requête>`. Le
navigateur ne résout et n'ouvre que `www.bing.com` (réglage `search_host`,
résolveur Chromium et politique de l'image alignés). Les liens de résultat de
Bing (`/ck/a?…&u=a1<base64url>`) sont décodés sur l'hôte ; les liens internes à
Bing sont écartés. Les pages bloquées, vides ou inattendues sont signalées par
un code d'erreur précis (`SearchBlocked`, `SearchEmptyPage`, `SearchUnavailable`,
`SearchUnexpectedPage`) au lieu d'un « injoignable » unique.

## Conséquences
- ✅ `web_search` fonctionne sur la machine de développement : 10 résultats pour « python asyncio » lors du test en direct du 2026-10-14 (une seule mesure, environ 4 s).
- ✅ Toujours aucune clé d'API ni secret ; la surface exposée du conteneur reste un seul hôte.
- ✅ Les échecs disent la vraie cause au modèle et à l'utilisateur (page bloquée, vide, réseau coupé, page inattendue) ; chaque cas est testé.
- ❌ **Fragile par nature** : on lit le HTML de Bing, qui peut changer sans préavis. Le parseur s'appuie sur trois repères structurels (`b_results`, `b_algo`, `b_caption`) et sur le format `u=a1…` des liens ; si l'un change, l'outil peut renvoyer « aucun résultat » sans erreur. Les tests tournent sur une page enregistrée, pas sur le site réel.
- ❌ **Conditions d'utilisation** : les conditions de Microsoft limitent en principe l'accès automatisé à Bing hors API. Usage ponctuel d'un projet pédagogique, mais ce n'est pas un usage garanti ; à faire relire avant tout usage commercial (voir `docs/legal/`).
- ❌ **Confidentialité moindre que DuckDuckGo** : la requête part chez Microsoft, qui peut la rattacher à l'adresse IP. Ne rien mettre de confidentiel dans une recherche.
- ❌ Bing peut lui aussi présenter un défi anti-robot depuis un autre réseau ; l'outil le signalerait (`SearchBlocked`) mais n'a pas de moteur de repli.
- Suivi : tests `tests/execution/sandbox/test_search_parsing.py` (page enregistrée le 2026-10-14) et `test_browser_sandbox.py`. À revoir si Bing change son balisage ou bloque l'outil : passer à un SearXNG auto-hébergé (E) ou à une API (F), derrière le même `BrowserSandbox`/`search_parsing`.
