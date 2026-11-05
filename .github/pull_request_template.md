## Ce que ça change

<!-- Une ou deux phrases. Ce qu'un relecteur doit comprendre avant de lire le code. -->

## Lot et décision concernés

<!-- Lot A / B / C / D — et l'ADR si la PR applique ou remet en cause une décision
     (docs/decisions/). Écris « aucun » si ça ne touche à aucune décision. -->

## Comment le vérifier

<!-- La commande à lancer, ou ce qu'il faut regarder pour voir que ça marche. -->

## Avant de demander une relecture

- [ ] `pytest -q` passe
- [ ] `ruff check src tests` ne signale rien
- [ ] la branche est à jour avec `main` (`git pull --rebase origin main`)
- [ ] aucun secret, clé d'API ou `.env` dans le diff
- [ ] si cette PR fixe un choix d'architecture, l'ADR correspondant est écrit
