# ADR-0015 — Confirmation depuis le navigateur : un broker synchrone, sans changer le contrat de la passerelle

- **Statut** : Accepté (2026-11-01, validé par l'équipe)
- **Date** : 2026-10-14
- **Décideurs** : Meric Gbemetonou (Lot B), à valider avec le Lot D (qui branche le broker dans le serveur)
- **Lot concerné** : B (`execution/web_confirmation.py`) ; D est impacté : il doit faire tourner l'agent dans un thread de travail

## Contexte
La confirmation humaine avant une action risquée (feature A3) existe pour la
CLI (`human_in_loop.py`). La passerelle d'outils ([ADR-0006](0006-passerelle-d-outils.md))
appelle un `Confirmer` **synchrone** : `(ConfirmationRequest) -> bool`, qui
bloque jusqu'à la réponse. Dans un navigateur la réponse arrive plus tard,
par une autre requête HTTP (`POST /sessions/{id}/confirm`, voir
[web-api.md](../architecture/web/web-api.md)), pendant que la requête qui a lancé l'agent est un
flux SSE toujours ouvert.

Contraintes : un oui explicite est la seule façon d'autoriser (délai, onglet
fermé, panne ou réponse ambiguë = refus) ; l'interface web reste une façade
([ADR-0005](0005-interface-web-facade.md)) ; le code du Lot B ne doit pas
dépendre du framework web que le Lot D choisira ; la passerelle ne change pas.

## Options envisagées
| Option | Pour | Contre |
| --- | --- | --- |
| A. **Broker synchrone** (`threading.Event`) : le confirmer bloque le thread de l'agent, `resolve()` le réveille | Contrat de la passerelle inchangé ; aucun framework ; testable sans serveur ; même garde-fous (seul `True` autorise) que la CLI | Un thread bloqué par demande en attente ; l'agent doit tourner hors de la boucle d'événements |
| B. Confirmer `async` (la passerelle `await` la réponse) | Pas de thread bloqué côté serveur | Change le contrat `Confirmer` de l'[ADR-0006](0006-passerelle-d-outils.md), donc la passerelle, la CLI et leurs tests ; force toute la chaîne (boucle ReAct, outils) à devenir `async` |
| C. Interrogation d'un dictionnaire de session (le confirmer boucle sur `sessions[id][confirm_id]`) | Très simple à écrire | Attente active ou `sleep` ; dictionnaire partagé sans verrou ni nettoyage garanti ; le délai, la fermeture et les doublons sont à refaire par le Lot D ; difficile à tester |
| D. WebSocket bidirectionnel au lieu de SSE + POST | Un seul canal pour la question et la réponse | Remet en cause le contrat de transport déjà documenté ; il faudrait quand même un moyen de bloquer l'agent jusqu'à la réponse, donc le problème du confirmer reste entier |

## Décision
Option A. `WebConfirmationBroker` fournit un `Confirmer` synchrone. Il publie
un événement `confirm_request` via une fonction `emit` fournie par le serveur,
puis attend au plus `timeout_s` qu'on appelle `resolve(confirm_id, approved)`.
Seul `approved is True` autorise ; délai dépassé, `close()`, panne de `emit`
ou identifiant inconnu valent refus. Un broker par session ; `close()` à la
déconnexion du navigateur.

## Conséquences
- ✅ La passerelle, la CLI et leurs tests ne changent pas (`git diff main -- src/sensai/execution/gateway.py` est vide).
- ✅ Les règles de sûreté sont testées une fois, côté Lot B (35 tests dans `tests/execution/test_web_confirmation.py`), et non réécrites par chaque serveur.
- ✅ Aucun framework importé : le Lot D garde le choix FastAPI, Flask ou autre.
- ❌ **Un thread est bloqué par confirmation en attente**, jusqu'à `timeout_s` (60 s par défaut). Acceptable pour un agent par session, à revoir si un serveur doit tenir des centaines de sessions simultanées (seuil non mesuré).
- ❌ **L'agent doit tourner hors de la boucle d'événements** (thread de travail) : appeler `run_agent_turn` directement dans un `async def` figerait le serveur pendant l'attente. C'est une contrainte pour le Lot D, documentée dans `web-api.md` mais non vérifiable par nos tests.
- ❌ **Un thread d'attente peut survivre brièvement** : la passerelle impose son propre délai (`_run_bounded`, thread daemon) et le broker attend aussi `timeout_s`. Si la passerelle expire la première, le thread du broker reste quelques millisecondes avant de se nettoyer ; il ne peut ni exécuter l'outil ni laisser une demande en attente.
- ❌ Une réponse qui arrive après le délai ou après `close()` est rejetée (`resolve` retourne `False`, la route répond 404) : l'utilisateur qui a cliqué trop tard doit le savoir, c'est à l'interface de l'afficher.
- Suivi : tests de concurrence dans `tests/execution/test_web_confirmation.py` ; à revoir si le serveur Lot D passe à plusieurs processus (le broker vit en mémoire d'un seul processus, la route `confirm` doit atteindre le même).
