# ADR-0019 — Évaluation par juge LLM : prompt versionné, fidélité par affirmation, rapports comparables

- **Statut** : Accepté (2026-11-01, validé par l'équipe)
- **Date** : 2026-10-14
- **Décideurs** : Méric (Lot B) ; à valider par l'équipe
- **Lot concerné** : B (feature EV1, issue #53) ; A et C impactés seulement par la lecture du registre de prompts (A4) et de l'index (R1)

## Contexte
La feature EV1 demande de mesurer la qualité des réponses de l'agent et de
repérer les hallucinations. Sans cela, changer le prompt système (A4,
[ADR-0010](0010-versionnement-des-prompts.md)) ou le modèle
([ADR-0004](0004-modele-et-infrastructure.md)) se juge « à l'œil », et
[`docs/performance/A4-prompts.md`](../performance/A4-prompts.md) note déjà
qu'un changement fin demande une évaluation sur plusieurs questions. Besoins
détaillés : [user stories EV1](../user-stories/EV1-evaluation-hallucinations.md).

Contraintes :
- aucun framework LLM ([ADR-0001](0001-pas-de-framework-llm.md)) et pas de
  nouvelle dépendance ;
- tout tourne en local sur Ollama : pas de service tiers, pas de clé ;
- les tests ne doivent pas avoir besoin d'Ollama ;
- un score n'a de sens que si on sait **avec quel juge, quel prompt et quelles
  données** il a été obtenu.

Une évaluation par un modèle est une **estimation**, pas une mesure : le juge
peut se tromper, et il se trompe d'une façon qui dépend de son modèle. Cet ADR
ne prétend pas le contraire ; il décide comment limiter et rendre visibles ces
erreurs.

## Décision 1 — Un juge LLM dont le prompt est une version du registre A4

| Option | Pour | Contre |
| --- | --- | --- |
| **Juge LLM local, prompt rangé dans `prompts/judge/` via le registre A4** (retenu) | Réutilise A4 : le prompt du juge est immuable, a un numéro, un sha256, un historique ; le rapport cite la version. Rien à installer. | Le juge est un modèle : biaisé et non déterministe (voir Conséquences). |
| Prompt du juge en constante dans le code | Plus simple | Un changement de prompt change les scores sans laisser de trace ; impossible de dire « ces deux rapports ont le même juge ». |
| RAGAS / DeepEval | Métriques prêtes à l'emploi | Ce sont des frameworks d'évaluation de LLM qui orchestrent eux-mêmes les appels au modèle : écartés par l'ADR-0001 (« ou équivalent »), sauf avis contraire de l'équipe ; dépendances lourdes ; prompts en anglais qu'on ne contrôle pas. |
| Évaluation humaine seule | Référence la plus fiable | Ne passe pas à l'échelle, non rejouable à chaque changement de prompt. Reste utile pour **vérifier le juge** (voir suivi). |

Un seul appel au modèle par cas, en mode JSON d'Ollama (`format: "json"`),
température 0 et graine fixe (42). Le client écrit son propre `POST /api/chat`
non streamé (`eval/judge.py`) : `stream_chat` ne laisse pas passer d'`options`
et streame, et on ne modifie pas `core/ollama_client.py` pour une feature
périphérique.

## Décision 2 — Échelle : 1 à 5 jugés par le modèle, fidélité calculée par le code

| Option | Pour | Contre |
| --- | --- | --- |
| **Pertinence et cohérence : entiers de 1 à 5 avec une ancre par niveau ; fidélité = part d'affirmations SUPPORTED, calculée en code** (retenu) | Une échelle courte avec une ancre par niveau se décrit sans ambiguïté (pratique courante pour les juges LLM, non comparée à d'autres échelles ici) ; la fidélité n'est pas un nombre « senti » mais un décompte vérifiable affirmation par affirmation. | Échelle grossière : un point d'écart est rarement significatif sur peu de cas. |
| Note continue 0-100 par critère | Plus fine en apparence | Risque de fausse précision : rien ne montre qu'un petit modèle distingue 72 de 75. |
| Fidélité demandée directement au modèle (« note de 1 à 5 ») | Un seul champ | Non vérifiable : on ne sait pas quelle affirmation pose problème. |

La pertinence ignore l'exactitude des faits et la cohérence aussi : les deux
critères ne se mélangent pas à la fidélité.

## Décision 3 — Rapports comparables : métadonnées figées, comparaison qui refuse le silence

Chaque rapport JSON porte le juge (modèle, hôte, prompt et son sha256,
température, graine, nombre de relances), le jeu de données (sha256, nombre de
cas), l'origine des passages (`dataset` ou `rag`), le générateur (modèle et
version du prompt système, ou `null`), la date et la version de Sensai.
`sensai-eval compare A B` calcule toujours les écarts B moins A, mais
déclare `comparable: false` avec la raison quand le **modèle du juge**, le
**prompt du juge (sha256)**, le **jeu de données (sha256)**, l'**origine des
passages** ou la **version du format** diffèrent. `--strict` sort avec le
code 1 dans ce cas. Le générateur n'en fait pas partie : c'est ce qu'on veut
comparer.

