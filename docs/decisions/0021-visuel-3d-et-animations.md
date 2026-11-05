# ADR-0021 — Visuel d'agent : le portrait fourni, fixe, avec lueur et ruban sobres

- **Statut** : Remplacé par ADR-0056 (2026-11-02 : le visuel 3D est retiré du code)
- **Date** : 2026-10-13
- **Décideurs** : Valentino (Lot D)
- **Lot concerné** : D

## Contexte
La landing et l'écran d'accueil du chat doivent montrer un agent avec un visuel soigné. Valentino a fourni
le portrait de l'IA retenue (PNG haute résolution avec canal alpha). Il porte sur la visière le texte
« TURNOVER MARKETING », nom d'une marque tierce, et son origine et ses droits n'ont pas été vérifiés.

Plusieurs versions ont été essayées puis écartées par Valentino : une tête 3D construite en code ou
issue d'un scan sous licence (elle ne ressemblait pas à l'IA voulue), un fondu entre 8 vues d'une planche
(flou, rendu artificiel), puis une version très animée (inclinaison vers le curseur, électrons, rafales,
cycle d'ambiances), jugée « trop ». Il veut quelque chose de simple et bien dessiné.

## Options envisagées
| Option | Pour | Contre |
| --- | --- | --- |
| Tête 3D construite en code ou scan sous licence | Vraie 3D, droits clairs | Ne ressemble pas à l'IA voulue (rejeté). |
| Rotation par fondu entre les vues d'une planche | Tour complet | Vues petites et floues, rendu artificiel (rejeté). |
| Portrait animé (inclinaison, électrons, rafales, cycle) | Spectaculaire | Jugé excessif par le demandeur (rejeté). |
| **Portrait fixe, lueur douce, ruban qui l'entoure** | Sobre, net, fidèle à l'image fournie ; le ruban passe devant et derrière l'IA grâce à la profondeur | L'IA est une image fixe : voir les inconvénients. |

## Décision
Un script (`frontend/scripts/prepare_ai_frames.py`) détoure le portrait et l'écrit en WebP
(`frontend/public/ai/portrait.webp`). La scène (three.js) affiche ce portrait fixe, une lueur orange douce
et deux rubans fins qui l'entourent, devant et derrière ; seul le texte des rubans défile lentement. Il n'y
a aucune autre animation.

**La scène n'est pas enfermée dans un conteneur** : le canvas couvre toute la largeur de l'écran, derrière
le texte. Sa hauteur suit celle de la fenêtre et l'ensemble est mis à l'échelle dessus, placé à droite (ou
au centre sur petit écran) : l'IA reste entière et le ruban file jusqu'au bord de l'écran au lieu d'être
coupé par une ligne droite. Sur l'écran d'accueil du chat, le canvas déborde en plus de 12 % en haut et en
bas de son emplacement, pour que le ruban ne soit pas tronqué, et l'IA y est centrée sur la page. Si WebGL
manque, un orbe animé prend la place. `framer-motion` anime le reste
de l'interface (apparitions, compteurs) et respecte `prefers-reduced-motion` ; dans ce cas le texte des
rubans ne défile plus.

## Conséquences
- ✅ Un visuel sobre, net, entier dans la section d'accueil, en thème clair comme sombre.
- ✅ Rien n'est coupé par un bord de conteneur, et la mise à l'échelle suit l'écran.
- ✅ Le reste du site n'est pas alourdi : la scène est un chunk séparé, chargé à la demande.
- ❌ **Droits non vérifiés** : l'origine de l'image et le droit de la réutiliser ne sont pas établis (`docs/legal/licences.md`). Elle portait le nom d'une marque tierce ; le script **efface ce texte** par défaut (`--keep-text` le conserve). C'est une modification de l'œuvre : à confirmer avant tout rendu public.
- ❌ **L'IA est une image fixe** : pas d'inclinaison, de rotation ni de profondeur. Le ruban, lui, est en vraie 3D.
- ❌ **L'effacement du texte laisse un léger aspect irrégulier** sur la visière, visible de près.
- ❌ **Poids mesuré (build du 2026-10-13)** : chunk de la scène 808 Ko (218 Ko compressés), image 111 Ko, contre 321 Ko (106 Ko compressés) pour le bundle principal, `framer-motion` compris. C'est lourd pour un visuel presque fixe : l'essentiel du chunk est three.js. L'orbe de secours s'affiche pendant le chargement.
- ❌ **La scène se redessine en continu** pour faire défiler le texte du ruban, et un canvas pleine largeur coûte plus qu'un petit cadre sur un grand écran à haute densité de pixels (rendu plafonné à deux fois la densité, non mesuré sur la machine de démo). Il faut aussi masquer le défilement horizontal de la page.
- ❌ **Il faut WebGL** ; le rendu n'est pas couvert par des tests automatiques (seuls la détection WebGL, le repli et la salutation le sont). Il est vérifié à l'œil dans le navigateur.
- ❌ **L'image source** (un PNG) est à la racine du dépôt, non suivie par git : sans elle, le script ne peut pas être rejoué.
- Suivi : confirmer l'origine et les droits de l'image ; si l'équipe veut son propre nom sur la visière, regénérer l'image avec ce texte plutôt que de la retoucher ; mesurer l'affichage sur la machine de démo. **Seuil de révision** : si le poids de three.js n'est plus justifié (par exemple si le ruban devient une simple image), remplacer la scène par une image et du CSS, et supprimer la dépendance. Même décision si la scène met plus de quelques secondes à s'afficher sur la machine de démo.
