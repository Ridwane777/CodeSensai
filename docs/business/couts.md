# Coûts de CodeSensei

Ce document sépare ce qui est **mesuré** de ce qui est **estimé**. Chaque
estimation donne sa méthode et ses hypothèses, pour qu'on puisse la corriger
avec un vrai chiffre (facture, relevé d'heures). Rédigé le 2026-10-25.

## 1. Mesuré

| Élément | Valeur | Source |
| --- | --- | --- |
| Durée du projet | 2026-09-22 → 2026-10-24 (33 jours calendaires) | `git log` |
| Équipe | 4 personnes | `git shortlog` |
| Activité | 291 commits, 42 PR fusionnées | `git log`, GitHub |
| Licences de logiciels et de modèles | **0 €** : Ollama (MIT), `qwen3-coder:30b` et `qwen3:8b` (Apache-2.0), bibliothèques MIT / Apache-2.0 | [licences.md](../legal/licences.md) |
| Services tiers payants | **0 €** : aucune clé d'API ; recherche web sans API ([ADR-0040](../decisions/0040-recherche-web-duckduckgo-et-repli-bing.md)) | code, `docs/dependances.md` |
| Durées de fonctionnement | chargement du modèle à froid : 47 à 80 s ; un tour d'agent : 4 à 90 s selon la tâche | [essai du 2026-10-24](../performance/essais/essai-2026-10-24.md) |

**Non mesuré** : la dépense réelle en GPU. Elle figure sur la facture RunPod
de l'équipe, qui n'est pas dans le dépôt : à reporter ici pour remplacer
l'estimation 2.1.

## 2. Estimé

### 2.1 GPU pendant le développement (RunPod)

- **Tarif** : RunPod facture à la seconde, pod démarré. Grille publique
  consultée le 2026-10-25 pour un GPU de 24 Go en Community Cloud : RTX 3090
  ou RTX A5000 ≈ 0,22 $/h, RTX 4090 ≈ 0,44 $/h ; en Secure Cloud, environ le
  double (RTX 4090 ≈ 0,69 $/h). Source :
  [runpod.io/gpu-cloud/pricing](https://www.runpod.io/gpu-cloud/pricing).
- **Heures** (hypothèse) : des pods allumés surtout pendant les essais, soit
  environ 2 à 4 h par jour d'essai, sur 10 à 15 jours d'essais, soit **20 à
  60 heures**. À remplacer par le total de la facture.
- **Estimation** : 20 h × 0,22 $ ≈ **4 $** au plus bas ; 60 h × 0,69 $ ≈
  **41 $** au plus haut. Ordre de grandeur : **quelques dizaines de dollars**
  pour tout le projet. Le stockage du pod (modèles ≈ 20 Go) s'y ajoute
  pendant qu'il existe.

### 2.2 Temps de développement

- **Méthode** : 4 personnes, 33 jours calendaires, en parallèle d'autres
  cours. Hypothèse : 2 à 4 h par personne et par jour ouvré (24 jours ouvrés).
- **Estimation** : 4 × 24 × 2 à 4 h = **190 à 380 heures-personnes**.
- **Valorisation** (à titre indicatif, pour le business plan) : au coût d'un
  développeur junior en France, 35 à 45 € de l'heure chargés (hypothèse), soit
  **6 700 à 17 100 €**. C'est le premier poste de coût, et de loin.

### 2.3 Coût d'exploitation pour un utilisateur

CodeSensei est conçu pour tourner **en local**, pour un seul développeur.

| Configuration | Coût direct | Hypothèses |
| --- | --- | --- |
| Poste avec un GPU de 24 Go (modèle 30B) | 0 € de service ; l'électricité | matériel déjà possédé |
| Poste modeste + `qwen3:8b` | 0 € de service | modèle plus petit : une fonctionnalité validée dessus peut se comporter autrement qu'avec le 30B (ADR-0004) ; pas de mesure comparative dans le dépôt |
| GPU loué à l'heure (RunPod, Community) | ≈ 0,22 à 0,44 $/h d'utilisation | pod arrêté hors usage ; 2 h par jour ouvré ≈ 9 à 18 $/mois |

### 2.4 Ce qui coûterait si on changeait de choix

| Changement | Coût supplémentaire | Quand il se justifie |
| --- | --- | --- |
| API de recherche web (Brave Search API) | abonnement et quota (tarif à vérifier au moment du choix) | dès un usage hors projet pédagogique (rétrospective, point 5) |
| Essai de bout en bout hebdomadaire sur le pod | ≈ 1 h de GPU par semaine, soit 0,22 à 0,69 $ | toujours (rétrospective, point 2) |

## 3. Comment corriger ce document

1. Remplacer l'hypothèse d'heures de 2.1 par le total de la facture RunPod.
2. Remplacer 2.2 par un relevé d'heures si l'équipe en a tenu un.
3. Revoir les tarifs de 2.1 et 2.4 à la date de la mise à jour (ils changent).
