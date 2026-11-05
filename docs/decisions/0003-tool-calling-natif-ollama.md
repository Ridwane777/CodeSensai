# ADR-0003 — Tool calling natif d'Ollama plutôt que parsing du texte ReAct

Date : 2026-09-22
Lot concerné : A (impacte B et C)
Statut : Accepté (2026-11-01, validé par l'équipe)

## Contexte
La boucle ReAct (`core/agent.py`) doit décider, à chaque tour, si le modèle
appelle un outil ou répond. Deux façons de récupérer cette décision :

1. demander au modèle d'écrire `Action: nom_outil(arguments)` en texte, et
   parser cette ligne nous-mêmes (ce que décrit `prompts/react_prompt.txt`) ;
2. passer la liste des outils dans le champ `tools` de `POST /api/chat` et
   lire le champ `message.tool_calls` de la réponse, déjà structuré par Ollama.

Le sujet interdit les frameworks LLM, pas les fonctionnalités de l'API Ollama
elle-même : les deux options restent du HTTP brut via `core/ollama_client.py`,
donc conformes à [ADR-0001](0001-pas-de-framework-llm.md).

## Options considérées

- **Parsing du texte** — un seul format à maîtriser, marche avec n'importe quel
  modèle. Mais avec un petit modèle local comme `qwen3:8b`, la sortie dérive :
  guillemets manquants, JSON d'arguments à moitié fermé, `Action:` en plein
  milieu d'une phrase, deux actions dans le même tour. Chaque cas se rattrape
  par une rustine dans le parseur, et ces rustines sont exactement le genre de
  code qu'on n'arrive plus à tester ni à expliquer au Keynote.
- **Champ `tools` natif** — Ollama renvoie `tool_calls` avec le nom de l'outil
  et ses arguments déjà désérialisés. Les schémas `parameters` de nos outils
  (`core/tools.py`) sont déjà au format JSON Schema attendu : rien à réécrire
  côté Lots B et C. Contrainte : le modèle choisi doit supporter le tool
  calling (`qwen3:8b` et `mistral` le supportent, tous les modèles non).

## Décision
L'agent envoie `registry.describe_all()` dans le champ `tools` de la requête
Ollama et lit les appels d'outils dans `message.tool_calls`. Le cycle
Thought/Action/Observation reste visible pour l'utilisateur — c'est
l'exigence de transparence du raisonnement — mais **la décision exécutée vient
du champ structuré, jamais du texte affiché**. Le parsing texte est conservé
uniquement comme repli si le modèle configuré ne renvoie pas de `tool_calls`.

## Conséquences
- Plus de parseur fragile à maintenir dans `core/agent.py` ; la boucle se
  résume à : appeler, lire `tool_calls`, `registry.call(...)`, réinjecter
  l'observation en message `role: "tool"`, reboucler jusqu'à `MAX_ITERATIONS`.
- Les Lots B et C ne changent rien : le contrat `Tool` est déjà le bon format.
- Le choix du modèle devient contraint (il doit supporter le tool calling).
  À documenter dans le README, et à vérifier au démarrage plutôt que de
  laisser l'agent échouer silencieusement en cours de session.
- Le streaming se complique : une réponse qui contient un appel d'outil ne se
  streame pas mot à mot comme une réponse finale. La boucle streame le texte
  des réponses finales, et affiche les actions comme des étapes.
