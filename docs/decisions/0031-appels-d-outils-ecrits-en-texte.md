# ADR-0031 — Appels d'outils écrits en texte : les lire seulement quand la réponse n'est que ça

- **Statut** : Accepté (2026-11-01, validé par l'équipe)
- **Date** : 2026-10-17
- **Décideurs** : Ridwane (lot C), à valider par Fresnel (lot A, `core/agent.py`)
- **Lot concerné** : A (`core/agent.py`) ; complète l'[ADR-0003](0003-tool-calling-natif-ollama.md) sans le remplacer

## Contexte
L'ADR-0003 fait passer les appels d'outils par le champ structuré
`tool_calls` d'Ollama : « jamais du texte affiché ». Lors des essais réels
de M3 (pod RunPod, `qwen3-coder:30b`, Ollama 0.40.6, 2026-10-17), le modèle
écrit souvent son appel dans le texte au format qui lui est propre
(`<function=…><parameter=…>…</parameter></function>`), sans la balise
`<tool_call>` d'ouverture : Ollama ne le reconnaît pas, rien n'est exécuté.

Mesures (appels structurés, 8 outils proposés, même prompt système) :
- `read_file`, `run_code`, `web_search`, `search_codebase`, `recall_facts`,
  `update_state` : 5 ou 6 sur 6 une fois les descriptions raccourcies ;
- `save_fact` (« retiens que… ») : 1 sur 6, et 4 sur 12 sous le nom
  `remember_fact`. Avec un seul outil proposé : 8 sur 8. Ce n'est pas notre
  prompt : sans lui, le taux est le même.

Pire que l'échec : avant tout correctif, le modèle affirmait ensuite avoir
fait l'action (« la version a été passée de 7 à 8 ») alors que rien n'avait
été exécuté.

## Options envisagées

| Option | Pour | Contre |
| --- | --- | --- |
| Ne jamais lire le texte ; relancer le modèle, puis s'arrêter sur une erreur claire | Stricte application de l'ADR-0003 | Mesuré : 2 enregistrements sur 5 dans le CLI ; M3 inutilisable en démo pour retenir un fait |
| **Lire les appels au format natif de qwen3-coder, seulement quand la réponse n'est que ça, puis les faire passer par le chemin normal** (retenu) | C'est la syntaxe d'appel du modèle lui-même, pas du texte libre à interpréter ; l'appel passe ensuite par la passerelle, les garde-fous et la confirmation comme un appel structuré | Dépend du format d'un modèle : un autre modèle aura le sien ; une réponse injectée qui ne serait qu'un appel serait lue |
| Changer de modèle | Peut-être plus fiable | Contredit l'ADR-0004 à deux semaines du rendu, sans garantie |
| Parser des formats de type ReAct (`Action: …`) | Marche avec tout modèle | Précisément ce que l'ADR-0003 a écarté : texte libre, ambigu |

## Décision
Dans `core/agent.py`, quand le modèle répond sans appel structuré :
1. si la réponse **n'est composée que** d'appels au format
   `<function=nom><parameter=clé>valeur</parameter>…</function>` (avec ou sans
   `<tool_call>`), et que chaque `nom` est un outil **proposé** au modèle,
   ces appels sont lus et suivent le chemin normal : passerelle, permissions,
   garde-fous, **confirmation** pour l'écriture et l'exécution. Les valeurs
   sont converties selon le schéma de l'outil (entier, nombre, booléen),
   sinon laissées en texte. Un `Thought` le signale ;
2. si la réponse mêle du texte et un appel, contient un appel mal formé ou
   vise un outil non proposé, **rien n'est exécuté** : la même demande est
   reposée au modèle, sans sa réponse ratée (la lui renvoyer l'incite à la
   recopier), deux fois au plus, puis le tour s'arrête sur une `Error`.

## Conséquences
- ✅ Les appels que le modèle a voulus mais qu'Ollama n'a pas reconnus sont
  faits, sans exception à la passerelle ni à la confirmation.
- ✅ Le modèle ne peut plus affirmer une action qui n'a pas eu lieu : soit
  l'appel est fait, soit le tour s'arrête sur une erreur visible.
- ❌ Écart à la lettre de l'ADR-0003 : une réponse composée uniquement d'un
  appel écrit en texte est exécutée. Une injection qui ferait répondre au
  modèle *seulement* un appel serait lue ; elle passerait quand même par la
  confirmation pour toute écriture ou exécution, pas pour une lecture.
- ❌ Lié au format de qwen3-coder : un autre modèle demandera son propre
  lecteur, ou rien (le champ structuré reste la voie normale).
- ❌ Une relance coûte un appel au modèle de plus (quelques secondes).
- Suivi : tests de `core/agent.py` (appel seul lu, confirmation et refus
  appliqués, types du schéma, plusieurs appels, outil non proposé refusé,
  appel mêlé à du texte jamais exécuté) ; mesure dans le CLI réel
  ([essai M3](../performance/M3-facts.md)). À revoir si une version d'Ollama
  reconnaît ces appels.
