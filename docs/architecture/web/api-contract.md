# Contrat entre l'interface web et le cœur

**Statut : brouillon — à valider entre le Lot A et le Lot D avant que le
développement web commence.** C'est le document qu'ADR-0005 annonce comme
bloquant : tant qu'il n'est pas accepté, le Lot D ne peut pas travailler en
parallèle.

## L'idée en une phrase

Un tour d'agent ne produit pas du texte, il produit **une suite
d'événements**. La CLI les affiche dans un terminal, le web les envoie au
navigateur en JSON. Les deux interfaces consomment la même source, donc elles
ne peuvent pas raconter deux histoires différentes.

La source, c'est `sensai.core.agent.run_agent_turn()`, qui renvoie des objets
définis dans `sensai/core/events.py`.

## Les événements

| Type | Champs | Ce que c'est |
|---|---|---|
| `token` | `text` | Un morceau de la réponse finale, à afficher au fil de l'eau |
| `thought` | `text` | Le raisonnement avant d'agir — à présenter autrement qu'une réponse |
| `tool_call` | `id`, `name`, `arguments` | L'agent demande l'exécution d'un outil |
| `tool_return` | `id`, `name`, `ok`, `content` | Le résultat de cet outil |
| `error` | `message` | Le tour est perdu (modèle injoignable, etc.) |
| `done` | `reason` | Fin du tour — toujours le dernier événement |

Trois règles qui comptent pour l'affichage :

1. **`id` relie un `tool_call` à son `tool_return`.** Deux outils peuvent
   s'enchaîner dans le même tour ; sans cet identifiant, l'interface ne sait
   plus quel résultat appartient à quel appel.
2. **Un outil qui échoue n'est pas une `error`** : c'est un `tool_return`
   avec `ok: false`, et l'agent continue. `error` signifie « ce tour est
   perdu », rien ne suivra à part `done`.
3. **`done` arrive toujours**, y compris après une `error`. C'est le signal
   pour rendre la main : réafficher le prompt en CLI, fermer le flux côté web.

Côté Python, `to_wire(event)` transforme un événement en dictionnaire JSON.
Les noms réseau (`token`, `tool_call`, …) sont figés explicitement dans
`events.py` : renommer une classe Python ne cassera pas le front.

## Les routes HTTP proposées

À discuter — c'est la partie qui appartient au Lot D.

```
POST   /api/sessions              -> { "session_id": "..." }
GET    /api/sessions              -> liste des sessions (dépend du Lot C)
GET    /api/sessions/{id}         -> l'historique d'une session
POST   /api/sessions/{id}/messages
       body: { "content": "..." }
       -> flux SSE d'événements
POST   /api/sessions/{id}/confirm
       body: { "confirm_id": "...", "approved": true }
       -> 204
```

### Le flux de réponse

`POST /messages` ne renvoie pas une réponse complète : il ouvre un flux
**SSE** (*Server-Sent Events*, une connexion HTTP que le serveur garde
ouverte pour pousser des messages). Chaque événement part tel quel :

```
data: {"type":"thought","text":"Je dois lire le fichier de config"}

data: {"type":"tool_call","id":"1","name":"search_codebase","arguments":{"query":"config"}}

data: {"type":"tool_return","id":"1","name":"search_codebase","ok":true,"content":"..."}

data: {"type":"token","text":"La config"}

data: {"type":"token","text":" se trouve dans"}

data: {"type":"done","reason":"final_answer"}
```

Le flux se ferme après `done`.

### La confirmation avant action risquée

C'est le seul endroit où le web a besoin de plus que le cœur ne fournit.

L'agent n'exécute aucun outil lui-même : il reçoit la passerelle d'outils
(`ToolGateway`, ADR-0006), et c'est elle qui demande confirmation. Elle
attend une fonction `confirm(request: ConfirmationRequest) -> bool` (type
`Confirmer` dans `execution/gateway.py`), fournie par l'interface qui la
construit. `ConfirmationRequest` porte l'outil, son niveau de risque, les
arguments et le délai accordé. La CLI lui donne une version qui pose la
question dans le terminal. **Le web doit lui en donner une qui :**

1. émet un événement `confirm_request` dans le flux SSE ouvert, avec un
   identifiant et le contenu de la `ConfirmationRequest` ;
2. attend que le navigateur réponde par `POST /confirm` ;
3. renvoie `True` ou `False` à la passerelle.

`confirm_request` n'existe pas dans `events.py` : c'est un événement propre
au transport HTTP, que le Lot D ajoute côté serveur. Il vaut mieux le garder
là que de faire dépendre le cœur d'un aller-retour réseau.

**Deux points à ne pas rater :**

- Pas de réponse au bout d'un délai raisonnable = **refus**, jamais
  acceptation. L'absence de confirmation n'est pas un oui. La passerelle
  impose déjà ce délai (`request.timeout_s`) : le web s'en sert pour
  l'afficher, et n'a pas besoin de compter lui-même.
- Si le client se déconnecte pendant l'attente, l'action est abandonnée.

## Ce que le web ne fait pas

Il n'exécute pas la boucle de raisonnement, ne décide pas quel outil appeler,
ne met pas en forme l'historique à sa façon. Tout ça vient de `sensai.core`.
S'il manque quelque chose, on complète `core/` — la CLI en profite aussi
(ADR-0005).

## Sécurité — à traiter dès la conception

Exposer cet agent sur le web, c'est exposer **l'exécution de code** sur le
web. Une page accessible sans authentification laisse n'importe qui lancer du
Python sur la machine hôte.

- L'API n'est pas ouverte sans authentification, même « juste pour la démo ».
- Les garde-fous du Lot B (sandbox, filtrage des secrets, confirmation
  humaine) deviennent la seule barrière : ils ne sont plus optionnels.
- Le pod Ollama distant d'ADR-0004 ne doit pas être joignable publiquement.

## Ce qui reste ouvert

- Faut-il un événement `usage` (tokens consommés, durée) pour
  l'observabilité, ou la trace passe-t-elle à côté du flux ?
- Comment l'interface reprend-elle un flux interrompu — on rejoue depuis le
  début du tour, ou on abandonne ?
- Qui crée la session : un appel explicite, ou le premier message ?
