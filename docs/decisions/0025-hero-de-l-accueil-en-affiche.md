# ADR-0025 — Hero de l'accueil composée comme une affiche, sans scène 3D

- **Statut** : Accepté (2026-11-01, validé par l'équipe)
- **Date** : 2026-10-14
- **Décideurs** : Valentino (Lot D)
- **Lot concerné** : D

## Contexte
Comportement attendu : [US-X1-5](../user-stories/README.md), qui remplace US-X1-4 pour l'accueil.

Valentino a fourni une maquette de référence pour la hero de l'accueil : un portrait au centre, un nom
écrit en très grand au pied de l'écran et posé devant le sujet, une accroche à gauche, une courte
présentation et un bouton orange à droite, un menu réduit à une pilule « logo + burger » en haut à gauche.
Il veut ce rendu « exactement », adapté aux thèmes clair et sombre, avec chaque élément bien mis en valeur.

L'ADR-0021 affichait le portrait dans une scène three.js entourée de rubans. Ce visuel ne correspond pas à
la maquette (qui n'a pas de ruban), et l'ADR-0021 prévoyait déjà son seuil de révision : « si le poids de
three.js n'est plus justifié, remplacer la scène par une image et du CSS ».

## Options envisagées
| Option | Pour | Contre |
| --- | --- | --- |
| Garder la scène 3D et poser la nouvelle mise en page autour | Rien à retirer ; ruban conservé | Le ruban brouille le nom géant et l'accroche ; 808 Ko de three.js chargés pour une image fixe ; éloigné de la maquette. |
| **Portrait en image (`<img>`), mise en page en CSS, animations framer-motion** | Fidèle à la maquette ; plus de chunk three.js sur l'accueil ; pas de WebGL requis | Le ruban disparaît de l'accueil ; l'écran d'accueil du chat garde la scène 3D, donc deux traitements du même portrait. |
| Image composée à l'avance (portrait + nom dans un seul fichier) | Rendu identique partout | Texte non sélectionnable, non traduisible, flou en grand ; impossible d'adapter le nom au thème. |

## Décision
La hero de l'accueil (`frontend/src/features/hero/LandingHero.tsx`) affiche le portrait en `<img>`, centré,
le buste sortant par le bas. Le nom « CodeSensei » occupe toute la largeur (taille en `vw`) et passe devant
le buste. En thème sombre il est blanc, comme sur la maquette. En thème clair il est rendu en
`mix-blend-mode: difference` : sombre sur le fond clair, clair là où il croise le buste sombre, donc lisible
partout sans choisir une couleur unique. L'en-tête de l'accueil devient une pilule flottante (logo + menu
burger) ; les autres pages gardent la barre de navigation complète. Le bouton d'appel à l'action utilise
`#d63f00` avec du texte blanc dans les deux thèmes (contraste 4,59:1, AA). Sur mobile, la grille s'efface
et les éléments s'empilent : accroche, portrait avec le nom en surimpression, présentation et bouton.

La scène 3D de l'ADR-0021 reste utilisée par l'écran d'accueil du chat (`Welcome`).

## Conséquences
- ✅ Rendu fidèle à la maquette, dans les deux thèmes, vérifié à l'œil dans le navigateur à 1440×900,
  1024×768 et 375×812 (sans défilement horizontal).
- ✅ L'accueil ne charge plus le chunk de la scène (808 Ko, 218 Ko compressés, mesuré au build du
  2026-10-14) : il n'est plus téléchargé qu'en ouvrant le chat. Le portrait (111 Ko) suffit.
- ✅ L'accueil n'a plus besoin de WebGL.
- ❌ **Le ruban disparaît de l'accueil** : le visuel de l'accueil et celui du chat ne sont plus traités pareil.
- ❌ **Le mélange `difference` du thème clair** donne au nom une teinte crème là où il croise le buste
  bleu, et bleutée sur la visière orange : c'est voulu (effet d'affiche), mais ce n'est pas un noir uni.
- ❌ **La taille du nom est calée à la main** (`17.8vw`) sur la police Plus Jakarta Sans : si la police ne
  charge pas, la police de secours est plus étroite et le nom ne remplit plus toute la largeur. Si le nom
  change, il faut recaler cette valeur.
- ❌ Le menu de l'accueil cache la navigation derrière un clic de plus que sur les autres pages.
- ❌ Les droits sur le portrait ne sont toujours pas vérifiés (voir ADR-0021) : la hero le met encore plus
  en avant.
- Suivi : tests `frontend/tests/landing.test.tsx` (menu flottant, titre, appel à l'action). À revoir si
  l'équipe veut retrouver le ruban sur l'accueil, ou si le nom du produit change.
