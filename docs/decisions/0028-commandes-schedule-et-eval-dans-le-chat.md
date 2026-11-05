# ADR-0028 — `/schedule` et `/eval` dans le chat : on réutilise les commandes existantes

- **Statut** : Accepté (2026-11-01, validé par l'équipe)
- **Date** : 2026-10-14
- **Décideurs** : Méric (Lot B) ; en attente de relecture de l'équipe
- **Lot concerné** : B (`chat_commands.py`) ; A (`cli.py` appelle le module)

## Contexte
X5 (planification) et EV1 (évaluation) n'existent que comme commandes
séparées (`sensai-schedule`, `sensai-eval`). C'est leur forme naturelle
(cron appelle `sensai-schedule run-due`, une évaluation est un script), mais un
évaluateur qui ouvre le chat ne les voit pas : ils ne se démontrent pas
« dans l'agent ». Il faut les rendre atteignables depuis la conversation sans
dupliquer leur logique.

## Options envisagées
| Option | Pour | Contre |
| --- | --- | --- |
| **`/schedule …` et `/eval …` : la ligne est découpée puis passée au `main` de chaque commande** | Aucune logique dupliquée, mêmes options et mêmes codes de sortie, ~100 lignes | La sortie va à l'écran, pas dans la conversation ; une commande longue fige le chat |
| Réimplémenter des sous-commandes propres au chat | Sortie maîtrisée, pas de dépendance à argparse | Deux implémentations à garder alignées (X5 et EV1 sont déjà testées) |
| Les exposer comme **outils** du modèle | Le modèle pourrait planifier lui-même | Le modèle créerait des tâches qui tournent sans surveillance : une injection de prompt deviendrait une action persistante. Contraire à ADR-0006 et ADR-0016 |
| Ne rien faire | Aucun risque | X5 et EV1 invisibles dans une démo du chat |

## Décision
Deux commandes `/schedule` et `/eval`, tapées par l'utilisateur, déléguées aux
`main` existants. La session leur fournit le dossier de données, l'hôte et le
modèle (le modèle de la session sert de juge), sauf si l'utilisateur donne
lui-même l'option. Ce ne sont **pas** des outils : seul le clavier les déclenche
(le texte du modèle n'est jamais interprété comme une commande). `/schedule
loop` est refusé, car il ne rend jamais la main. Une ligne de commande n'est
envoyée ni au modèle ni à l'historique. Une erreur (guillemet non fermé, option
inconnue, panne) s'affiche et le chat continue.

## Conséquences
- ✅ X5 et EV1 se démontrent depuis le chat, avec le comportement testé des
  commandes d'origine ; rien à garder aligné.
- ✅ Le modèle ne peut pas planifier ni évaluer de lui-même.
- ❌ La sortie de ces commandes n'entre pas dans la conversation : le modèle ne
  « sait » pas qu'une tâche a été planifiée, et l'historique ne la garde pas.
- ❌ `/schedule run`, `/schedule run-due` et `/eval run` bloquent le chat
  jusqu'à la fin (un jugement complet peut durer plusieurs minutes), sans
  barre de progression ni annulation propre autre que Ctrl+C.
- ❌ Les messages d'usage d'argparse restent ceux des commandes d'origine, pas
  adaptés au chat (ils parlent de `sensai-schedule`).
- ❌ Une tâche créée depuis le chat tourne ensuite sans surveillance ; elle
  garde la politique de X5 (écriture et exécution refusées, ADR-0016), mais son
  texte n'est pas relu par le filtre d'entrée (ADR-0027) : il est tapé par
  l'utilisateur.
- Suivi : revoir si l'interface web (Lot D) doit offrir les mêmes commandes
  (elle aurait besoin d'une sortie capturée, pas imprimée) ; EV4 reste une suite
  `pytest` : un jeu de tests d'attaque n'a pas de sens dans une conversation.
