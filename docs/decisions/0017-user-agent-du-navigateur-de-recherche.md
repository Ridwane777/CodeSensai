# ADR-0017 — Recherche web : Chromium se présente comme un navigateur normal (user-agent)

- **Statut** : Accepté (2026-11-01, validé par l'équipe)
- **Date** : 2026-10-14
- **Décideurs** : Meric Gbemetonou (Lot B), après un retour de l'équipe sur la démo
- **Lot concerné** : B (outil `web_search`, sandbox navigateur). Complète l'[ADR-0014](0014-moteur-de-recherche-bing.md), qui n'est pas modifié.

## Contexte
Après le passage à Bing (ADR-0014), l'équipe a constaté que `web_search`
répondait mais renvoyait **0 résultat** pour « Ollama tool calling API » et
« docker run read-only tmpfs », et des résultats hors sujet pour
« python dataclass default factory ». La même requête faite avec `curl` donnait
10 résultats.

Cause mesurée le 2026-10-14 (image `sensai-browser`, Chromium 155.0.8059.39,
requête « Ollama tool calling API », nombre d'occurrences de `b_algo` dans le dump) :

| user-agent | `b_algo` |
| --- | --- |
| défaut du mode sans écran (annonce `HeadlessChrome`) | 0 |
| `Chrome/131.0.0.0` | 0 |
| `Chrome/155.0.0.0` (même version que le Chromium de l'image) | 83 |

Bing ne bloque pas ouvertement : il sert une page appauvrie à ce qui ressemble
à un robot, y compris à un user-agent dont la version ne correspond pas au
moteur réel.

## Options envisagées
| Option | Pour | Contre |
| --- | --- | --- |
| A. Ne rien changer | Zéro code | `web_search` inutilisable en démonstration |
| B. **`--user-agent` d'un Chrome normal, à la version du Chromium de l'image** | Une ligne ; mesuré : 10 résultats sur les 3 requêtes ; le reste de la sandbox ne change pas | Fragile (voir ❌) ; imite un navigateur |
| C. API de recherche (Brave Search API, SearXNG auto-hébergé) | Contrat clair, plus d'imitation | Clé d'API ou service à déployer, donc un autre ADR ; non testé ici |

## Décision
Option B. `BrowserConfig.user_agent` (valeur par défaut :
`Mozilla/5.0 (X11; Linux x86_64) … Chrome/155.0.0.0 Safari/537.36`) est passé
à Chromium par `--user-agent=`. Le réseau reste limité à `www.bing.com`,
JavaScript reste coupé par la politique de l'image, le conteneur reste jetable.

## Conséquences
- ✅ Mesuré le 2026-10-14 : 10 résultats pour chacune des trois requêtes en échec (environ 4 s), aucun conteneur laissé derrière ; le premier résultat est la documentation officielle (docs.ollama.com, docs.python.org).
- ✅ Changement minimal, couvert par un test (`test_browser_presents_itself_as_a_regular_browser_not_headless`).
- ❌ **Couplage à la version de Chromium** : avec `Chrome/131` Bing sert encore 0 résultat. Si l'image est reconstruite avec un autre Chromium, il faut aligner `user_agent` (`chromium --version`), sinon l'outil retombe en silence sur « 0 résultat ».
- ❌ **Fragile** : Bing peut durcir sa détection à tout moment ; on imite un navigateur au lieu d'utiliser un contrat.
- ❌ **Conditions d'utilisation** : se faire passer pour un navigateur ordinaire accentue le point déjà ouvert de l'ADR-0014 (accès automatisé sans l'API de Microsoft). Acceptable pour une démonstration pédagogique, pas pour un produit.
- ❌ L'outil renvoie `ok: true` avec 0 résultat quand Bing sert une page appauvrie : l'échec reste invisible pour le modèle. Piste non traitée ici : traiter « page de résultats sans `b_algo` » comme `SearchEmptyPage`.
- Suivi : si Bing bloque malgré tout, passer à Brave Search API ou SearXNG (option C) par un nouvel ADR.
