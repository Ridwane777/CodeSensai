# Conditions d'utilisation — CodeSensei

*Version du 2026-10-11. Projet étudiant (the school) ; ce texte ne remplace pas
l'avis d'un juriste.*

## 1. Objet

CodeSensei est un assistant de développement : il lit du code, raisonne
étape par étape, propose et exécute du code dans un environnement isolé, avec
votre accord. C'est un **projet pédagogique**, fourni gratuitement, **en
l'état**, sans garantie de disponibilité ni de maintenance.

## 2. Ce que vous devez savoir sur les réponses

- Les réponses sont produites par un **modèle de langage**. Elles peuvent
  être **fausses, incomplètes ou obsolètes**, même quand elles ont l'air sûres.
- **Relisez tout code avant de l'utiliser** en dehors de CodeSensei, et ne
  vous fiez pas aux réponses pour des décisions juridiques, médicales,
  financières ou de sécurité.

## 3. Exécution de code et actions sur votre machine

- Avant toute action qui écrit ou exécute quelque chose, CodeSensei vous
  montre ce qu'il va faire et **attend votre accord explicite**. Sans réponse,
  c'est un refus.
- **Vous êtes responsable de ce que vous acceptez.** Lisez le code présenté
  avant de dire oui.
- Le code s'exécute dans un conteneur Docker jetable, sans réseau et sans
  accès à vos fichiers (feature T2) ; cette isolation réduit les risques mais
  ne les supprime pas. L'écriture de fichiers (`write_file`) agit, elle,
  **directement sur votre projet**, après votre accord et en montrant le diff.

## 4. Usages interdits

Il est interdit d'utiliser CodeSensei pour :
- attaquer, s'introduire dans ou perturber un système informatique sans
  autorisation (Code pénal, art. 323-1 et suivants) ;
- produire des logiciels malveillants ou contourner des mesures de sécurité ;
- traiter des données personnelles de tiers sans base légale ;
- violer les droits de propriété intellectuelle d'autrui ;
- contourner volontairement les garde-fous (confirmation, filtrage, sandbox).

## 5. Vos données

Voir la [politique de confidentialité](politique-de-confidentialite.md). En
bref : tout reste sur votre machine, sauf ce qui est envoyé au serveur de
modèle que vous configurez. **Ne collez pas de secrets** (clés d'API, mots de
passe) dans la conversation.

## 6. Propriété intellectuelle

- Le code que vous écrivez avec CodeSensei vous appartient.
- Les modèles utilisés (Qwen3, Qwen3-Coder) et Ollama ont leurs propres
  licences : voir [licences.md](licences.md).
- La licence du code de CodeSensei lui-même n'est pas encore choisie.

## 7. Responsabilité

L'équipe fait de son mieux pour que CodeSensei soit sûr, mais ne peut être
tenue responsable des dommages résultant d'une réponse erronée, d'un code
accepté par l'utilisateur ou d'un usage contraire à ces conditions, dans les
limites prévues par la loi.

## 8. Modifications

Ces conditions peuvent évoluer avec le projet. La version en vigueur est
celle de ce fichier ; son historique est visible dans Git.
