# ADR-0022 — Un tour = un flux SSE ouvert par POST ; l'agent tourne dans un thread

- **Statut** : Accepté (2026-11-01, validé par l'équipe)
- **Date** : 2026-10-14
- **Décideurs** : Valentino (Lot D)
- **Lot concerné** : D (impacte A, qui a écrit le contrat, et B, dont la passerelle impose la confirmation)

## Contexte
Écrit **après** les user stories [US-WEB-1 à 4, 7 et 15](../architecture/web-api.md), qui fixent le comportement
attendu : réponse en flux, confirmation avant action risquée avec délai, déconnexion du navigateur, interruption,
un seul tour à la fois, erreurs claires.

Le Lot A a déjà choisi le principe ([api-contract.md](../architecture/web/api-contract.md)) : `POST /messages` ouvre un flux SSE.
Reste à décider **comment le serveur l'implémente**, parce que le cœur impose deux contraintes que le squelette de
[web-api.md](../architecture/web/web-api.md) ne respectait pas :

- `run_agent_turn` est un **générateur synchrone** et bloquant ;
- la confirmation est une **fonction synchrone** `Callable[[ConfirmationRequest], bool]`, et la passerelle exige
  un résultat `is True` : une coroutine serait toujours refusée.

Un serveur asynchrone qui itérerait le générateur directement bloquerait sa boucle, et la confirmation, qui attend une
requête que cette même boucle devrait servir, s'interbloquerait (écarts 1 et 2 de [web-api-alignement.md](../architecture/web/web-api-alignement.md)).

## Options envisagées
| Option | Pour | Contre |
| --- | --- | --- |
| WebSocket (un canal bidirectionnel par session) | Un seul canal pour les événements, les confirmations et l'interruption ; reconnexion maîtrisable | Plus de code (protocole, ping, reprise), authentification moins simple, hors du contrat déjà écrit par le Lot A |
| Interrogation répétée (polling) | Aucune connexion longue | Latence de la réponse mot à mot, charge inutile, tous les inconvénients sans les avantages |
| `GET` + `EventSource` pour le flux, `POST` à part pour les messages | Reconnexion automatique du navigateur | Ne passe pas l'authentification par en-tête (`EventSource` n'envoie pas d'en-tête personnalisé), sépare un message de son flux, et la reconnexion rejouerait un tour qu'on ne sait pas reprendre |
| Réécrire le cœur en asynchrone | Serveur plus naturel | Touche `core/` et `execution/` des Lots A et B pour un besoin du seul web ; hors périmètre |
| **`POST /messages` renvoie le flux SSE ; confirmation et interruption par `POST` séparés ; l'agent tourne dans un thread** | Conforme au contrat du Lot A ; le cœur n'est pas modifié ; testé de bout en bout (15 tests) | Voir les inconvénients |

## Décision
1. `POST /api/sessions/{id}/messages` répond en `text/event-stream` et reste ouvert pendant tout le tour. Le client lit le flux avec `fetch` (pas `EventSource`).
2. La confirmation (`POST /confirm`) et l'interruption (`POST /interrupt`) sont des requêtes séparées, que le serveur relie au tour en cours par l'identifiant de session.
3. **L'agent tourne dans un thread** ; ses événements passent à la boucle asynchrone par une file ; une action de plus à la fois par session (`409` sinon), plusieurs sessions en parallèle.
4. **Le confirmeur est une fonction ordinaire** qui publie `confirm_request`, puis attend un `threading.Event`. Il expire **légèrement avant** la passerelle (0,1 s) : une réponse tardive reçoit `404`, et non un `204` trompeur.
5. Pas de réponse à temps, déconnexion du navigateur ou interruption = **refus** ; jamais une acceptation par défaut.
6. Un flux coupé n'est **pas repris** : le tour est abandonné et n'entre pas dans l'historique ; le client renvoie son message. (Question laissée ouverte par le Lot A : voici notre réponse.)

## Conséquences
- ✅ Le cœur et la passerelle restent inchangés ; la CLI et le web consomment la même boucle.
- ✅ Les comportements des stories sont vérifiés : `done` toujours en dernier, `tool_call` et `tool_return` appariés par `id`, refus par délai, onglet fermé, interruption, deux sessions sans mélange.
- ❌ **Pas de reconnexion automatique** : `EventSource` ne sait pas faire de `POST`. Une coupure réseau en pleine réponse fait perdre le tour ; l'utilisateur doit renvoyer son message.
- ❌ **Un thread par tour actif.** Négligeable pour un usage individuel ; à plafonner et à revoir si plusieurs personnes utilisent un même serveur.
- ❌ **L'interruption est coopérative** : un thread Python ne se tue pas. Elle prend effet au prochain événement ; un appel au modèle déjà parti ou un outil en cours (une exécution de code, par exemple) finit avant de s'arrêter, dans la limite de ses propres délais.
- ❌ **Un intermédiaire qui met les réponses en mémoire tampon** (certains proxys) casse le flux mot à mot ; l'en-tête `X-Accel-Buffering: no` aide, sans garantie.
- ❌ **Mesuré sur un faux Ollama**, sur une seule machine, sans mesure de charge ; la tenue avec un vrai modèle n'est pas démontrée.
- Lien avec [ADR-0015](0015-confirmation-web-synchrone.md) (Lot B, écrit en parallèle) : les deux décisions concordent (confirmeur synchrone, agent dans un thread). Le point 4 sera réalisé avec `WebConfirmationBroker` du Lot B plutôt qu'avec le confirmeur du prototype ; la marge d'expiration de 0,1 s est à reporter dans le broker si le Lot B l'accepte.
- Suivi : confirmer avec le Lot A (questions 1 à 5 de [web-api-alignement.md](../architecture/web/web-api-alignement.md)). **Seuil de révision** : si plus de quelques sessions actives en parallèle sont nécessaires, passer à un pool de threads borné ou revoir le choix du transport.
