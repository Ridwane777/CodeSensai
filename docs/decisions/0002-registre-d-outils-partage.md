# ADR-0002 — Un registre d'outils partagé plutôt que des appels directs

Date : 2026-09-21
Lot concerné : A (impacte B et C)
Statut : accepté

## Contexte
Trois features (sandbox, RAG, outil MCP externe) doivent toutes être
appelables par l'agent. Développées par 3 personnes différentes en
parallèle, sur des sous-systèmes très différents (exécution de code,
recherche sémantique, appel réseau externe).

## Options considérées
- L'agent importe et appelle directement `execution.sandbox` et
  `knowledge.rag` — écarté : couple fortement le Lot A aux détails
  d'implémentation des Lots B et C ; impossible de tester la boucle ReAct
  avant que sandbox et RAG soient terminés.
- Un contrat `Tool` commun (name/description/parameters/run) + un
  `ToolRegistry` central — retenu.

## Décision
Chaque capacité exposée à l'agent implémente le protocole `Tool`
(`core/tools.py`) et s'enregistre dans un `ToolRegistry`. L'agent
n'interagit qu'avec le registre, jamais avec une implémentation concrète.

## Conséquences
- Les 3 lots peuvent développer et tester leur module en isolation dès le
  départ (le Lot A teste sa boucle contre `EchoTool` en attendant sandbox
  et RAG).
- L'intégration devient : enregistrer son outil dans le registre — pas une
  réécriture de l'agent à chaque nouvelle feature.
- Léger surcoût initial (écrire le protocole, le wrapper par outil) —
  rentabilisé dès que 2 outils ou plus existent.
