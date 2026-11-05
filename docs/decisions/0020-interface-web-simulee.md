# ADR-0020 — Interface web développée sur un moteur simulé, derrière un contrat remplaçable

- **Statut** : Accepté (2026-11-01, validé par l'équipe) ; remplacé en partie par [ADR-0035](0035-serveur-web-reel.md) (serveur réel)
- **Date** : 2026-10-13
- **Décideurs** : Valentino (Lot D)
- **Lot concerné** : D (impacte A pour le contrat d'événements, et tous les lots pour la démo)

## Contexte
Pour la démo de mi-parcours, il faut montrer le parcours utilisateur
complet de CodeSensei. Or le backend web n'existe pas : `src/sensai/web/` et
`src/sensai/observability/` sont vides, la boucle ReAct (A1) n'a que son contrat,
et le sandbox, les garde-fous, la confirmation et l'outil MCP sont des
squelettes. Attendre le backend bloquerait toute la conception de l'interface.

[ADR-0005](0005-interface-web-facade.md) impose déjà que l'interface soit une
façade au-dessus de `sensai.core` et que le format d'échange soit figé avant le
développement. Reste à choisir comment avancer sans backend.

## Options envisagées
| Option | Pour | Contre |
| --- | --- | --- |
| Pages statiques avec réponses codées en dur | Très rapide | Jetable, aucune réactivité crédible (interruption, confirmation, formulaire), à refaire entièrement. |
| Faux backend FastAPI qui rejoue des scénarios | Plus proche du réel, teste le réseau | Deux chantiers pour une démo ; un serveur de plus qui peut tomber le jour de la démo. |
| **Interface React branchée sur une interface `Engine`, avec un `MockEngine` dans le navigateur** | Une seule interface pour la mi-parcours et le rendu final ; le vrai backend remplace seulement l'adaptateur ; démo sans réseau ni serveur ; le contrat d'événements est écrit et testé tout de suite | Le contrat est une proposition tant que le Lot A ne l'a pas validé ; la démo ne prouve pas l'intégration réelle. |

## Décision
On développe l'interface dans `frontend/` (React, Vite, TypeScript, Tailwind)
contre une interface `Engine` et un flux d'événements typés
(`frontend/src/contract/`). Un `MockEngine` joue des scénarios scriptés mais
réactifs. Un `HttpEngine` (squelette, non branché) porte le futur flux SSE vers
FastAPI. Tout écran affiche un badge « Moteur simulé ».

## Conséquences
- ✅ La conception et la démo de l'interface avancent sans attendre A, B et C.
- ✅ Le contrat interface ⇄ moteur est écrit, typé et testé (`frontend/tests/`) : il sert de base de discussion avec le Lot A.
- ✅ Démo sans réseau : pas de panne possible côté serveur le jour de la démo.
- ❌ **La démo ne prouve pas que le vrai moteur sait produire ces événements** : l'intégration reste à faire et peut révéler des écarts (formats, latences, ordre des événements).
- ❌ Le contrat est proposé par le Lot D seul : s'il diverge de ce que le Lot A peut émettre, il faudra le réviser (nouvel ADR si la décision change).
- ❌ Risque de perception : une démo scénarisée peut être prise pour un vrai agent. Atténuation : badge permanent, page [simule-vs-reel.md](../architecture/web/simule-vs-reel.md), et présentation orale explicite.
- ❌ Le routage par mots-clés ne comprend pas le langage libre : toute formulation hors scénario reçoit une réponse de repli.
- Suivi : valider le contrat avec le Lot A ; lister les écarts dans `simule-vs-reel.md` à chaque écran branché au vrai moteur. **Seuil de révision** : si au rendu final le moteur réel émet des événements différents, remplacer ce contrat par un nouvel ADR.
