# Essai réel — [M3] Mémoire de faits

Vérification de M3 avec le vrai modèle, en plus des tests automatiques
(`tests/knowledge/test_facts.py`, `tests/tools/test_fact_tools.py`, et les
tests M3 de `tests/test_cli_rag.py`). Choix :
[ADR-0030](../decisions/0030-memoire-structuree-de-faits.md). L'essai a
aussi conduit à l'[ADR-0031](../decisions/0031-appels-d-outils-ecrits-en-texte.md)
et à la correction d'une régression de M4.

## Ce qui est vérifié
Les user stories : l'agent retient de lui-même un fait (US-M3-1), le
retrouve dans une nouvelle session et trouve les relations inverses
(US-M3-2), corrige une valeur sans laisser l'ancienne et laisse
l'utilisateur effacer (US-M3-3).

## Machine et réglages
- Pod RunPod (Community Cloud, GPU de 24 Go), Ollama 0.40.6,
  `qwen3-coder:30b`, fenêtre de contexte 32 768. Adresse hors dépôt.
- `sensai --no-rag --new-session`, dossier de données jetable, petit projet
  vide ; confirmations données par une entrée programmée (`o`).
- 8 outils proposés au modèle : `run_code`, `read_file`, `write_file`,
  `web_search`, `search_codebase`, `update_state`, `save_fact`, `recall_facts`.

## Premier essai : ce qui marchait et ce qui cassait

| Scénario | Résultat |
| --- | --- |
| « Le service auth utilise Redis 7, dépend de PostgreSQL, Méric en est responsable. Retiens-le. » | ✅ 3 faits enregistrés, chacun confirmé (`add` pour la dépendance, `replace` pour la version) |
| Nouvelle session : « Quelle version de Redis utilise auth ? » | ✅ `recall_facts`, répond 7 en citant le fait |
| « Qu'est-ce qui dépend de PostgreSQL ? » | ✅ recherche inverse : auth |
| « Quelle base utilise billing ? » | ✅ « je n'ai aucun fait », propose de chercher dans le code |
| « On est passés à Redis 8, mets à jour ta mémoire » | ❌ l'appel est écrit **dans le texte** (`<function=remember_fact>…`), rien n'est exécuté, puis le modèle **affirme** « la version a été passée de 7 à 8 » |

## Enquête : appels d'outils écrits en texte

Mesures sur l'API d'Ollama directement (appels structurés reçus dans
`tool_calls`), même prompt système que le CLI :

| Situation | Résultat |
| --- | --- |
| « retiens que… », 1 seul outil proposé | 8/8 structurés |
| même demande, 8 outils proposés | 0/8 |
| sans notre prompt système | même taux qu'avec : ce n'est pas lui |
| `read_file` avec 5 outils (état de `main` le 14/10) | 5/5 |
| `read_file` après l'ajout d'`update_state` (M4, description longue) | **1/5 : régression introduite par M4** |
| description d'`update_state` réduite à une phrase | 5/5 |
| `remember_fact` (12 essais) contre le nom `save_fact` | 4/12 contre 8/12 |

Conclusions : qwen3-coder oublie la balise `<tool_call>` d'ouverture plus
souvent quand les outils proposés sont nombreux et leurs descriptions longues
(aucune phrase précise n'est seule en cause) ; le nom de l'outil compte
aussi. Corrections :
1. descriptions d'outils réduites à une phrase, mode d'emploi déplacé dans le
   prompt système (corrige la régression de M4) ;
2. `remember_fact` renommé `save_fact` ;
3. ADR-0031 : un appel écrit en texte est lu seulement si la réponse n'est
   que des appels à des outils proposés, puis passe par la passerelle et la
   confirmation ; sinon le modèle est relancé deux fois, puis le tour
   s'arrête sur une erreur au lieu d'une fausse affirmation.

Après correction, appels structurés avec les 8 outils (6 essais chacun) :
`read_file` 5/6, `run_code` 6/6, `web_search` 6/6, `search_codebase` 6/6,
`recall_facts` 6/6, `update_state` 6/6, `save_fact` 1/6 (d'où l'ADR-0031).

## Essai final (6 demandes « retiens que… », mémoire vierge)

| | Relances seules | + lecture du texte (ADR-0031) | + cohérence des noms |
| --- | --- | --- | --- |
| Faits enregistrés | 2/5 | 6/6 | **6/6** |
| « Redis 8 » remplace « Redis 7 » | — | ❌ 7 reste, sous un autre nom | ✅ remplacé (l'agent consulte la fiche avant) |
| Doublons | — | 3 noms pour la même donnée | 1 doublon, même valeur |

« Cohérence des noms » : espaces, `_` et `-` équivalents ; la confirmation et
la réponse de `save_fact` montrent les attributs déjà connus de l'entité ; le
prompt demande de consulter l'entité avant d'enregistrer ; un attribut
introuvable renvoie tout ce qu'on sait de l'entité.

Nouvelle session, « Quelle version de Redis utilise le service auth, et sur
quel port ? » : **3 essais sur 3** répondent « Redis 8, port 8080 » avec un
seul `recall_facts` (avant le dernier correctif, le modèle cherchait
`redis_version`, ne trouvait rien et fouillait des fichiers inexistants).

## Limites
- Le modèle choisit lui-même les noms : un doublon reste possible ; la
  confirmation le montre à l'utilisateur, qui peut refuser.
- La lecture des appels en texte dépend du format de qwen3-coder (ADR-0031).
- Mesures sur un seul projet, avec des entrées programmées ; une à huit
  répétitions par cas : des ordres de grandeur.
