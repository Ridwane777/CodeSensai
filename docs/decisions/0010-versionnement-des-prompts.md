# ADR-0010 — Versionnement des prompts : versions immuables dans le dépôt, marque-page « active »

- **Statut** : Accepté (2026-11-01, validé par l'équipe)
- **Date** : 2026-10-12
- **Décideurs** : Ridwane NICO (Lot C), à valider avec le Lot A (fichiers partagés)
- **Lot concerné** : C (impacte A : `config.py`, `config.json`, `prompts/`)

## Contexte
La feature [A4] Prompt Versioning (obligatoire depuis l'ADR-0008) doit permettre de montrer
l'historique des prompts système et de revenir à une ancienne version en une
commande (Definition of Done ClickUp). Elle sert **l'équipe qui construit
l'agent**, pas l'utilisateur final : « vous allez de toute façon itérer sur
les prompts système (ReAct, guardrails, persona) pendant tout le projet —
autant les traiter comme des artefacts versionnés, comparables et
"rollback-ables" ». La feature A7 (Lot A) pourra s'appuyer dessus. Besoins
détaillés : [user stories A4](../user-stories/A4-prompt-versioning.md).

Cas vécu : le prompt mémoire de M1 (`prompts/memory_prompt.txt`), ajouté après
les essais, a changé les réponses du modèle
([essais M1](../performance/M1-sessions.md)).

État vérifié le 2026-10-12 sur toutes les branches distantes :
- `prompts/system_prompt.txt` est chargé par `config.py` partout ;
- `prompts/memory_prompt.txt` est chargé sur les branches de M1 et R1 ;
- `prompts/react_prompt.txt` n'est chargé nulle part, y compris sur
  `lot-a/boucle-react` (la boucle passe par le tool calling natif) ;
- aucun prompt « guardrails » n'existe (`lot-b/guardrails` n'en a pas).

**Pratique de l'industrie** (Langfuse, Arize, Agenta, PromptLayer, Maxim ;
sources en fin de document) : une **version est immuable** et identifiée par
un numéro ou une empreinte ; une **étiquette** (`production`…) est un
**pointeur mobile** ; l'application charge la version pointée, et revenir en
arrière consiste à **déplacer le pointeur**, sans redéploiement. On garde avec
chaque version qui l'a créée, quand et pourquoi. Les équipes commencent
souvent avec des prompts dans git, puis ajoutent ce registre quand revenir en
arrière exige un revert et un redéploiement.

Contraintes :
- `config.py` et `prompts/system_prompt.txt` sont partagés avec le Lot A ;
  les autres branches ne doivent pas casser avant la fusion.
- Pas de nouvelle dépendance.

## Options envisagées

**1. Où vivent les versions**

| Option | Pour | Contre |
| --- | --- | --- |
| **Dans le dépôt** (retenu) : un dossier par prompt (`prompts/system/v1.txt`…) et un index `prompts/versions.json` | Partagé par l'équipe, relu en PR, lisible sans outil, chargeable depuis le code (A7) | Un fichier de plus par version dans le dépôt |
| Base locale (SQLite dans `~/.sensai/`, comme M1) | Retour en arrière immédiat | Chaque développeur aurait son propre historique : les versions d'un coéquipier seraient invisibles (contraire à US-A4-1) |
| Git seul (`git log` et `git diff` sur `prompts/`) | Rien à stocker | Ne fonctionne que dans un clone ; une modification non commitée n'est pas une version ; les versions ne sont pas des objets que le code (A7) peut charger simplement |

**2. Ce que l'agent lit**

