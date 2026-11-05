# ADR-0030 — Mémoire structurée : des faits « entité, attribut, valeur » que l'agent tient lui-même

- **Statut** : Accepté (2026-11-01, validé par l'équipe)
- **Date** : 2026-10-17
- **Décideurs** : Ridwane (lot C)
- **Lot concerné** : C ; A impacté (`cli.py` : outils, prompt système, commande `/facts`) ; B impacté (deux outils passent par la passerelle)

## Contexte
[M3] External Structured Memory (issue #57, obligatoire depuis l'ADR-0008) :
la mémoire passe dans une vraie base ; l'agent lit, écrit et met à jour
lui-même des enregistrements structurés (faits, entités, relations) par des
opérations CRUD, sur la durée, exposées comme outils. User stories :
[M3-structured-memory.md](../user-stories/M3-structured-memory.md).

Ce qui existe déjà et ne suffit pas :
- M1 garde la conversation brute (purgée après 30 jours) et un profil que
  seul l'utilisateur remplit (`/remember`) ;
- M4 (`SENSAI.md`, ADR-0029) est un compte rendu en prose, fait pour être lu.

Aucun des deux ne retrouve un **fait précis** (« quelle version de Redis
utilise auth ? ») des semaines plus tard. Contraintes : toute écriture passe
par la passerelle (ADR-0006) ; la mémoire est relue par le modèle à chaque
session, ce qui en fait une cible d'injection durable (« empoisonnement de la
mémoire »).

**Répartition des rôles** : l'agent (le modèle) **décide** quoi retenir ou
chercher et le demande par tool calling ; la passerelle contrôle ; les
**outils exécutent** l'opération dans SQLite, avec des requêtes paramétrées.
Le modèle n'écrit jamais de SQL et ne touche jamais la base.

## Options envisagées

**1. Modèle de données**

| Option | Pour | Contre |
| --- | --- | --- |
| **Triplets entité, attribut, valeur dans une table SQLite** (retenu) | Format classique des mémoires de faits et des graphes de connaissances ; une seule table couvre faits et relations (une relation est un fait dont la valeur est une entité) ; recherche simple dans les deux sens | Pas de schéma imposé : le modèle peut nommer un même attribut de deux façons |
| Trois tables : entités, attributs, relations | Plus rigoureux | Plus de code et d'outils, plus d'erreurs du modèle |
| Notes en texte libre avec étiquettes | Très souple | Plus « structuré » : contredit le catalogue, et refait M4 |

**2. Outils et confirmation**

| Option | Pour | Contre |
| --- | --- | --- |
| **`save_fact` (risque `write`, confirmé) et `recall_facts` (risque `read`) ; suppression réservée à l'utilisateur** (retenu) | Le minimum pour les trois user stories ; chercher ne dérange jamais ; aucun fait n'entre en mémoire sans accord | Une confirmation par fait enregistré |
| `save_fact` déclaré `read` | Fluide | Une page web ou un fichier lu pourrait faire retenir un faux fait, resservi à chaque session |
| Quatre outils CRUD, suppression comprise | Le plus complet | Un agent qui efface ses souvenirs est difficile à contrôler ; `replace` couvre déjà la modification |

**3. Ce que l'agent sait au démarrage**

| Option | Pour | Contre |
| --- | --- | --- |
| **La liste des entités connues (50 au plus) dans le prompt système ; le détail par `recall_facts`** (retenu) | Léger quelle que soit la taille de la mémoire ; le modèle sait qu'il a quelque chose sur « auth » et pense à chercher | Un appel d'outil de plus |
| Tous les faits dans le prompt | Aucun appel d'outil | Ne passe pas à l'échelle : la mémoire grossit sans limite de durée |
| Faits liés à chaque question ajoutés automatiquement | Rien à faire pour le modèle | Deviner les faits liés est fragile et ajoute du bruit |

**4. Ce que l'utilisateur fait lui-même**

| Option | Pour | Contre |
| --- | --- | --- |
| **Commande `/facts` dans le chat** (retenu) | Sans quitter le chat, jamais vue par le modèle ; même logique que `/state`, `/profile` | Rien hors du chat |
| Commande séparée `sensai-facts` | Scriptable | Il faut quitter le chat ; c'est une mémoire de travail, pas un outil d'équipe |

## Décision
Les faits sont stockés dans `~/.sensai/memory.db` (SQLite, dossier `700`,
fichier `600`), rattachés au chemin du projet, sans purge automatique. Un
fait est un triplet (entité, attribut, valeur) ; les noms sont comparés sans
tenir compte de la casse ni des espaces en trop, et un même triplet n'existe
qu'une fois. Chaque création, modification et suppression est gardée dans
un historique (ancienne et nouvelle valeur, date).

Outils proposés à l'agent :
- `save_fact(entity, attribute, value, mode)`, risque `write` : `replace`
  remplace la ou les valeurs de l'attribut, `add` ajoute une valeur (pour les
  relations à plusieurs valeurs). La confirmation montre le fait, et
  l'ancienne valeur s'il y en a une. Champs vides ou trop longs refusés.
- `recall_facts(entity, attribute, value)`, risque `read`, au moins un critère :
  tout sur une entité, un attribut précis, ou les entités dont la valeur est
  donnée (relations inverses). Sans résultat, la réponse le dit.

Les descriptions des outils tiennent en une phrase et l'outil d'écriture
s'appelle `save_fact` : avec une description longue ou le nom `remember_fact`,
qwen3-coder écrivait ses appels en texte au lieu de les faire (4 appels
structurés sur 12 contre 8 sur 12, mesuré sur le pod le 2026-10-17). Le mode
d'emploi est dans le prompt système.

Le prompt système contient la liste des entités connues (les 50 plus
récemment modifiées), encadrée comme une donnée, relue à chaque message ; il
demande de ne retenir que les faits durables et importants. En tâche
planifiée (X5), `recall_facts` fonctionne et `save_fact` est refusé.

Dans le chat : `/facts` (entités), `/facts <entité>` (ses faits),
`/facts forget <entité> [attribut] [valeur]` (suppression ; demande
confirmation quand elle vise toute une entité), `/facts history <entité>`.

## Conséquences
- ✅ L'agent retrouve un fait précis des semaines plus tard, dans n'importe
  quelle session du projet, et le cite.
- ✅ Aucun fait n'entre en mémoire sans accord, et l'agent ne peut rien
  effacer : un faux fait injecté ne s'installe pas en silence.
- ✅ Le prompt reste léger : seuls les noms d'entités y sont.
- ❌ Une confirmation par fait enregistré : si l'agent retient trop de
  détails, c'est pénible. À mesurer pendant l'essai réel.
- ❌ Pas de schéma : `version_redis` et `redis_version` peuvent coexister.
  Montrer les attributs existants dans `recall_facts` limite le problème sans
  le supprimer.
- ❌ Pas de purge automatique : la mémoire garde des données personnelles
  (noms de personnes, choix internes) tant que l'utilisateur ne les efface
  pas (`/facts forget` ou suppression du fichier), à décrire dans le dossier
  légal.
- ❌ La liste d'entités dans le prompt peut contenir un nom injecté : elle est
  encadrée comme une donnée, ce qui limite le risque sans le supprimer (même
  limite que EV4-OUT-14).
- Suivi : tests (pas de doublon, `replace` et `add`, historique, mémoire par
  projet, relations inverses, refus) ; essai réel sur le pod (retenir un fait,
  le retrouver dans une nouvelle session, le corriger, l'oublier).
