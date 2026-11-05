# ADR-0026 — Univers « code » animé : stop motion, parallaxe et analyse de bug en direct

- **Statut** : Remplacé par ADR-0056 (2026-11-02 : l'univers de code animé est retiré du code)
- **Date** : 2026-10-14
- **Décideurs** : Valentino (Lot D)
- **Lot concerné** : D

## Contexte
Comportement attendu : [US-X1-6 et US-X1-7](../user-stories/README.md), écrites avant de figer cette décision ; elles remplacent US-X1-4 (« visuel calme, sans particules »).

Après la hero en affiche (ADR-0025), Valentino juge l'accueil « fade, pas d'animation ». Il veut qu'on
« plonge dans l'univers » d'un agent de code : du code qui s'écrit dans la hero, est analysé et dont les
bugs sont jugés, une animation stop motion simple, de la parallaxe et des effets qui suivent la souris.
Il veut aussi que le chat adopte ce même univers.

L'ADR-0021 rappelle qu'une version très animée (inclinaison, électrons, rafales) avait été jugée « trop ».
La demande actuelle porte sur autre chose : montrer le **travail** de l'agent (lire, scanner, juger,
corriger), pas un décor qui bouge pour bouger.

## Options envisagées
| Option | Pour | Contre |
| --- | --- | --- |
| Vidéo ou GIF d'une session enregistrée | Rendu exact d'une vraie session | Lourd, flou en grand, impossible à adapter au thème, texte non accessible. |
| Lottie / bibliothèque d'animation dédiée | Animations riches | Nouvelle dépendance, et l'animation se dessine dans un autre outil. |
| **Composants React + CSS `steps()` + framer-motion (déjà présent)** | Aucune dépendance ajoutée ; texte réel, coloré par thème ; logique testable | Tout est à écrire et à régler à la main. |

## Décision
Un petit module `frontend/src/features/code/` porte l'univers :
- `useAnalysis` : une machine d'états (frappe → scan → bug → effacement → correction → verdict) qui
  avance d'une image toutes les 90 ms, environ 11 images/s, le rythme saccadé du stop motion. Trois extraits
  Python réalistes tournent en boucle (division par zéro, `=` au lieu de `==`, `await` manquant).
- `CodeEditorCard` et `VerdictCard` : l'éditeur où le code s'écrit, avec le faisceau de scan, la ligne
  fautive soulignée en rouge puis réécrite en vert, et le terminal qui « juge » et compte les bugs corrigés.
- `CodeRain` : des colonnes de code qui défilent par à-coups (`animation: … steps(48)`), en décor.
- `useMouseParallax` : la souris déplace chaque couche selon sa profondeur (décor, portrait, cartes, nom).
- Un tremblement image par image (`.boil`) sur les cartes, et un faisceau qui balaie le visage de l'IA,
  découpé sur sa silhouette par un masque CSS.

Le chat reprend l'univers : pluie de code en fond, raisonnement présenté comme un terminal numéroté
(« › Pensée », « $ outil(args) », « ← Observation »), invite `~/projet ❯`, et l'analyse en direct sur
son écran d'accueil.

Si l'utilisateur demande moins d'animations (`prefers-reduced-motion`), tout s'arrête : l'éditeur montre
directement le code corrigé, la parallaxe reste à zéro, le décor est immobile.

## Conséquences
- ✅ L'accueil montre ce que fait l'agent (lire, analyser, juger, corriger) au lieu de seulement l'annoncer.
- ✅ Aucune dépendance ajoutée : le bundle principal passe de 324 Ko à 335 Ko (107 → 111 Ko compressés,
  mesuré au build du 2026-10-14).
- ✅ La boucle d'analyse est testée (`frontend/tests/analysis.test.ts`) ; le reste est vérifié à l'œil.
- ❌ **Les bugs montrés sont scénarisés** : c'est une mise en scène, pas une vraie analyse du projet. La
  démo doit le dire (le badge « moteur simulé » reste affiché).
- ❌ **Plus de travail en continu pour le navigateur** : un minuteur toutes les 90 ms et des animations
  CSS permanentes. Non mesuré sur la machine de démo.
- ❌ **Risque de surcharge** : c'est précisément ce qui avait été reproché à une version précédente
  (ADR-0021). Si l'équipe trouve l'ensemble trop chargé, retirer d'abord le tremblement `.boil`, puis la
  pluie de code.
- ❌ Les cartes de code de la hero sont masquées sous 1024 px de large ou 700 px de haut, faute de place.
- Suivi : mesurer l'usage processeur sur la machine de démo ; remplacer les extraits scénarisés par
  de vrais résultats quand le moteur réel (`httpEngine`) sera branché.