| Option | Pour | Contre |
| --- | --- | --- |
| **La version qui porte le marque-page** (`"active"` dans l'index) (retenu) | Conforme à la pratique de l'industrie : revenir en arrière ne fait que déplacer le marque-page, rien n'est recopié ni effacé | Demande de modifier `config.py` (Lot A) |
| Garder `system_prompt.txt` comme fichier lu, et y recopier une version pour revenir en arrière | `config.py` inchangé | Texte en double ; on ne sait plus quelle version est en service. Retenu dans un premier temps, abandonné après la recherche sur la pratique de l'industrie |
| Création automatique d'une version à chaque modification détectée au lancement | Aucun geste à faire | Historique bruité, sans description ; conflits quand deux branches créent la même version |

**3. Identifier une version**

| Option | Pour | Contre |
| --- | --- | --- |
| **Un numéro** (`v1`, `v2`…), avec date, auteur, description et empreinte sha256 dans l'index (retenu) | Lisible et court à taper. L'empreinte n'identifie pas : elle permet à `sensai-prompt check` (et à la CI) de détecter une version modifiée après avoir été rangée — sans elle, « une version n'est jamais modifiée » ne serait qu'une convention (ajoutée en écrivant les tests) | Deux branches qui créent chacune une `v4` produisent un conflit git dans `versions.json` : on renumérote l'une des deux |
| Date et heure (`2026-10-12_1724`) | Pas de collision | Long à taper |
| Empreinte sha256 comme identifiant | Pas de collision | Illisible ; utile seulement si chaque machine tenait son propre historique |

**4. Quels prompts versionner**

| Option | Pour | Contre |
| --- | --- | --- |
| **`system` et `memory`, avec un mécanisme générique** (ajouter un prompt = une ligne) (retenu) | Les deux seuls prompts qui influencent réellement l'agent | — |
| `system` seul | La lettre de la DoD | Pas d'historique pour le prompt mémoire, le cas réel |
| Inclure `react_prompt.txt` | Complet en apparence | Ce fichier n'a aucun effet : on versionnerait un fichier inutilisé |

**5. Commandes**

| Option | Pour | Contre |
| --- | --- | --- |
| **Une commande séparée, `sensai-prompt`**, déclarée dans `pyproject.toml` (retenu) | Outil d'équipe utilisé comme `git` ; n'a besoin ni d'Ollama ni de l'agent ; utilisable en script ou en CI ; ne touche pas au parseur du Lot A | Une commande de plus à connaître |
| Des commandes dans la session (`/prompt …`), comme M1 | Même style que M1 | Il faudrait lancer l'agent pour consulter un historique |
| Des sous-commandes `sensai prompt …` | Une seule commande | Il faudrait réorganiser le parseur de `config.py`, partagé avec le Lot A |

## Décision
- Les versions vivent dans `prompts/<nom>/vN.txt` ; l'index
  `prompts/versions.json` garde, pour chaque prompt, le marque-page `active`
  et la liste des versions (`id`, `date`, `author`, `description`,
  `sha256`) :

  ```json
  {
    "system": {
      "active": "v2",
      "versions": [
        {"id": "v1", "date": "2026-09-22", "author": "…", "description": "prompt initial", "sha256": "a1dc…"},
        {"id": "v2", "date": "2026-10-12", "author": "…", "description": "précise le format", "sha256": "…"}
      ]
    },
    "memory": {"active": "v1", "versions": ["…"]}
  }
  ```

- Une version enregistrée n'est jamais modifiée ni supprimée ; un test
  (`tests/test_prompts_registry.py`) vérifie le registre du dépôt en CI.
- L'agent charge la version `active` de chaque prompt. Si `versions.json` est
  absent, il relit `prompts/system_prompt.txt` et `prompts/memory_prompt.txt`
  comme aujourd'hui. L'option existante `--system-prompt <fichier>` garde la
  priorité : elle sert à essayer un brouillon.
- Au lancement, `sensai` affiche les versions utilisées (« prompts : system
  v2, memory v1 »).
- Migration : le contenu actuel de `system_prompt.txt` et de
  `memory_prompt.txt` devient la `v1` de chaque prompt ; les deux fichiers sont
  ensuite supprimés, pour que le texte n'existe qu'à un seul endroit. Date et
  auteur de chaque `v1` : ceux du dernier commit du fichier d'origine. La clé
  `system_prompt_path` est retirée du `config.json` du dépôt : elle désignait
  l'ancien fichier, et un chemin explicite passe avant le registre.
- Commandes :

  ```
  sensai-prompt history <prompt>                      versions : n°, date, auteur, description, (active)   US-A4-1
  sensai-prompt show <prompt> [version]               contenu d'une version (l'active par défaut)
  sensai-prompt diff <prompt> <v1> [v2]               différences ligne par ligne (v2 = l'active)          US-A4-1
  sensai-prompt save <prompt> <fichier> "description" range le fichier comme nouvelle version             US-A4-2
  sensai-prompt use <prompt> <version>                déplace le marque-page                               US-A4-3
  sensai-prompt check                                 cohérence : numéros, fichiers, marque-pages, empreintes
  ```

- `save` ne déplace pas le marque-page (on range, puis on met en service) et
  refuse un texte identique à une version existante. L'auteur est lu dans
  `git config user.name`.
- Différences calculées avec `difflib` (bibliothèque standard).

Déroulé type pour l'équipe :

```
sensai-prompt show system > brouillon.txt                 je pars du texte en service
sensai --system-prompt brouillon.txt                      je l'essaie
sensai-prompt save system brouillon.txt "précise X"       il devient v3
sensai-prompt diff system v2 v3                           je compare
sensai-prompt use system v3                               l'agent lit la v3
sensai-prompt use system v2                               retour en arrière si besoin
```

## Conséquences
- ✅ Vérifié avec un vrai modèle (`qwen3:8b`, 2026-10-12) : passer à une v2
  qui impose le français fait répondre l'agent en français, et
  `sensai-prompt use system v1` rétablit l'anglais
  ([essai réel](../performance/A4-prompts.md)).
- ✅ Revenir en arrière = déplacer un marque-page : une commande, aucun texte
  recopié, aucune version perdue (DoD).
- ✅ Historique commun à l'équipe, relu en PR, avec qui, quand et pourquoi
  pour chaque version.
- ✅ Les versions sont des objets chargeables par le code : A7 pourra essayer
  ou comparer des versions sans passer par git.
- ✅ Aucune nouvelle dépendance ; les autres branches continuent de
  fonctionner grâce au repli sur les anciens fichiers.
- ❌ **Modifie `config.py` et `config.json`, et supprime
  `prompts/system_prompt.txt`**, partagés avec le Lot A : à valider avec
  Fresnel avant la fusion. Un `config.json` personnel qui garde
  `system_prompt_path` court-circuite le registre (un chemin explicite est
  prioritaire).
- ❌ Déplacer le marque-page modifie `versions.json` : pour que ça s'applique
  à toute l'équipe, il faut le commiter (un essai personnel se fait sans
  commit).
