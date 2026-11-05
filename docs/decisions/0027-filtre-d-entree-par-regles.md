# ADR-0027 — Filtre d'entrée EV2 : des règles déterministes, appliquées avant tout le reste

- **Statut** : Accepté (2026-11-01, validé par l'équipe)
- **Date** : 2026-10-14
- **Décideurs** : Méric (Lot B) ; en attente de relecture de l'équipe
- **Lot concerné** : B (`execution/guardrails.py`) ; A (`cli.py` appelle le filtre) ; D (l'interface web devra l'appeler aussi)

## Contexte
[EV2] demande deux intercepteurs : en sortie (masquer secrets et données
personnelles, fait) et **en entrée** (« détecter et bloquer les prompts non
sûrs ou hors périmètre avant qu'ils n'atteignent le modèle », selon des règles
configurables). Seul le second manquait : `filter_input` levait
`NotImplementedError`. Il faut décider *comment* juger un prompt et *où*
appeler le filtre. Contraintes : le projet tourne en local, sans service tiers
(ADR-0001, ADR-0004) ; le filtre s'exécute à chaque message, donc doit être
rapide ; et il doit être testable sans modèle.

## Options envisagées
| Option | Pour | Contre |
| --- | --- | --- |
| **Règles déterministes (regex) en français et en anglais** | Instantané, aucune dépendance, testable ligne à ligne, explique son refus (nom de la règle), configurable par un simple fichier | Contournable par reformulation, autre langue ou encodage ; faux positifs sur des questions de sécurité légitimes |
| Classifieur LLM local (le modèle juge le prompt) | Comprend les reformulations | Un appel de plus par message (latence, VRAM sur le 8B de dev), non déterministe, lui-même manipulable par le prompt qu'il juge, impossible à tester sans modèle |
| API de modération hébergée (ex. OpenAI Moderation) | Modèle entraîné pour cela | Envoie chaque prompt, donc le code de l'utilisateur, à un tiers : contredit le choix « tout reste local » (voir `docs/legal/`) ; clé d'API et quota en plus |

## Décision
`filter_input(text, rules) -> (autorisé, texte_ou_raison)` applique des règles
regex déterministes. Elles ne portent que sur des couples verbe + objet sans
ambiguïté : écraser les consignes, révéler le prompt système, personas de
contournement connues, création de logiciel malveillant, vol d'identifiants.

1. **Refus** : le message n'atteint ni le modèle, ni la recherche RAG, ni le
   profil, ni la session sauvegardée. La raison nomme la règle et ne répète pas
   le prompt.
2. **Secrets collés** : une clé d'API dans le prompt n'est pas refusée mais
   **masquée** avant le modèle, la session et le profil (même masquage que les
   outils). Les e-mails et numéros de carte tapés par l'utilisateur ne sont pas
   masqués en entrée : il les a écrits volontairement.
3. **Texte nettoyé, pas normalisé** : caractères invisibles et séquences ANSI
   retirés (une instruction cachée dans un texte collé), mais pas de NFKC sur le
   texte renvoyé, pour ne pas réécrire le code de l'utilisateur. Les règles, elles,
   sont évaluées sur le texte normalisé, ce qui déjoue les lettres pleine largeur
   et les caractères de largeur nulle.
4. **Appelé en premier dans la boucle de `cli.py`**, avant les commandes
   (`/remember` écrit dans le profil).
5. **Échec fermé** : un filtre qui plante bloque, comme la passerelle
   (ADR-0006).
6. **Configurable, mais seulement en ajoutant** : la clé `input_blocklist` de
   `config.json` ajoute des règles (c'est ainsi que se configure le « hors
   périmètre », ex. un projet qui ne doit pas parler de salaires). Les règles
   par défaut ne peuvent pas être désactivées par la config, même principe que
   les modes de permission. Une règle invalide arrête le démarrage.

## Conséquences
- ✅ Les attaques évidentes sont arrêtées sans appel au modèle, avec un refus
  expliqué ; un secret collé dans le chat ne finit plus dans `sessions.db`.
- ✅ Chaque règle a un test ; `tests/test_cli_input_filter.py` échoue si
  l'appel est retiré de `cli.py`.
- ❌ **Contournable.** Une reformulation, une autre langue, du base64 ou une
  attaque étalée sur plusieurs messages passent. Ce filtre retire les cas
  évidents, il ne remplace pas le modèle ni la confirmation avant action
  (ADR-0006), qui restent la vraie barrière.
- ❌ **Faux positifs connus.** Une question légitime qui cite une phrase
  d'attaque (« comment empêcher “ignore previous instructions” ? ») est
  refusée ; le message invite à reformuler. Un cours sur les malwares aussi,
  sauf mention de détection/analyse. Le texte du prompt n'est pas montré à
  l'utilisateur dans le refus, mais la règle l'est.
- ❌ **Couverture partielle.** Le filtre n'est branché que sur la CLI. Les
  prompts des tâches planifiées (X5) sont écrits par l'utilisateur à la
  création de la tâche et ne sont pas filtrés ; l'interface web (Lot D) devra
  appeler `filter_input` elle aussi, sinon elle contourne la protection.
- ❌ Les règles sont écrites à la main pour deux langues : en ajouter une
  demande du travail.
- Suivi : ajouter ces attaques au corpus EV4 pour mesurer ce que le filtre
  retient vraiment ; **revoir cette décision** si des faux positifs gênent
  l'usage normal, ou si un classifieur local mesuré tient sous ~200 ms par
  prompt sur la machine de démonstration.
