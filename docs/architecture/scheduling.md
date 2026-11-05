# Planification de tâches — [X5]

`sensai-schedule` rejoue des tâches de l'agent à intervalle fixe, sans
surveillance. Décision et compromis : [ADR-0016](../decisions/0016-planification-des-taches.md).
Histoires utilisateur : [X5-scheduling.md](../user-stories/X5-scheduling.md).

La commande est installée avec le paquet (`pip install -e .`). Elle n'utilise
que la bibliothèque standard et l'agent existant : aucune dépendance ajoutée.

## Principe

1. On enregistre des tâches : un identifiant, un prompt, un intervalle.
2. `sensai-schedule run-due` joue **une fois** les tâches échues, puis s'arrête.
   C'est cron (ou un timer systemd) qui le lance régulièrement.
3. Chaque exécution laisse un compte rendu JSON.

Une tâche est échue si elle n'a jamais tourné, ou si l'intervalle est écoulé
depuis le **début** de sa dernière exécution. Il n'y a **pas de rattrapage** :
après trois jours d'arrêt, une tâche quotidienne tourne une fois, pas trois.

## Commandes

Options globales, à placer avant la commande : `--data-dir`, `--model`, `--host`
(par défaut `config.json`, puis `$SENSAI_HOME` / `~/.sensai` pour les données).

| Commande | Effet |
| --- | --- |
| `add ID --every 1d --prompt "…" [--tools a,b] [--timeout 600]` | Ajoute une tâche. `ID` : 1 à 40 caractères parmi `a-z`, `0-9`, `-`. Intervalle : `30m`, `1h`, `1d`, `7d` ou un nombre de secondes, **60 s au minimum**. `--tools` : liste des seuls outils proposés au modèle (noms vérifiés contre le registre) ; sans lui, tous. |
| `list` | Identifiant, intervalle, active ou non, dernière exécution, statut, prochaine échéance. |
| `remove ID` | Supprime la tâche **et** ses comptes rendus (`runs/ID/`). |
| `enable ID` / `disable ID` | Réactive / suspend une tâche sans la supprimer. |
| `run-due [--dry-run]` | Joue les tâches échues. `--dry-run` les liste sans rien lancer ni écrire. |
| `run ID` | Joue une tâche maintenant, échue ou non (le verrou reste respecté). |
| `history ID [-n 10]` | Derniers comptes rendus, du plus récent au plus ancien. |
| `loop [--every 300]` | Appelle `run-due` toutes les N secondes (minimum 60) jusqu'à Ctrl+C. Mode de secours sans cron ni systemd. |

Codes de sortie : `0` tout va bien (tâches `ok` ou ignorées), `1` une tâche a
échoué (`error`, `timeout`, `max_iterations`) ou une tâche demandée n'existe
pas, `2` mauvaise utilisation ou fichier des tâches inutilisable.

Le registre partagé (`src/sensai/registry.py`) propose `run_code`,
`read_file`, `write_file` et `web_search`. Sans surveillance, seuls la lecture
et la recherche web passent : `run_code` et `write_file` demandent une
confirmation, donc sont toujours refusés (ADR-0016). Les garde-fous EV2
masquent les secrets dans ce que renvoient les outils.

## Brancher cron

```cron
# Toutes les 15 minutes : joue ce qui est échu (l'intervalle de chaque tâche décide du reste).
*/15 * * * * SENSAI_HOME=/home/moi/.sensai /home/moi/sensai/.venv/bin/sensai-schedule run-due >> /home/moi/.sensai/schedule/cron.log 2>&1
```

- Utiliser le **chemin complet** de la commande : cron n'a pas le `PATH` d'un terminal.
- Cron ne lit pas votre profil : définir `SENSAI_HOME` dans la ligne (ou
  `data_dir` dans `config.json`) si les données ne sont pas dans `~/.sensai`.
- `config.json` et `prompts/` sont cherchés dans le dossier courant puis dans
  le dépôt ; le dossier courant de cron est `$HOME`.
- Les avertissements (verrou périmé repris, compte rendu illisible) sortent sur
  la sortie d'erreur, d'où la redirection.

## Brancher un timer systemd (utilisateur)

`~/.config/systemd/user/sensai-schedule.service`

```ini
[Unit]
Description=Tâches planifiées Sensai

[Service]
Type=oneshot
Environment=SENSAI_HOME=/home/moi/.sensai
ExecStart=/home/moi/sensai/.venv/bin/sensai-schedule run-due
```

