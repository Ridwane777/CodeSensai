# ADR-0006 — Une passerelle impose permissions, validation et confirmation à tous les outils

Date : 2026-10-07
Lot concerné : B (impacte A, C, D)
Statut : accepté — validé par le lot A (2026-10-11) : la boucle ReAct appelle les outils via la passerelle

## Contexte
[ADR-0002](0002-registre-d-outils-partage.md) donne un contrat commun
(`Tool`) et un registre. Il ne dit rien de ce qui doit se passer *autour* de
l'appel : qui a le droit d'appeler quoi, qui valide les arguments et le
résultat, quand on demande à l'utilisateur. Sans règle commune, chaque outil
(sandbox, RAG, MCP, fichiers, recherche web) réinventerait ces contrôles — ou
les oublierait. Et ADR-0005 rappelle qu'exposer l'agent sur le web, c'est
exposer l'exécution de code : ces contrôles sont la seule barrière.

## Options considérées
- **Chaque outil fait ses propres contrôles** — écarté : A3 et EV2 devraient
  être branchés N fois, et le N+1ᵉ outil les oublierait sans que rien ne le
  signale.
- **Étendre `ToolRegistry.call` dans `core/tools.py`** — écarté pour l'instant :
  fichier du lot A, dont toute modification touche les quatre lots. Peut
  devenir l'étape suivante si le lot A l'accepte.
- **Une `ToolGateway` qui enveloppe le registre** (`execution/gateway.py`) —
  retenu : le registre et le protocole `Tool` ne changent pas, un outil
  existant continue de fonctionner.

## Décision
1. L'agent appelle `ToolGateway.call(name, **kwargs)` (même signature que
   `ToolRegistry.call`), jamais le registre directement.
2. Chaque outil déclare un `risk` (`read`, `network`, `write`, `execute`). Un
   outil qui ne le déclare pas est traité comme `execute`.
3. Le mode (`allow` / `ask` / `deny`) découle du risque ; les préférences
   utilisateur peuvent toujours **durcir**, mais n'**assouplissent** que
   `read` et `network`. `write` et `execute` demandent toujours confirmation.
4. Les arguments et le résultat sont validés ; les garde-fous d'EV2 se
   branchent sur deux points (entrée, sortie) ; la confirmation d'A3 est
   fournie par l'interface (ADR-0005, point 3).
5. Tout échec d'un garde-fou, d'un filtre ou d'une confirmation **bloque**
   plutôt que de laisser passer. Les appels d'outil et les confirmations ont
   un délai imposé par la passerelle ; les échecs d'outil sont classés
   (`timeout`, `network_error`, `tool_error`) pour que le modèle sache s'il
   peut réessayer.
6. Les décisions de la passerelle reviennent au modèle comme un `ToolResult`
   (`ok=False`, `data["error"]` = code stable), pour que l'agent s'adapte à un
   refus au lieu de planter.

## Conséquences
- Ajouter un outil = déclarer son risque et rendre un `ToolResult` (voir
  `docs/architecture/tool-contract.md`). Les contrôles lui sont appliqués sans qu'il les
  écrive.
- A3, EV2 et la confirmation web n'ont qu'un point d'accroche chacun.
- **Rien n'empêche encore l'agent d'appeler `registry.call` directement.** Tant
  que la boucle ReAct (lot A) n'utilise pas la passerelle, la protection n'est
  pas effective : c'est à brancher avec le lot A, et un test devra garantir
  que l'agent ne détient pas le registre brut.
- Un délai dépassé n'arrête pas l'outil (un thread ne se tue pas). Les outils
  qui modifient l'état doivent borner leur propre durée.
- Le plancher sur `write`/`execute` rend un outil « toujours autorisé » impossible
  sans modifier le code : voulu, mais à assumer si on veut une démo fluide.
- Les outils externes (MCP) doivent déclarer un risque à l'enregistrement ; un
  serveur MCP inconnu sera donc traité en `execute`.
