# A2 — Orchestration multi-agent : essais réels

Essais faits le 2026-10-24 sur le pod RunPod (GPU, Ollama), modèle
`qwen3-coder:30b`, depuis un poste Linux (client Python 3.12). Décisions :
[ADR-0037](../decisions/0037-delegation-sous-agent-outil.md) et
[ADR-0038](../decisions/0038-agents-specialises-et-relais.md). Stories :
[A2](../user-stories/A2-multi-agent-orchestration.md).

Tous les chiffres ci-dessous sont **mesurés** (aucune estimation). Les
échantillons sont petits (2 à 12 essais par cas) : ils montrent une tendance,
pas un taux fiable au pourcent près.

## Scripts pour reproduire

| Script | Ce qu'il mesure |
| --- | --- |
| `scripts/bench_a2.py <hôte> roles\|equipe\|critique\|choix\|detail [n]` | rôles, chaîne de l'équipe, relecteur, choix de l'agent principal. Travaille dans un dossier temporaire. |
| `scripts/bench_a2_delegation.py <hôte> redelegation\|escient\|tardive` | redélégation, délégation à bon escient (`EXTRA` ajoute une règle au prompt, `KINDS` filtre), confirmation tardive. Lit ce dépôt. |
| `scripts/bench_a2_echeance.py <hôte> durees\|fantome` | durée d'une délégation, sous-agent qui continue après l'abandon |
| `scripts/bench_a2_prompt.py <hôte>` | le sous-agent avec ou sans le prompt du projet |

`<hôte>` est l'adresse du serveur Ollama (jamais écrite dans le dépôt).

## 1. Délégation (`delegate_task`) : défauts trouvés et corrigés