`~/.config/systemd/user/sensai-schedule.timer`

```ini
[Unit]
Description=Lance les tâches Sensai échues toutes les 15 minutes

[Timer]
OnCalendar=*:0/15
Persistent=false

[Install]
WantedBy=timers.target
```

Puis `systemctl --user daemon-reload && systemctl --user enable --now sensai-schedule.timer`.
La sortie va dans `journalctl --user -u sensai-schedule.service`. Ces deux
exemples sont à adapter : la commande, elle, est testée dans `tests/scheduling/`.

## Où sont les fichiers

Sous `<données>/schedule/` (`~/.sensai/schedule/` par défaut), dossier créé en `700` s'il n'existait pas :

| Fichier | Contenu |
| --- | --- |
| `tasks.json` | Liste des tâches : `id`, `prompt`, `interval_s`, `enabled`, `created_at`, `last_run_at`, `last_status`, `timeout_s`, et `tools` si une liste a été donnée. Écriture atomique ; s'il est illisible ou mal formé, la commande s'arrête (code 2) en nommant le fichier, **sans le réécrire**. |
| `runs/<id>/<horodatage UTC>.json` | Un compte rendu par exécution. On garde les 50 derniers par tâche, les plus anciens sont supprimés. |
| `locks/<id>.lock` | Verrou présent pendant qu'une exécution tourne (`pid`, `started_at`). |

### Compte rendu d'exécution

```json
{
  "task_id": "resume",
  "started_at": "2026-10-14T08:00:00+00:00",
  "finished_at": "2026-10-14T08:00:12+00:00",
  "status": "ok",
  "answer": "texte de la réponse finale",
  "tool_calls": [{"name": "lire", "ok": true}, {"name": "ecrire", "ok": false, "error": "refused"}],
  "error": null
}
```

Statuts : `ok`, `error` (agent injoignable, plantage, erreur signalée),
`max_iterations` (6 appels au modèle sans réponse finale), `timeout`,
`skipped_locked` (une autre exécution de la même tâche était en cours).
`tool_calls` contient le **nom** et l'issue de chaque outil (`ok`, ou le code
d'erreur de la passerelle), jamais les arguments. La réponse du modèle, elle,
est enregistrée telle quelle.

## Politique sans surveillance

- Chaque exécution utilise une passerelle d'outils neuve avec le confirmeur
  `deny_all` : **un outil qui demande confirmation est toujours refusé**. Par
  défaut, c'est le cas de tout outil `write` ou `execute`. Aucune préférence ne
  peut l'assouplir pour ces deux niveaux.
- Les préférences viennent de la clé `tools` de `config.json` si elle existe
  (la CLI interactive la lit aussi). `confirm_after_untrusted` est
  forcé à `true` : après la réponse d'un outil de lecture ou de réseau, plus
  aucun outil autre que de lecture ne part.
- Le modèle est prévenu que personne ne peut confirmer et qu'il ne doit pas
  relancer un outil refusé.
- Aucun historique : chaque exécution part du prompt système et du prompt de la
  tâche, et rien n'est écrit dans `sessions.db`.

## Limites

- **Pas de tâche qui écrit ou exécute du code**, par construction.
- Une tâche peut encore envoyer une requête par un outil réseau tant qu'aucun
  outil n'a répondu dans l'exécution : donner à chaque tâche la liste
  `--tools` la plus courte possible. Voir l'ADR-0016.
- Le délai (`--timeout`, 600 s par défaut) n'est vérifié qu'**entre deux
  événements** de l'agent. Un appel au modèle qui ne répond pas ne peut pas être
  interrompu depuis la boucle : la commande attend. Les appels d'outils ont
  leur propre délai dans la passerelle (120 s par défaut).
- Un verrou plus vieux que **deux fois** le délai de la tâche est considéré
  comme laissé par un processus tué : il est supprimé (avec un avertissement) et
  l'exécution part. Deux passes qui reprennent le même verrou périmé au même
  instant peuvent se chevaucher.
- Pas d'expressions cron, pas de fuseau horaire : les dates stockées sont en UTC ;
  `list` affiche la prochaine échéance en heure locale.
- Modifier `tasks.json` pendant qu'une passe tourne peut perdre l'une des deux
  modifications (pas de transaction).
