# Interface web réelle : essai de bout en bout

Décision : [ADR-0035](../decisions/0035-serveur-web-reel.md).

**Méthode** (2026-10-18). `sensai-web` lancé sur un petit projet d'essai (un
`README.md`, un `calc.py`), avec le modèle `qwen3-coder:30b` et `bge-m3` sur
le pod RunPod, l'interface construite (`npm run build`) servie par le même
serveur. Le scénario pilote l'API comme le navigateur : mêmes routes, même
jeton, même flux SSE.

| Étape | Résultat | Temps |
| --- | --- | --- |
| `GET /api/config` sans jeton | `401` | — |
| `GET /` (interface construite) | `200` | — |
| « Que fait la fonction add dans calc.py ? » | `rag_sources` puis la réponse, qui cite `calc.py` lignes 1-2 | 11,8 s |
| La même question | **Servie par le cache** (`cache_hit`), sans appel au modèle | 1,4 s |
| « Crée le fichier test_calc.py… » | Le modèle a d'abord **demandé la permission par écrit** au lieu d'appeler l'outil (comportement du modèle, pas du serveur) | 23,5 s |
| « Oui, crée-le maintenant… » | `tool_call` → `confirm_request` (diff de création) → « oui » (`204`) → fichier créé | — |
| « Crée aussi notes.txt… » puis « non » | `tool_return` en échec (« L'utilisateur a refusé… »), fichier **non** créé | — |
| `/state` | Réponse de la commande, sans appel au modèle | 0,0 s |
| Longue explication, interrompue après 0,5 s | `done` avec `reason: "interrupted"`, rien d'enregistré | 4,1 s |
| `GET /export?format=md` | `200`, `text/markdown` | — |
| `GET /api/sessions` | La session, avec son titre et ses 6 messages | — |

## Essai cliqué dans un navigateur

Le même serveur, piloté dans Chrome (Chrome DevTools) comme un utilisateur :

| Parcours | Résultat |
| --- | --- |
| Ouvrir `http://127.0.0.1:8765/` | Écran « Connexion à CodeSensei » (serveur détecté) |
| Faux jeton | « Jeton refusé… », on reste sur l'écran |
| Vrai jeton | Badge « Agent réel · qwen3-coder:30b » ; après rechargement, reconnexion sans redemander |
| « Que fait la fonction add dans calc.py ? » | Réponse en direct ; onglet Sources : `calc.py:1-2` (77 %) |
| Demande d'écriture | Carte « Action risquée · accord requis » avec le détail ; « Autoriser » → « ✓ Autorisé », observation « Created … (66 bytes) », fichier présent sur le disque |
| Seconde demande, « Refuser » | « ✕ Refusé », l'agent reçoit le refus, fichier absent |
| Longue explication, « ■ Arrêter » | « Génération interrompue », la saisie redevient possible |
| « Modifier le message » | Barre « Versions » : branche principale et « Variante 1 », une nouvelle session côté serveur |
| Page d'accueil, connectée | Pastille « Connecté à l'agent réel · qwen3-coder:30b » |
| Page Journal, après un appel de `read_file` | `read_file`, ses arguments, 21 ms, « Succès » ; 1 appel, 21 ms en moyenne, 0 % d'échec ; « Tokens utilisés » reste à 0 (simulé) |
| Page Export | L'aperçu Markdown contient la vraie conversation et l'appel d'outil ; le lien de partage est annoncé comme simulé |
| Console du navigateur | Aucune erreur ni avertissement |

**Défauts visibles trouvés par cet essai, corrigés et testés :**
- les blocs de code du modèle (trois accents graves) s'affichaient en texte brut ;
- l'accueil du chat et la page d'accueil affichaient « moteur simulé » ou « démo simulée » même connectés ;
- le texte écrit avant et après un appel d'outil était collé (« …write_file.J'ai créé… ») ;
- quand le modèle écrit son appel d'outil en texte (ADR-0031), l'interface affichait `<function=write_file>…` ; il est maintenant masqué, comme dans le CLI.

## Tests automatiques

- **Serveur** (`tests/web/`, 102 tests du serveur réel et les 15 du prototype) :
  jeton sur chaque route, documentation désactivée, CORS fermé, sessions
  partagées avec le CLI, flux et `done` en dernier, erreurs du modèle et du
  cœur, un tour à la fois, deux sessions en parallèle, confirmation (oui, non,
  délai, réponse tardive, double réponse, valeurs `"true"`/`1`/`"yes"`
  refusées), interruption, onglet fermé, entrée bloquée, commandes, cache,
  sources du RAG, bifurcation, export filtré des secrets, mémoires,
  interface servie, parité des outils avec le CLI, purge au démarrage (#65).
  Lancés 5 fois de suite : 117/117 à chaque fois.
- **Interface** (`frontend/tests/`, 166 tests) : traduction du flux
  (`wire.test.ts`), moteur réel contre un faux serveur (`httpEngine.test.ts`),
  connexion par jeton et mode démonstration (`connection.test.tsx`).

## Défaut trouvé en écrivant les tests, corrigé

`approved` était un booléen pydantic ordinaire : `"true"`, `1` ou `"yes"`
auraient été pris pour « oui » et auraient **autorisé une écriture**. Seul le
booléen JSON `true` est désormais accepté (`StrictBool`), le reste reçoit `400`.

## Limites

- **Recharger la page repart d'une conversation vide** dans l'interface : la
  session reste enregistrée côté serveur (et reprenable dans le CLI), mais
  l'interface ne la recharge pas encore.
- Le résumé d'une confirmation contient le **chemin complet** du fichier
  (texte produit par l'outil `write_file`) : il est visible dans le
  navigateur, sur la machine locale.
- Un seul utilisateur, sur la machine locale ; pas de mesure de charge.