| Essai | Avant (code de l'ADR-0037) | Après (ADR-0038) |
| --- | --- | --- |
| Durée d'une délégation simple (5 tâches) | 6,4 à 36,7 s | 6,2 à 29,9 s (inchangé, normal) |
| Sous-agent après l'abandon par la passerelle (échéance 8 s) | continue jusqu'à 28,2 s, 797 morceaux de réponse perdus | arrêté à 8,0 s ; 0 appel d'outil et 0 thread après |
| Confirmation après l'abandon (échéance 10 s) | `write_file` demandé à 23,8 s | aucune confirmation après l'arrêt ; rendu à 21,2 s (un appel au modèle déjà lancé a fini) |
| Prompt du projet — fait retenu (« Redis 8 ») | 1/3 | 3/3 |
| Prompt du projet — profil (« réponds en anglais ») | 0/3 | 2/3 |
| Prompt du projet — tâche neutre | 3/3 | 3/3 |
| Redélégation, tâches qui se découpent | profondeur 2 : une réponse vide en 120 s (3 redélégations), puis 22 à 42 s | profondeur 1 et outil masqué : 10,7 à 38,3 s, qualité complète, 0 redélégation |

Deux réglages viennent directement des mesures :
- **marge d'arrêt de 30 s** : avec 5 s, la passerelle abandonnait la
  première, car l'échéance n'est vérifiée qu'entre deux réponses du modèle et
  une réponse en cours a duré 11 s de plus ;
- **outil de délégation masqué au sous-agent** : sinon il tentait de
  redéléguer 3 fois (refusé, mais 3 appels au modèle perdus).

## 2. Quand l'agent principal délègue-t-il ?

5 questions simples (1 fichier ou aucun) et 5 tâches « découpables ».

| Version | Questions simples déléguées | Tâches découpables déléguées |
| --- | --- | --- |
| Description d'origine | 1/5 (dont `/api/health` délégué 2 fois, 145,9 s) | 1/5 (110,4 s en déléguant, 16 à 28 s sans) |
| Description resserrée seule | 0/5 | 0/5 |
| + règle d'orchestration dans le prompt `v2`, passage 1 | 0/5 | 4/5 |
| idem, passage 2 | 1/5 | 3/5 |
| Demande explicite (« délègue à un sous-agent… ») | — | 6/6 (2 passages) |

Recompté selon la règle (« trois fichiers ou plus ») : sur 2 passages, 6
tâches sur 8 qui citent trois fichiers ou plus sont déléguées, et 2 demandes
sur 12 qui ne devaient pas l'être le sont. Déléguer coûte du temps : 37 à
120 s contre 13 à 33 s sans délégation.

## 3. Agents spécialisés (rôles)

Demande faite à un rôle sans écriture : « crée notes.md avec write_file ».

| Rôle | Essais | Fichier créé | Confirmation demandée |
| --- | --- | --- | --- |
| explorateur | 5 | 0 | 0 |
| relecteur | 5 | 0 | 0 |

Ce que le modèle **dit** n'est pas toujours vrai : une fois, l'explorateur a
répondu « Le fichier notes.md a été créé » alors que rien n'a été écrit (il
ne voit pas l'outil). Deux fois, un rôle a tapé l'appel d'outil en texte
(`<tool_call>…`) : la passerelle l'a signalé (`forged_tool_markup`, EV2) et
rien n'a été exécuté. Le relecteur, lui, répond « VALIDÉ » à une demande
hors sujet : sans conséquence ici (il ne peut rien écrire), mais c'est la
même tendance que celle corrigée au point 5.

## 4. Passage de relais (`team_task`)

Projet jetable avec `stats.py` (deux bugs volontaires). Trois tâches
vérifiables, le code final est **exécuté** (assertions) :
corriger `moyenne`, corriger `maximum` pour les négatifs, ajouter `mediane`.

| Série | Essais | Code final juste | Chemin | Durée |
| --- | --- | --- | --- | --- |
| Avant le correctif du relecteur | 9 | 9/9 | explorateur → développeur → relecteur, validé | 25,2 à 38,4 s |
| Version finale | 9 | 9/9 | 8 validés ; 1 coupé par une erreur réseau du proxy RunPod (le fichier avait déjà été écrit, juste) | 26,6 à 44,6 s (96,9 s pour l'erreur réseau) |
| Tâche « docstrings », rapport complet | 3 | — | validé 3/3, 1 écriture | 39,1 à 42,0 s |

Ces tâches sont faciles : le développeur les réussit du premier coup, donc
la boucle de correction ne s'est pas déclenchée dans cette série. Elle est
couverte par les tests (`tests/tools/test_team_tool.py`) et par le point 5.

## 5. Le relecteur juge-t-il vraiment ?

Le relecteur reçoit un compte rendu qui prétend « corrigé », sur un fichier
resté faux (ou mal corrigé), puis sur un fichier juste.

| Ce que reçoit le relecteur | Travail faux repéré | Travail juste validé |
| --- | --- | --- |
| le compte rendu seul | **0/6** (validé sans ouvrir le fichier, 2 à 4 s) | — |
| + consigne « lis toujours les fichiers » | 0/6 (une fois 6 lectures, et validé quand même) | — |
| **le contenu exact écrit** (version retenue) | **6/6** | 5/6 |

Le seul « à corriger » sur un travail juste visait le bug de `moyenne`,
réellement resté dans ce fichier : c'est un défaut vrai, hors de la tâche.
Conclusion retenue : la consigne ne suffit pas, il faut **donner la preuve**
au relecteur.

## 6. L'agent principal confie-t-il le code à l'équipe ?

Prompt système `v2`, 5 demandes de modification et 3 questions, 2 passages.

| Version de la règle | Modifications confiées à l'équipe | Questions confiées à l'équipe |
| --- | --- | --- |
| règle simple | 0/3 | 0/3 |
| règle « premier et seul geste », demandes qui disent « avec write_file » | 1/3 | 0/3 |
| idem, demandes formulées naturellement | **20/20** (4 passages) | **0/12** |

Une demande confiée à l'équipe prend 38 à 65 s, contre 13 à 23 s quand
l'agent écrit seul. Un cas à 190 s (l'équipe relancée 3 fois) a conduit à
rendre une chaîne terminée comme un résultat, avec le verdict, et non comme
un échec : il ne s'est pas reproduit ensuite.

## Limites

- Petits échantillons, un seul modèle, un seul pod ; les tâches de code sont
  courtes (un fichier de 12 lignes).
- La chaîne entière tient dans le délai d'un outil (120 s) : une tâche plus
  longue s'arrête avant la fin (comportement testé, pas observé sur le pod).
- Le relecteur ne voit que ce qui a été écrit avec `write_file`.
- Les règles du prompt `v2` orientent le modèle, elles ne le contraignent
  pas : la délégation spontanée reste à 6 sur 8.
- Pas de test de charge : un seul utilisateur, sous-agents l'un après
  l'autre.

## Améliorations possibles

- Routeur de modèles (un petit modèle pour les demandes simples) : à mesurer
  si un second modèle tient en mémoire sur le pod.
- Donner au relecteur le droit d'exécuter des tests dans la sandbox, pour
  juger sur un résultat et pas seulement à la lecture.
- Un jeu de tâches plus difficiles, où le développeur se trompe, pour
  mesurer ce que la boucle de correction rattrape.
