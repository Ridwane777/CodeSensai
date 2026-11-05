# ADR-0007 — Persistance des sessions et du profil : SQLite dans ~/.sensai, sessions par projet

Date : 2026-10-11
Lot concerné : C (impacte A et D)
Statut : Accepté (2026-11-01, validé par l'équipe)

## Contexte
La feature [M1] demande deux choses : retrouver l'historique d'une conversation
d'une session du CLI à l'autre, et un profil utilisateur (préférences,
instructions) injecté au démarrage. Definition of Done ClickUp : fermer et
rouvrir le CLI conserve l'historique et les préférences. Les besoins détaillés
sont dans [les user stories M1](../user-stories/M1-session-persistence.md).

Contraintes :
- **Le web lira les mêmes sessions.** Le contrat d'API du Lot A prévoit
  `GET /api/sessions` et `GET /api/sessions/{id}`, et le Lot D a une tâche
  « Rouvrir une conversation passée ». Le stockage doit donc être lisible
  depuis le code Python, par un autre processus que le CLI.
- **L'historique est sensible.** Il contient le code de l'utilisateur, ses
  questions, et potentiellement des secrets collés par erreur. Il ne doit pas
  pouvoir finir dans un dépôt Git.
- **Un développeur travaille sur plusieurs projets.** Reprendre « la dernière
  session » ne doit pas rouvrir la conversation d'un autre projet.
- Bibliothèque standard de préférence : le sujet cite `sqlite3` comme
  dépendance autorisée.

Pour trancher l'emplacement et le comportement au démarrage, on a regardé
comment Claude Code fait : sessions dans `~/.claude/projects/<projet>/`,
nouvelle session par défaut avec `--continue` pour reprendre, profil en
fichiers `CLAUDE.md` global et par projet.

## Options considérées

**Stockage des sessions**
- **SQLite** — retenu. Bibliothèque standard ; une sauvegarde est une
  transaction, donc un CLI tué en pleine écriture ne laisse pas de session à
  moitié écrite ; lecture par le serveur web pendant que le CLI tourne ; la
  liste des sessions est une requête. Perdu : la base ne se lit pas à l'œil
  sans outil (`sqlite3` en ligne de commande suffit).
- Un fichier JSON par session — lisible et simple à déboguer, mais écriture
  non atomique sans précaution, et lister les sessions oblige à ouvrir tous
  les fichiers.
- Un seul fichier JSON — le plus simple à coder, mais réécrit en entier à
  chaque message, et un fichier corrompu fait perdre toutes les sessions.
- JSONL en ajout seul, comme Claude Code — robuste aux interruptions, mais
  `History.drop_last()` retire un tour après une erreur : un fichier en ajout
  seul garderait ce tour, ou demanderait une logique d'annulation en plus.

**Emplacement des données**
- **`~/.sensai/`, sessions rattachées au projet** — retenu. Le projet est le
  dossier d'où l'on lance le CLI (chemin absolu). Hors de tout dépôt, donc
  jamais commitable, et les contextes de projets différents ne se mélangent
  pas. Perdu : une colonne et un filtre de plus.
- `~/.sensai/` sans notion de projet — plus simple, mais toutes les sessions
  de tous les projets dans une seule liste, et « reprendre la dernière » peut
  rouvrir le mauvais projet.
- Un dossier `.sensai/` dans le projet — séparé par projet sans rien coder,
  mais un `.gitignore` oublié suffit à commiter l'historique.

**Comportement au démarrage**
- **Reprendre la dernière session du projet** — retenu. Répond directement à
  la Definition of Done et à US-M1-1. `--new-session` repart de zéro,
  `--session <id>` reprend une session précise.
- Nouvelle session par défaut et `--continue` pour reprendre (choix de
  Claude Code) — évite qu'un contexte traîne d'un sujet à l'autre, mais la DoD
  ne se démontre qu'avec une option. Écarté pour coller à la DoD ; reste
  défendable si l'usage montre que la reprise automatique gêne.
- Nouvelle session seule, `--session <id>` pour reprendre — pas de raccourci
  vers la dernière session.

**Profil**
- **Un `profile.json` global, modifiable par commandes dans le CLI et à la
  main** — retenu. Champs `name`, `instructions`, `preferences` (liste).
  Commandes `/remember <texte>`, `/profile`, `/forget`. Démontrable en direct.
  Perdu : un seul profil pour tous les projets.
- Profil global + profil par projet (façon `CLAUDE.md`) — plus fidèle au
  besoin réel, mais deux niveaux à fusionner, tester et expliquer. Écarté pour
  le délai, c'est l'évolution naturelle.
- Markdown libre injecté tel quel — aucun schéma, mais pas d'ajout ou de
  retrait d'une préférence à l'unité.
- JSON édité seulement à la main — le moins de code, mais peu parlant en
  démonstration.

**Protection des fichiers sur la machine**
- **Dossier en `700`, fichiers en `600`, seulement si Sensai crée le
  dossier** — retenu. Les autres comptes de la machine ne lisent ni
  l'historique ni le profil. Un dossier existant n'est pas modifié : `--data-dir`
  peut pointer vers le dossier personnel de l'utilisateur, dont on ne doit pas
  changer les droits.
- Droits par défaut du système (umask, souvent `755`/`644`) — rien à coder,
  mais tout compte de la machine peut lire le code et les questions de
  l'utilisateur.
- Chiffrement de la base — protège aussi une copie du disque, mais impose une
  dépendance (SQLCipher) et une gestion de clé ; disproportionné pour un outil
  local.

**Suppression d'une session**
- **Pas de commande dans le CLI** — retenu. Les agents en ligne de commande de
  référence s'en passent : Claude Code et Codex CLI n'en proposent pas, à notre
  connaissance (sessions en fichiers supprimés à la main, purge automatique
  après un délai chez Claude Code). Gemini CLI a `/chat delete`, mais seulement
  pour les conversations sauvegardées explicitement. La suppression
  conversation par conversation est un usage d'interface web (ChatGPT, Claude).
  `SessionStore.delete()` existe dans le code : le Lot D peut l'exposer dans
  l'interface web sans autre changement.
- Une commande `/delete <id>` — utile pour effacer une conversation où un
  secret a été collé, mais redondant avec la suppression de `~/.sensai` pour un
  usage CLI, et une commande de plus à tester.

**Durée de conservation**
- **Purge au démarrage des sessions sans message depuis 30 jours,
  configurable** — retenu. Même défaut que Claude Code. La référence est
  `updated_at`, la date du dernier message échangé. `--retention-days` ou la
  clé `retention_days` de `config.json` changent la durée ; `0` désactive la
  purge. C'est la réponse aux secrets collés par erreur : ils ne restent pas
  indéfiniment sur le disque.
- Référence `created_at` — écartée : une conversation active commencée il y a
  31 jours serait supprimée en plein travail.
- Référence « dernière ouverture » — écartée : avec la reprise par défaut,
  chaque lancement ouvre la dernière session, qui ne serait donc jamais
  purgée ; et il faudrait écrire en base à chaque ouverture.
- Aucune purge — rien à coder, mais conservation illimitée de données
  potentiellement sensibles.
- Garder une trace des sessions supprimées pour expliquer leur absence —
  écartée : ce serait conserver une trace de ce qu'on a voulu effacer. Le
  message « session inconnue » mentionne la purge comme cause possible.

## Décision
- Sessions dans une base SQLite `~/.sensai/sessions.db` (dossier modifiable
  par `SENSAI_HOME` ou `--data-dir`), chaque session rattachée au chemin absolu
  du projet.
- Au démarrage, le CLI reprend la dernière session non vide du projet courant ;
  `--new-session` et `--session <id>` changent ce comportement.
- Profil dans `~/.sensai/profile.json`, modifiable par `/remember`,
  `/profile`, `/forget` ou à la main, ajouté au prompt système à chaque
  démarrage.
- **Le prompt système n'est pas sauvegardé avec la session** : il est
  reconstruit à chaque démarrage (fichier de prompt + profil). Sinon, corriger
  le prompt ou le profil n'aurait aucun effet sur les anciennes conversations.
- Une session n'est enregistrée qu'après une réponse complète du modèle : un
  tour en échec, retiré par `drop_last()`, n'atteint jamais la base.
- Quand une session est reprise, une consigne lue dans
  `prompts/memory_prompt.txt` (depuis A4 : version active du prompt `memory`,
  [ADR-0010](0010-versionnement-des-prompts.md)) est ajoutée au prompt système : l'historique est
  réel et le modèle doit s'en servir. Ajoutée après les essais réels, où
  `llama3` puis `qwen3-coder:30b` niaient avoir une mémoire
  ([docs/performance/M1-sessions.md](../performance/M1-sessions.md)).
- Le dossier de données est créé en `700`, `sessions.db` et `profile.json` en
  `600`. Un dossier qui existe déjà garde ses droits.
- Pas de suppression d'une session depuis le CLI ; `SessionStore.delete()`
  reste disponible pour l'interface web.
- Au démarrage, les sessions sans message depuis plus de 30 jours
  (`--retention-days`, `retention_days`, `0` = jamais) sont supprimées, avec
  un message ; la session demandée par `--session` est épargnée. Un `VACUUM`
  suit la purge pour que le texte supprimé ne reste pas dans le fichier.

## Conséquences
- ✅ La DoD de M1 est satisfaite sans option : fermer et rouvrir le CLI
  reprend la conversation et le profil.
- ✅ Le Lot D peut lister et rouvrir les sessions en appelant le même module
  (`knowledge/memory.py`), sans dépendre du CLI.
- ✅ Aucune dépendance ajoutée à `requirements.txt`.
- ✅ Le modèle de démonstration s'appuie sur l'historique repris (« Oui, tu
  avais un bug de login… ») grâce à la consigne de reprise.
- ✅ Base possible pour [M3] External Structured Memory, si l'équipe la retient
  un jour : la base SQLite existe déjà.
- ❌ L'historique est stocké **en clair** sur le disque de l'utilisateur. Un
  secret collé dans le chat y reste. Le filtrage des secrets relève des
  guardrails du Lot B ([EV2]) ; il faudra décider s'ils s'appliquent aussi
  avant la sauvegarde.
- ✅ Les autres comptes de la machine ne peuvent pas lire l'historique ni le
  profil.
- ❌ Un dossier `~/.sensai` créé avant ce changement, ou choisi par
  l'utilisateur, garde ses droits d'origine : `chmod 700 ~/.sensai` à faire
  à la main.
- ❌ Pour effacer une seule conversation depuis le CLI, il faut passer par
  `sqlite3` ; seul l'effacement complet (supprimer `~/.sensai`) est simple.
- ✅ Conservation limitée : les données inactives disparaissent d'elles-mêmes.
- ❌ Une conversation qu'on comptait reprendre après plus de 30 jours est
  perdue ; le message au démarrage et l'option `0` limitent la surprise, sans
  l'éviter.
- ❌ Une session purgée ou un identifiant mal tapé donnent le même message :
  le CLI ne peut pas dire laquelle des deux causes s'applique.
- ❌ Un projet déplacé ou ouvert depuis un autre chemin apparaît comme un
  autre projet : ses anciennes sessions ne sont plus reprises
  automatiquement (elles restent accessibles par `--session <id>`).
- ❌ Un seul profil pour tous les projets ; le profil par projet est l'étape
  suivante.