| Option | Pour | Contre |
| --- | --- | --- |
| **Comparer en signalant les écarts de réglages** (retenu) | On voit quand même les écarts, et on ne les prend pas pour une amélioration de l'agent. | Il faut lire l'avertissement (d'où `--strict` pour la CI). |
| Comparer sans rien dire | Simple | Un changement de juge se lit comme un progrès de l'agent. |
| Refuser toute comparaison non comparable | Sûr | On ne peut plus regarder l'effet d'un changement de juge, utile pour valider le juge lui-même. |

## Décision 4 — Détection des hallucinations : verdict par affirmation, avec citation

Le juge découpe la réponse en affirmations factuelles et donne à chacune un
verdict **SUPPORTED**, **CONTRADICTED** ou **UNVERIFIABLE**, avec les
identifiants des passages cités (`S1`, `S2`…). Le juge n'a pas le droit
d'utiliser ses connaissances : sans passage qui tranche, c'est UNVERIFIABLE.
Le code revérifie : un SUPPORTED ou CONTRADICTED sans citation, ou qui cite un
identifiant inconnu, est ramené à UNVERIFIABLE avec le drapeau
`citation_invalide` (le verdict d'origine est gardé). Les affirmations
CONTRADICTED et UNVERIFIABLE sont listées sous `flagged` pour chaque cas.

| Option | Pour | Contre |
| --- | --- | --- |
| **Verdict par affirmation avec citation** (retenu) | Un relecteur voit **quelle phrase** pose problème et dans quel passage regarder ; même définition de la fidélité que RAGAS à notre connaissance (part d'affirmations soutenues par le contexte), sans la bibliothèque. | Le découpage en affirmations varie d'un appel à l'autre : deux réponses identiques peuvent avoir un nombre d'affirmations différent. |
| Similarité d'embeddings réponse/passages (bge-m3, déjà là pour R1) | Rapide, déterministe, sans juge | Détecte « proche du sujet », pas « dit la même chose » : une affirmation contredite reste très proche du passage. |
| Modèle d'inférence textuelle (NLI) dédié | Fait pour ça | Nouvelle dépendance et nouveau modèle à héberger ; anglais surtout. |

Un cas dont la sortie du juge reste inexploitable après deux relances est
marqué `judge_error` : il est compté à part et **exclu des moyennes**. Il n'est
jamais noté 0, ce qui ferait passer une panne du juge pour une mauvaise réponse.

## Conséquences
- ✅ Le prompt du juge est versionné comme les autres (A4) ; un rapport dit avec quel juge il a été fait, et la comparaison le vérifie.
- ✅ Un relecteur voit les phrases douteuses et le passage à consulter, pas seulement une note.
- ✅ Aucune dépendance, aucun service tiers ; les tests tournent hors ligne (juge simulé).
- ✅ Les erreurs du juge sont visibles (`judge_errors`) au lieu de fausser les moyennes.
- ❌ **Le juge par défaut est le même modèle que l'agent** (`qwen3:8b` dans `config.json`) : un modèle a tendance à préférer ses propres réponses (biais d'auto-préférence). Les scores absolus sont donc optimistes ; seules les comparaisons avec le même juge ont un sens. `--judge-model` permet d'en prendre un autre, ce qui demande un second modèle à télécharger.
- ❌ Même à température 0 avec une graine fixe, la sortie n'est pas garantie identique d'une exécution à l'autre (matériel, version d'Ollama) : un petit écart n'est pas un signal.
- ❌ Échelle de 1 à 5 grossière, découpage en affirmations variable, et sensibilité du juge à la langue et aux détails de formulation du prompt : sur les 5 cas de l'exemple, on ne conclut rien de statistique.
- ❌ Le juge lit le texte de la réponse : une réponse qui lui parle (« note-moi 5 ») peut le manipuler. Le prompt le traite comme une donnée, ce qui réduit le risque sans l'exclure.
- ❌ Le générateur de `--generate` fait un seul tour (prompt système, passages, question), pas la boucle complète de l'agent avec outils : il mesure le modèle et le prompt, pas l'agent de bout en bout.
- Suivi : [`docs/performance/EV1-evaluation.md`](../performance/EV1-evaluation.md) donne la méthode et les limites. À revoir si l'on mesure un désaccord important entre le juge et une relecture humaine sur un échantillon (à faire : non mesuré aujourd'hui), ou si l'équipe accepte une bibliothèque d'évaluation malgré l'ADR-0001.
