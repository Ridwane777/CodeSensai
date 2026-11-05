# ADR-0039 — Sortie structurée (T5) en deux temps : chercher, puis mettre en forme

- **Statut** : Accepté (2026-10-24)
- **Date** : 2026-10-24
- **Décideurs** : Ridwane (lot C) et Fresnel (lot A)
- **Lot concerné** : A (`core/structured.py`) ; le CLI (`cli.py`)

## Contexte

[ADR-0036](0036-sortie-structuree-format-json-schema.md) fait de `/structured`
un appel unique au modèle avec le champ `format` d'Ollama, **sans outils**
(`format` et `tools` ne se combinent pas dans un même appel). La forme est
garantie, le fond ne l'est pas : le modèle ne peut ni lire un fichier ni
chercher dans le projet, il répond de mémoire.

Essai complet sur le pod (2026-10-24) : « la liste des fonctions de
stats.py » a renvoyé cinq fonctions inventées (`moyenne`, `median`, `mode`…)
pour un fichier qui n'en définit qu'une (`maximum`). Mesure dédiée
(`scripts/bench_t5.py`) : **0 réponse juste sur 15**.

## Options envisagées

| Option | Pour | Contre |
| --- | --- | --- |
| Garder l'appel direct et écrire la limite | Rien à changer, une seule requête | Une réponse JSON bien formée mais fausse, sur toute question qui porte sur le projet : 0 sur 15 |
| Joindre au prompt les fichiers cités dans la demande | Une requête de plus au plus, déterministe | Ne marche que si la demande nomme le fichier ; rien pour « où est… » ou « quelles routes… » |
| **Deux temps : l'agent cherche (boucle ReAct, outils, même passerelle), puis l'appel contraint met en forme sa réponse** | Toutes les capacités de l'agent (lecture, recherche, faits) ; garde l'appel contraint d'ADR-0036 tel quel ; mesuré 15 sur 15 | Plus lent (3,7 à 15,8 s contre 0,9 à 3,9 s) ; les confirmations de la passerelle peuvent être demandées pendant `/structured` |

## Décision

Dans le CLI, `/structured <schéma> <demande>` fait d'abord jouer un tour
d'agent (prompt système du projet, outils, même passerelle : mêmes
garde-fous et confirmations), affiché comme un tour normal. Sa réponse est
ensuite donnée à l'appel contraint (`format`), avec la consigne de ne remplir
le schéma qu'à partir de ce que l'agent a trouvé. Sans `gather` (appel
programmatique), le comportement d'ADR-0036 reste disponible.

ADR-0036 n'est pas remplacé : l'appel contraint reste celui qu'il décrit ;
cet ADR ajoute l'étape de recherche qui le précède.

## Conséquences

- ✅ Les réponses portent sur le vrai projet : 15 sur 15 justes contre 0 sur
  15 (détail dans [T5-structured.md](../performance/T5-structured.md)).
- ✅ Aucune nouvelle dépendance ; l'appel contraint et ses garanties de forme
  ne changent pas.
- ❌ Deux à quatre fois plus lent : il y a un tour d'agent avant la mise en
  forme.
- ❌ La mise en forme recopie ce que l'agent a écrit : si l'agent se trompe,
  le JSON se trompe aussi (le bon schéma ne corrige pas un mauvais fond).
- ❌ Les éléments recopiés gardent la forme donnée par l'agent
  (`inverser(phrase)` plutôt que `inverser`) : au schéma de préciser le format
  attendu (`description`) si cela compte.
- Suivi : si l'interface web expose `/structured`, lui donner la même étape.
