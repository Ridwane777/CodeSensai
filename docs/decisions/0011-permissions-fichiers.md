# ADR-0011 — Accès fichiers : une couche de permissions par chemin, refus par défaut

- **Statut** : Accepté (2026-11-01, validé par l'équipe)
- **Date** : 2026-10-13
- **Décideurs** : Méric (Lot B) ; en attente de relecture de l'équipe
- **Lot concerné** : B (outils `read_file` / `write_file`) ; A (l'agent les expose) ; D (l'interface web affichera la confirmation)

## Contexte
[T4] demande des opérations sur le système de fichiers **et** une couche de
permissions qui dit quels fichiers l'agent peut lire ou toucher, vérifiée
**avant** toute opération. La passerelle d'outils (ADR-0006) décide si un
outil *peut* tourner, pas quels chemins il touche : cette partie revient à
l'outil fichiers. Un chemin est un texte écrit par le modèle, donc potentiellement
influencé par un contenu hostile (injection de prompt dans un fichier lu).

## Options envisagées
| Option | Pour | Contre |
| --- | --- | --- |
| A. Couche de permissions partagée, chemin **résolu** (`..` et liens symboliques suivis) puis comparé aux dossiers autorisés | Bloque `../../etc/passwd` et les liens sortants ; un seul endroit à tester | Vérification faite avant l'ouverture, pas sur le descripteur ouvert |
| B. Filtrer le texte du chemin (refuser `..`) | Trivial | Contournable (lien symbolique, chemin absolu) : fausse sécurité |
| C. Lancer les opérations fichiers dans la sandbox Docker (ADR-0012) | Isolation réelle | Il faudrait monter le projet dans le conteneur ; lent ; hors sujet pour de simples lectures |
| D. Confirmer chaque lecture | Maximum de contrôle | Inutilisable : l'agent lit des dizaines de fichiers |

## Décision
Option A. Racine = dossier du projet pour la lecture et l'écriture, extensible
par la section `files` de la config (dossiers de lecture et d'écriture
séparés). Une liste de noms protégés (`.env`, `.git`, `.ssh`, `*.pem`, clés…)
est refusée même à l'intérieur de la racine ; la config peut l'allonger, jamais
la raccourcir. `read_file` (risque `read`) s'exécute sans demander ;
`write_file` (risque `write`) demande toujours (A3), montre le chemin exact et
un diff, et **refuse d'écraser** sans `overwrite=true`. Écriture atomique
(fichier temporaire puis renommage).

## Conséquences
- ✅ Sortie du projet impossible par `..`, chemin absolu ou lien symbolique (testé).
- ✅ Les secrets ne sont ni lisibles ni modifiables, donc ne passent pas dans le contexte du modèle.
- ✅ L'utilisateur voit un diff avant d'approuver un remplacement.
- ❌ Fenêtre TOCTOU : un lien symbolique créé entre la vérification et l'ouverture n'est pas détecté. Acceptable pour un agent mono-utilisateur ; à revoir si l'outil tourne sur une machine partagée (ouvrir avec `O_NOFOLLOW`/`openat`).
- ❌ Un noyau de noms protégés est une liste : un secret nommé autrement (`config.prod.yml`) est lisible. Les filtres EV2 masquent ensuite les identifiants dans le contenu, ce qui limite la fuite sans la supprimer.
- ❌ `read_file` ne demande pas confirmation : un fichier du projet contenant une injection est lu sans que l'utilisateur le voie. Atténué par le balisage « donnée non fiable » et `confirm_after_untrusted` (écritures ensuite confirmées).
- ❌ Pas de binaire, UTF-8 seulement, 1 Mo maximum : une limite de l'outil, pas de la couche.
- Suivi : tests `tests/execution/test_file_permissions.py` et `tests/tools/test_file_tools.py` ; à revoir si l'outil sert à plusieurs utilisateurs.
