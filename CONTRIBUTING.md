# Comment on travaille sur ce dépôt

À lire une fois, avant le premier commit. Ces règles ne sont pas là pour faire
joli : `main` est la branche depuis laquelle on fera la démo, et une seule
personne qui y pousse du code cassé nous coûte une soirée.

## La règle principale

**Personne ne pousse directement sur `main`.** On y entre par une Pull Request
relue. Si les droits d'administration du dépôt ne nous permettent pas de
l'interdire techniquement, la règle tient parce qu'on la respecte.

## Le cycle de travail

```bash
git checkout main
git pull
git checkout -b lot-a/boucle-react
# ... travail, commits ...
git push -u origin lot-a/boucle-react
```

Puis on ouvre la Pull Request sur GitHub.

**Nommage des branches :** `lot-<a|b|c|d>/<sujet-court>`. Le préfixe dit qui
travaille, sans avoir à ouvrir la branche — `lot-b/sandbox-docker`,
`lot-c/rag-ingestion`, `lot-d/api-web`.

**Avant de pousser**, si `main` a bougé entre-temps :

```bash
git pull --rebase origin main
```

Le rebase rejoue ton travail par-dessus le `main` à jour. Tu découvres les
conflits chez toi, pas dans la PR devant les autres, et l'historique reste
lisible.

## Les relectures

Une approbation suffit, puis l'auteur fusionne lui-même. À quatre, exiger deux
relecteurs bloque tout le monde.

**Qui relire :** `.github/CODEOWNERS` le dit, et GitHub le demande tout seul.
La logique : celui qui touche à un contrat partagé fait relire par le
propriétaire du contrat. Le reste, dans son propre dossier, une relecture
rapide par n'importe qui suffit.

`src/sensai/core/tools.py` est le cas sensible : une modification là casse les
trois autres lots. Elle passe toujours par le lot A.

## Des branches courtes

Plus une branche vit longtemps, plus `main` avance sans elle, et plus le risque
augmente d'avoir touché aux mêmes lignes que quelqu'un d'autre. Découpe le
travail : « le client MCP se connecte », puis « le client MCP appelle un
outil » — pas une seule PR énorme.

## Ce qui doit passer avant de demander une relecture

```bash
pytest -q
ruff check src tests
```

La CI (`.github/workflows/ci.yml`) lance les deux sur chaque PR. Une PR rouge
ne se fusionne pas.

Si ta modification ajoute un garde-fou, **ajoute le test qui échoue quand on
le retire** — sinon quelqu'un le « simplifiera » dans trois semaines sans
comprendre à quoi il servait.

## Les décisions d'architecture

Quand un choix structurant est fait — un outil qu'on adopte, une approche qu'on
écarte — il s'écrit dans `docs/decisions/`, à partir de `TEMPLATE.md`. Un
fichier par décision, numéroté, jamais réécrit : si on change d'avis, on en
crée un nouveau qui remplace l'ancien. Chaque ADR ajoute sa ligne dans l'index
`docs/decisions/README.md`, et sa section « Conséquences » dit aussi ce qu'on
perd (au moins un ❌).

Les ADR ne sont qu'une partie du dossier projet (légal, performance, coûts,
rétrospective, business, user stories) : voir `AGENTS.md` et la carte
`docs/README.md`.

Chaque ADR porte un `Statut` : `proposé` tant que l'équipe n'a pas tranché,
`accepté` ensuite. Ne présente pas comme acté ce qui attend encore un accord.

Ce qui mérite un ADR : une décision coûteuse à défaire, ou dont quelqu'un se
demandera « pourquoi ils ont fait ça ? » dans deux mois. Le choix d'un nom de
variable, non.

## Conventions de code

- **Commentaires en français**, comme le reste du code, et qui expliquent le
  **pourquoi** — surtout sur la logique de sécurité. C'est ce qui empêche un
  futur contributeur de supprimer une vérification critique par mégarde.
- **Messages de commit en anglais**, au format déjà en place :
  `feat(scope): ...`, `docs(scope): ...`, `chore(scope): ...`.
- Écrire comme le fichier autour : même style, même niveau de commentaire.

## Ce qu'on ne commite jamais

Aucune clé d'API, aucun `.env`, aucun mot de passe, aucune adresse de pod
privé. Le `.gitignore` en couvre une partie, il ne couvre pas tout — c'est à
relire dans le diff avant de pousser.

Si un secret part quand même : le dire tout de suite à l'équipe, et considérer
la clé comme compromise. La retirer d'un commit ne la retire pas de
l'historique.
