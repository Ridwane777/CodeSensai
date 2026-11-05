# ADR-0016 — Planification : `sensai-schedule run-due` appelé par cron, sans démon ni dépendance

- **Statut** : Accepté (2026-11-01, validé par l'équipe)
- **Date** : 2026-10-14
- **Décideurs** : Méric (Lot B) ; à valider par l'équipe
- **Lot concerné** : B (passerelle d'outils, politique sans surveillance) ; A (boucle d'agent réutilisée telle quelle)

## Contexte
La feature X5 demande de rejouer des tâches de l'agent à intervalle fixe
(issue #55). Personne n'est devant l'écran à ce moment-là, et c'est ce qui
change tout : la passerelle d'outils (ADR-0006) protège les actions risquées
par une **confirmation de l'utilisateur** (A3), or ici il n'y a personne pour
répondre. Il faut aussi qu'une tâche en échec ne bloque pas les autres, qu'une
même tâche ne tourne pas deux fois en même temps, et que l'on puisse relire ce
qui s'est passé. Contraintes : pas de nouvelle dépendance, projet utilisé sur
des machines d'étudiants (Linux, parfois WSL ou macOS).

## Options envisagées
### Planificateur
| Option | Pour | Contre |
| --- | --- | --- |
| APScheduler (bibliothèque) | Cron, intervalles, persistance, très répandu | Nouvelle dépendance majeure (à documenter, à tenir à jour), un processus qui doit rester vivant, beaucoup de fonctions inutiles ici |
| cron / systemd seuls, sans commande dédiée | Rien à écrire | Il faudrait écrire à la main une commande par tâche ; aucune garantie de non-recouvrement, de compte rendu ni de politique sans surveillance |
| Démon : un thread de planification dans `sensai` | Pas de configuration système | Les tâches ne tournent que tant que la session interactive est ouverte ; un thread qui appelle l'agent et la passerelle en parallèle de la conversation partage son état (ex. « contenu non fiable lu ») |
| **Commande `run-due` (une passe puis fin) appelée par cron/systemd, stdlib seule** — retenue | Le système d'exploitation sait déjà relancer, journaliser et survivre au redémarrage ; testable avec une horloge injectée ; zéro dépendance | L'utilisateur doit écrire une ligne de crontab ou un timer ; `loop` n'est qu'un mode de secours |

### Stockage des tâches
| Option | Pour | Contre |
| --- | --- | --- |
| **Un fichier JSON** — retenue | Lisible et corrigeable à la main, quelques tâches par utilisateur, écriture atomique (fichier temporaire puis `os.replace`) | Pas de transaction : deux processus qui écrivent en même temps peuvent perdre une modification |
| SQLite (comme les sessions, ADR-0007) | Transactions, accès concurrent | Disproportionné pour une dizaine de lignes ; moins lisible ; un fichier abîmé est plus difficile à réparer à la main |

## Décision
Les tâches (prompt + intervalle en secondes, 60 s minimum) sont enregistrées
dans `<données>/schedule/tasks.json`. La commande `sensai-schedule run-due`
joue les tâches échues une fois puis s'arrête ; cron ou un timer systemd la
déclenche. Elle s'appuie sur la bibliothèque standard uniquement.

**Politique sans surveillance.** Chaque exécution reçoit une `ToolGateway`
neuve dont le confirmeur est `deny_all`, passé explicitement. Conséquences :
- un outil dont le mode est « demander » (`write` et `execute` par défaut) est
  **toujours refusé** ; le modèle reçoit le refus comme une observation ;
- les préférences ne peuvent pas assouplir `write` ni `execute`
  (`tool_policy.LOOSENABLE`), donc une ligne `allow` dans `config.json` ne
  change rien ici non plus ;
- `confirm_after_untrusted` est forcé : après la lecture d'un contenu
  extérieur, plus aucun outil autre que de lecture ne part ;
- une liste `--tools` par tâche retire les autres outils de ce que voit le modèle ;
- le prompt système est précédé d'une note : exécution sans surveillance, ne
  pas relancer un outil refusé, dire ce qui n'a pas pu être fait.

**Isolation.** Chaque tâche est dans son propre `try/except` : un plantage
donne le statut `error` et la tâche suivante part. Un fichier verrou
(`O_CREAT|O_EXCL`) empêche deux exécutions simultanées ; un verrou de plus de
deux fois le délai de la tâche est jugé abandonné et repris. Le délai
(600 s par défaut) est vérifié entre deux événements de l'agent, et le nombre
d'étapes est borné par `MAX_ITERATIONS`.

**Intervalles seulement, pas d'expressions cron**, et pas de rattrapage des
exécutions manquées : une tâche échue tourne une fois, pas dix.

## Risque d'injection de prompt
Un contenu lu pendant une tâche (page web, fichier) peut contenir des
instructions destinées au modèle. Ce que la décision **limite** : il ne peut
ni écrire ni exécuter (refus), et dès qu'un outil de lecture ou de réseau a
répondu, `confirm_after_untrusted` transforme tout appel suivant d'un outil
qui n'est pas en lecture seule (donc aussi `network`) en demande de
confirmation, que `deny_all` refuse. Ce qu'elle **ne règle pas** : les outils
`network` restent autorisés sans surveillance tant qu'aucun outil n'a encore
répondu dans l'exécution, et un outil de lecture reste toujours appelable.
Un premier appel réseau peut donc partir avec ce que le modèle avait déjà en
tête (le prompt de la tâche, le prompt système), et une requête de recherche
est une URL qui sort chez le moteur : des données pourraient fuir par ce
canal. Atténuations : la liste `--tools` (ne donner à une tâche que ce dont
elle a besoin), `deny_all`, `confirm_after_untrusted`, et les garde-fous EV2 —
ils restent à brancher, car ni la CLI interactive ni le planificateur n'en
passent à la passerelle dans `main` aujourd'hui. On ne prétend pas que
l'injection est impossible.

## Conséquences
- ✅ Zéro dépendance ajoutée ; aucun processus à surveiller ; tout est testable sans Ollama ni vraie horloge.
- ✅ Une garantie simple à expliquer : sans surveillance, rien qui écrive ou exécute n'a lieu.
- ✅ Un compte rendu par exécution (50 gardés par tâche), sans les arguments des outils.
- ❌ **Aucune tâche d'écriture ni d'exécution n'est possible** (ex. « corrige les fautes de ce fichier chaque nuit ») : c'est le prix de la sécurité ; il faudrait un mode de confirmation différée (file d'attente d'actions à approuver) dans un nouvel ADR.
- ❌ Pas de rattrapage : si la machine est éteinte, les exécutions manquées sont perdues.
- ❌ Pas d'expressions cron (« chaque lundi à 9 h ») : seulement « toutes les N minutes/heures/jours » ; une expression se traduit à la rigueur par la planification de cron lui-même.
- ❌ L'utilisateur doit installer lui-même la ligne cron ou le timer systemd (exemples dans [scheduling.md](../architecture/scheduling.md)).
- ❌ Le fichier JSON n'est pas transactionnel : l'écriture est atomique, mais deux processus qui modifient les tâches en même temps (ex. `add` pendant qu'une passe termine) peuvent perdre une modification. Le planificateur relit le fichier avant chaque mise à jour pour réduire la fenêtre, sans la supprimer.
- ❌ Le délai ne peut pas interrompre un appel bloquant (modèle qui ne répond pas, outil bloqué) : il n'est vérifié qu'entre deux événements. Aucun arrêt forcé n'est promis ; les appels d'outils ont leur propre délai dans la passerelle, et le verrou périmé finit par libérer la tâche.
- ❌ La reprise d'un verrou périmé est fondée sur le temps : deux passes qui reprennent le même verrou au même instant peuvent se chevaucher.
- Suivi : tests dans `tests/scheduling/`. À revoir si les tâches deviennent nombreuses ou partagées entre utilisateurs (passer à SQLite), si l'on veut des horaires précis (expressions cron, ou APScheduler) ou si un mode de confirmation différée est demandé.