- ❌ Deux branches qui créent la même version produisent un conflit à la
  fusion, à résoudre à la main en renumérotant.
- ❌ Le modèle et ses paramètres ne sont pas versionnés avec le prompt : ils
  restent dans `config.json`. Une réponse dépend des deux.
- ❌ Hors A4, à signaler à l'équipe : `react_prompt.txt` n'est utilisé nulle
  part (à brancher ou supprimer) ; les fichiers `prompts/` ne sont pas inclus
  dans le paquet installé (vérifié en construisant le wheel), problème qui
  existait avant A4.
- ❌ Dépend du prompt mémoire de M1 : la branche est empilée sur celles de M1
  et R1, à rebaser après leur fusion.

## Évolutions prévues
La feature évoluera avec les apports des autres lots : versionner le prompt
ReAct quand le Lot A le branchera, s'appuyer sur EV1 pour associer des
résultats d'évaluation à chaque version, et laisser A7 créer des versions.

## Sources
- [Langfuse — Prompt Version Control](https://langfuse.com/docs/prompt-management/features/prompt-version-control)
- [Arize — What Is Prompt Versioning?](https://arize.com/glossary/prompt-versioning/)
- [Agenta — Git vs. Prompt Management Tools](https://agenta.ai/blog/git-vs-prompt-management-tools)
- [Agenta — Prompt Versioning: The Complete Guide](https://agenta.ai/blog/prompt-versioning-guide)
- [PromptLayer — How to version prompts in LLM apps](https://blog.promptlayer.com/how-to-version-prompts-in-llm-apps/)
- [Maxim — Prompt Versioning: Best Practices for AI Engineering Teams](https://www.getmaxim.ai/articles/prompt-versioning-best-practices-for-ai-engineering-teams/)
- [Hamel Husain — How should I version and manage prompts?](https://hamel.dev/blog/posts/evals-faq/how-should-i-version-and-manage-prompts.html)
