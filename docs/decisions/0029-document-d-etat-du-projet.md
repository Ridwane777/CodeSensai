# ADR-0029 — Document d'état du projet : `SENSAI.md`, mis à jour section par section

- **Statut** : Accepté (2026-11-01, validé par l'équipe)
- **Date** : 2026-10-17
- **Décideurs** : Ridwane (lot C)
- **Lot concerné** : C ; A impacté (`cli.py` : prompt système, commande `/state`) ; B impacté (un nouvel outil passe par la passerelle)

## Contexte
[M4] Artifact & State Document (issue #39, obligatoire depuis l'ADR-0008) :
l'agent tient à jour un document vivant, distinct de l'historique brut (M1),
et doit pouvoir **modifier une section précise sans réécrire tout le
document**, avec un format d'édition que notre code sait analyser. DoD :
après plusieurs échanges, le document reflète l'état du projet sans avoir été
corrompu ni réécrit en entier. User stories :
[M4-state-document.md](../user-stories/M4-state-document.md).

Contraintes :
- toute écriture passe par la passerelle (ADR-0006), et l'écriture demande
  toujours une confirmation qu'aucun réglage ne peut retirer (A3) ;
- le contexte du modèle est partagé entre l'historique, les passages du RAG,
  les résultats des outils et leur description. Fenêtre configurée sur le pod
  de validation : **32 768 tokens** (`OLLAMA_CONTEXT_LENGTH=32768`, réglage du
  pod, hors dépôt) ;
- les outils comparables rangent ce type de mémoire dans un fichier Markdown
  du projet : `CLAUDE.md` (Claude Code), dossier `memory-bank/` (Cline),
  `CONVENTIONS.md` (Aider). *Constat de mémoire, non revérifié le
  2026-10-17.*

## Options envisagées

**1. Où ranger le document, et sous quelle forme**

| Option | Pour | Contre |
| --- | --- | --- |
| **Un fichier `SENSAI.md` à la racine du projet, sections `##`** (retenu) | Lisible et modifiable à la main ; versionné et partagé avec le projet par Git ; sections faciles à découper | Un fichier de plus dans le projet de l'utilisateur (il peut l'ignorer dans `.gitignore`) |
| Plusieurs fichiers `.sensai/*.md`, un par section | Impossible d'abîmer une section en modifiant une autre | Plus lourd à lire et à charger |
| Dans `~/.sensai`, hors du projet | Ne touche pas au projet | Invisible et non partagé : contredit US-M4-1 |

**2. Format d'édition**

| Option | Pour | Contre |
| --- | --- | --- |
| **Outil `update_state(section, action, content)`, `action` = `replace` ou `append`** (retenu) | Arguments JSON validés par la passerelle ; le code ne touche qu'à la section visée, les autres restent identiques à l'octet près ; le modèle ne recopie jamais le document | Un outil de plus |
| Patch au format `diff` écrit par le modèle | Très général | Les modèles se trompent souvent de lignes et de contexte : patch refusé ou appliqué au mauvais endroit |
| Réécriture complète avec `write_file` | Rien à coder | Exclu par la DoD : le modèle peut oublier ou reformuler ce que l'utilisateur a écrit |

**3. Confirmation**

| Option | Pour | Contre |
| --- | --- | --- |
| **Risque `write` : confirmation à chaque mise à jour, avec la section avant et après** (retenu) | Honnête et cohérent avec A3 et l'ADR-0006, sans exception à justifier ; la confirmation montre le diff | Une confirmation par mise à jour ; jamais de mise à jour en tâche planifiée (X5 refuse l'écriture) |
| Déclarer `read` pour éviter la confirmation | Aucune interruption | Mensonge à la passerelle : une injection de prompt ferait écrire l'agent sans que l'utilisateur le voie |
| Nouveau niveau de risque « écriture limitée » | Pas d'interruption, honnête | Change la politique du lot B et l'ADR-0006 pour une seule feature |

**4. Ce que l'agent sait au démarrage**

