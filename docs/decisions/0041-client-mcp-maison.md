# ADR-0041 — MCP (T1) : un client stdio écrit à la main, serveurs déclarés dans config.json

- **Statut** : Accepté (2026-10-24)
- **Date** : 2026-10-24
- **Décideurs** : Ridwane (lot C) et Valentino (lot D)
- **Lot concerné** : D (`tools/mcp_tool.py`) ; branché dans le CLI, le serveur web et `config.py`

## Contexte

[T1] MCP demande que l'agent appelle les outils d'un serveur MCP externe. Le
fichier `tools/mcp_tool.py` n'était qu'un squelette (« À FAIRE ») branché
nulle part ; l'essai complet du 2026-10-24 l'a relevé. `docs/dependances.md`
notait « bibliothèque MCP : pas encore choisie ».

Contraintes : pas de framework, la même passerelle pour tous les outils
(ADR-0006 : un outil externe sans risque déclaré est traité en `execute`), et
les user stories T1 : outils enregistrés au démarrage sans toucher au code du
lot A ; un serveur en panne ne bloque pas l'agent.

## Options envisagées

| Option | Pour | Contre |
| --- | --- | --- |
| SDK officiel `mcp` (Python) | Toutes les fonctions du protocole (stdio, HTTP, ressources, prompts) ; suivi par les auteurs | Asynchrone (anyio) dans un code synchrone ; une dizaine de dépendances (httpx, pydantic, starlette, sse…) pour quatre messages |
| **Client stdio écrit à la main** (JSON-RPC 2.0, une ligne par message : `initialize`, `notifications/initialized`, `tools/list`, `tools/call`) | Aucune dépendance ; environ 200 lignes lisibles ; testable avec un faux serveur | Transport stdio seulement (pas de serveur MCP distant en HTTP) ; outils seulement (ni ressources ni prompts) ; à faire évoluer avec le protocole |
| Un seul outil générique `mcp_call(tool, arguments)` (le squelette) | Un seul outil à enregistrer | Le modèle ne voit ni les outils disponibles ni leurs paramètres : il devine les noms |

## Décision

Client stdio écrit à la main (`tools/mcp_tool.py`). Les serveurs se
déclarent dans `config.json` :

```json
"mcp_servers": {
  "time": {"command": "uvx", "args": ["mcp-server-time"], "risk": "read", "timeout_s": 30}
}
```

Au démarrage (CLI et serveur web), chaque serveur est lancé ; chacun de ses
outils devient un outil de l'agent, `mcp_<serveur>_<outil>`, avec la
description et le schéma de paramètres donnés par le serveur. Le risque vaut
`execute` par défaut (réglable par serveur) ; la confirmation montre le
serveur, l'outil et les arguments ; la réponse passe par les garde-fous de la
passerelle. Une configuration invalide arrête le démarrage ; un serveur
introuvable, muet, illisible ou qui plante donne un avertissement (ou une
erreur d'outil pendant la session), jamais une exception.

## Conséquences

- ✅ T1 fonctionne : essai réel sur le pod, le modèle appelle l'outil MCP de
  lui-même, avec confirmation, et la clé renvoyée par le serveur est masquée.
- ✅ Aucune nouvelle dépendance ; un nouveau serveur se branche par
  `config.json` seul.
- ✅ Les pannes sont testées : serveur introuvable, muet, réponse illisible,
  plantage pendant un appel.
- ❌ Transport stdio seulement : un serveur MCP distant (HTTP) n'est pas
  joignable. Passer au SDK officiel si ce besoin apparaît.
- ❌ Outils seulement : les ressources et prompts MCP sont ignorés.
- ❌ Un serveur MCP est du code tiers lancé sur la machine, avec les droits de
  l'utilisateur et sans sandbox : n'ajouter que des serveurs de confiance
  (risque L8, `docs/legal/`).
- ❌ Pas encore essayé avec un serveur publié : dans cette session, l'exécution
  d'un paquet téléchargé (`uvx mcp-server-time`) a été bloquée par les
  permissions de l'outil de développement. Essai réel fait avec le serveur de
  test du dépôt.
- Suivi : essayer un serveur publié (`mcp-server-time`,
  `@modelcontextprotocol/server-filesystem`) ; afficher les outils MCP dans
  l'interface web (story `T1-tool-calling-mcp.md`).
