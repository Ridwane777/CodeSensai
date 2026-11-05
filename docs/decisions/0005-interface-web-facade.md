# ADR-0005 — L'interface web est une façade, pas un second agent

Date : 2026-09-25
Lot concerné : D (impacte A et B)
Statut : Accepté (2026-11-01, validé par l'équipe)

## Contexte
L'équipe passe de trois à quatre : Valentino rejoint le projet, spécialisé
web et interfaces. Deux conséquences d'organisation, actées dans le README :

- l'interface web (`[X1]`) quitte le Lot C, qui gardait le RAG *et* la
  mémoire de session *et* le frontend ;
- l'outil MCP (`[T1]`) quitte le Lot A, où il était rangé sans être commencé.

Reste la question de fond : qu'est-ce que l'interface web a le droit de faire ?
La réponse par défaut — « elle refait ce dont elle a besoin » — produit deux
agents qui divergent, et une démo où la CLI et le navigateur ne donnent pas
la même réponse à la même question.

## Options considérées
- **Un backend web autonome** qui réimplémente la boucle d'agent pour être
  libre de ses choix (streaming, format des messages, gestion d'erreurs).
  Écarté : la logique de raisonnement existerait à deux endroits, et chaque
  correction du Lot A devrait être répercutée à la main.
- **Une façade** : le web expose par HTTP ce que la CLI expose en terminal,
  au-dessus du même `sensai.core`. Retenu.

## Décision
1. **Le web appelle `sensai.core`, il ne le duplique pas.** Toute logique de
   raisonnement, d'appel d'outil ou d'historique reste dans `core/`. Si le
   web a besoin d'un comportement que `core/` ne sait pas faire, on modifie
   `core/` — la CLI en profite aussi.
2. **Le format d'échange entre l'interface et le cœur est figé avant le
   développement**, au même titre que le protocole `Tool` l'a été pour les
   outils (ADR-0002). Tant qu'il n'est pas écrit, le Lot D ne peut pas
   avancer en parallèle. C'est la première tâche de Valentino, avec le Lot A.
3. **La façon de poser une question à l'utilisateur devient fournie par
   l'interface.** `execution/human_in_loop.confirm()` ne doit pas appeler
   `input()` : la CLI fournit sa version console, le web fournit un bouton.
   Sans ça, la confirmation avant action risquée (`[A3]`) est inutilisable
   depuis un navigateur.
4. **La trace des tours d'agent (`observability/`) appartient au même lot que
   l'interface.** C'est la même donnée, produite puis affichée.

## Conséquences
- Valentino peut développer contre un faux backend dès que le point 2 est
  écrit, sans attendre que la boucle ReAct soit terminée.
- Le point 3 est un changement dans un fichier du Lot B : à annoncer à Méric,
  ce n'est pas une correction mais une contrainte nouvelle qui vient de
  l'arrivée d'une seconde interface.
- **Exposer l'agent sur le web, c'est exposer l'exécution de code sur le
  web.** Une page accessible sans authentification laisse n'importe qui
  lancer du Python sur la machine hôte. Le sandbox (`[T2]`), les guardrails
  (`[EV2]`) et la confirmation humaine (`[A3]`) cessent d'être du confort :
  ils deviennent la seule barrière. À traiter à la conception de l'API, pas
  après.
- Même remarque pour le pod Ollama distant d'[ADR-0004](0004-modele-et-infrastructure.md) :
  une instance ouverte sur Internet est une API de génération ouverte à tous.
  Fermer cet accès fait partie du périmètre du Lot D.
- FastAPI (ou équivalent) est autorisé : c'est un framework web, pas un
  framework LLM — [ADR-0001](0001-pas-de-framework-llm.md) n'est pas en cause.
