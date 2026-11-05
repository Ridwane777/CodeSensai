# ADR-0037 — Multi-Agent Orchestration : délégation via un outil (`delegate_task`)

- **Statut** : Remplacé en partie par [ADR-0038](0038-agents-specialises-et-relais.md) (rôles, relais, profondeur 1, échéance du sous-agent)
- **Date** : 2026-10-24
- **Décideurs** : Fresnel (Lot A)
- **Lot concerné** : A (`core/`, `tools/`)

## Contexte

[A2] Multi-Agent Orchestration demande que l'agent puisse décomposer une
tâche complexe en sous-tâches et les confier à des sous-agents, plutôt que
de tout faire dans un seul tour de raisonnement linéaire.

Contraintes du dépôt : aucun framework multi-agent, tout passe par l'API
HTTP d'Ollama (comme le reste du projet) ; les sous-agents doivent respecter
les mêmes garde-fous et confirmations que l'agent principal (A3, EV2,
ADR-0006) — un sous-agent n'est pas un moyen de contourner la passerelle.

## Options envisagées

| Option | Pour | Contre |
| --- | --- | --- |
| Nouvel « orchestrateur » qui pilote plusieurs boucles ReAct depuis l'extérieur (nouveau point d'entrée, nouvelle CLI) | Séparation nette entre mode simple et mode multi-agent | Deuxième chemin à maintenir en parallèle de `cli.py` ; l'utilisateur doit savoir lequel choisir avant de commencer ; les garde-fous devraient être rebranchés à la main. |
| Délégation comme un **outil** (`delegate_task`) proposé à l'agent existant | Rien de nouveau côté interface : l'agent décide lui-même, pendant une conversation normale, quand déléguer. Réutilise `run_agent_turn` (ADR déjà en place) et la MÊME passerelle (ADR-0006) : permissions, garde-fous et confirmations s'appliquent à l'identique aux outils que le sous-agent appelle. | Le sous-agent peut, via le même outil, déléguer à son tour : il faut une borne de profondeur explicite pour éviter une récursion sans fin. |
| Sous-agents en parallèle (threads/async) pour plusieurs sous-tâches à la fois | Plus rapide sur des sous-tâches indépendantes | La confirmation A3 est interactive (terminal) : deux sous-agents qui demandent une confirmation en même temps ne peuvent pas être démêlés proprement côté CLI. Complexité à garder pour une itération plus tard si le besoin est mesuré. |

## Décision

La délégation est un outil, `delegate_task(task, persona?)`, enregistré
dans le même registre que les autres outils (`tools/delegate_tool.py`). Il
fait tourner un sous-agent **séquentiellement** via `run_agent_turn`
(`core/agent.py`), avec :
- un historique isolé (le sous-agent ne voit pas la conversation en cours —
  la sous-tâche doit se comprendre seule) ;
- la **même passerelle** (`ToolGateway`) que l'agent principal : les mêmes
  permissions, les mêmes garde-fous d'entrée/sortie, et la même confirmation
  avant une action risquée (EV2, A3) ;
- une profondeur de délégation bornée (`MAX_DELEGATION_DEPTH = 2`, suivie par
  une `contextvars.ContextVar`) : un sous-agent peut lui-même déléguer, mais
  pas indéfiniment.

Risque déclaré `execute` (le pire cas) : ce n'est pas l'outil lui-même qui
est dangereux, mais il ouvre la porte à n'importe quel outil que le
sous-agent choisira d'appeler, donc il ne doit jamais être assoupli par une
préférence utilisateur permissive (`tool_policy.LOOSENABLE` l'exclut déjà
pour `execute`).

Branché uniquement dans le chat CLI (`cli.py`), après la construction de la
passerelle — pas dans `registry.py` (partagé avec le planificateur X5),
parce que l'outil a besoin d'une référence vers sa propre passerelle, que
`build_registry()` ne construit pas.

## Conséquences

- ✅ Aucune nouvelle dépendance, aucun nouveau point d'entrée : le modèle
  décide lui-même, dans une conversation normale, quand décomposer une
  tâche.
- ✅ Les sous-agents héritent de tous les garde-fous existants (A3, EV2) sans
  code dupliqué : ils passent par la même passerelle.
- ❌ Exécution strictement séquentielle : déléguer trois sous-tâches
  indépendantes ne va pas plus vite qu'une boucle ReAct qui les ferait l'une
  après l'autre elle-même — seul le découpage du raisonnement change, pas la
  latence. Le parallélisme est explicitement écarté ci-dessus, pas oublié.
- ❌ Non branché dans `sensai-schedule` (X5) ni dans l'interface web (Lot D,
  `src/sensai/web/runtime.py`) : ces deux entrées construisent aussi une
  passerelle, mais `delegate_task` n'y est pas enregistré. À faire si le
  besoin se confirme, sans réécrire cet ADR.
- Suivi : si des sous-tâches réellement indépendantes et lentes deviennent
  courantes (mesuré, pas supposé), réévaluer l'exécution en parallèle à ce
  moment-là.