| Option | Pour | Contre |
| --- | --- | --- |
| **Contenu ajouté au prompt système, rafraîchi après chaque mise à jour, 8 000 caractères au plus** (retenu) | Connu dès le premier message (US-M4-1), même mécanisme que le profil de M1 | Occupe du contexte à chaque tour (environ 2 000 tokens au plus, ~6 % de 32 768) |
| Lecture à la demande par un outil | Ne coûte rien tant qu'il ne sert pas | Contredit US-M4-1 ; le modèle oublie d'aller le lire |

**5. Trace et annulation**

| Option | Pour | Contre |
| --- | --- | --- |
| **Journal local `~/.sensai/state/<projet>.jsonl` et commande `/state`, `/state history`, `/state undo <section>`** (retenu) | Couvre US-M4-3 sans fichier en plus dans le projet ; annulation par section, sans Git | Journal non partagé avec l'équipe |
| Seulement Git | Rien à coder | Suppose un dépôt Git et un commit après chaque modification ; pas d'annulation par section |
| Journal dans le projet | Partagé | Un fichier qui grossit dans le projet et qui garde des versions supprimées volontairement |

## Décision
Le document d'état est `SENSAI.md`, à la racine du dossier d'où l'on lance
`sensai`, en Markdown, découpé par ses titres `##`. À la première mise à
jour, s'il n'existe pas, il est créé avec quatre sections : `Fait`,
`En cours`, `Décisions`, `Problèmes connus`. L'utilisateur peut en ajouter à
la main ; l'agent ne peut pas en créer.

L'agent le modifie avec l'outil `update_state(section, action, content)`,
risque `write` :
- `replace` remplace le contenu d'une section, `append` y ajoute du texte à
  la fin ;
- une section inconnue est refusée (avec la liste des sections existantes),
  un `content` qui contient une ligne de titre (`#` en début de ligne) aussi ;
- la confirmation affiche la section avant et après ;
- l'écriture est atomique (fichier temporaire puis renommage).

Le contenu de `SENSAI.md` est ajouté au prompt système, encadré comme une
donnée sur le projet et non comme une instruction, tronqué à 8 000
caractères, et rafraîchi après chaque mise à jour. Le prompt demande une mise
à jour à la fin d'une tâche, pas à chaque message. `SENSAI.md` n'est pas
indexé par le RAG.

Chaque mise à jour est journalisée dans `~/.sensai/state/<projet>.jsonl`
(date, section, action, ancien et nouveau contenu, résumé), purgé comme les
sessions (30 jours). Dans le chat : `/state`, `/state history`,
`/state undo <section>`. L'annulation est réservée à l'utilisateur, elle est
elle-même journalisée, et elle est refusée si la section a été modifiée à la
main depuis la dernière mise à jour de l'agent. Comme Ctrl+Z, chaque
annulation remonte d'une modification de plus dans le journal : deux
`/state undo` de suite annulent les deux dernières modifications de la
section, elles ne s'annulent pas l'une l'autre. (Première version : la seconde
annulation annulait la première ; changé après l'essai réel du 2026-10-17,
où ce comportement s'est montré déroutant.)

## Conséquences
- ✅ Un humain lit et corrige le document sans outil ; l'équipe le partage
  par Git avec le code.
- ✅ Les sections que l'agent ne vise pas ne changent jamais : la DoD de M4
  (« ni corrompu ni réécrit en entier ») est garantie par le code, pas par la
  bonne volonté du modèle.
- ✅ Aucune exception à la passerelle : l'outil suit les mêmes règles que
  `write_file`.
- ❌ Une confirmation à chaque mise à jour : si le modèle met à jour trop
  souvent, c'est pénible. À mesurer pendant l'essai réel.
- ❌ En tâche planifiée (X5), le document n'est jamais mis à jour.
- ❌ Le document coûte jusqu'à environ 2 000 tokens de contexte à chaque tour.
- ❌ Le journal d'annulation est local : un coéquipier ne peut pas annuler une
  modification faite sur une autre machine (il passe par Git).
- ❌ Le contenu de `SENSAI.md` peut venir de n'importe qui dans le dépôt :
  l'encadrer comme une donnée limite le risque d'injection sans le supprimer
  (même limite que EV4-OUT-14 pour les résultats d'outils).
- Suivi : tests (sections intactes à l'octet près, refus, écriture atomique,
  annulation, troncature) ; essai réel sur le pod (plusieurs échanges, puis
  « où en est-on ? » dans une nouvelle session).
