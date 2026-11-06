# Essai réel — [M4] Document d'état du projet

> **Latest trial, 2026-11-06** ([report](essais/essai-2026-11-06.md)), qwen3:8b on the team laptop (CPU) and qwen3-coder:30b on a 24 GB GPU pod: `/state`: ✅ with both set-ups (< 1 s). Earlier measurements below.

Vérification de M4 avec le vrai modèle, en plus des tests automatiques
(`tests/knowledge/test_state_document.py`, `tests/tools/test_state_tool.py`,
et les tests M4 de `tests/test_cli_rag.py`, `tests/core/test_events.py`,
`tests/knowledge/test_rag.py`). Choix :
[ADR-0029](../decisions/0029-document-d-etat-du-projet.md).

## Ce qui est vérifié
La Definition of Done : après plusieurs échanges, le document reflète l'état
du projet **sans avoir été corrompu ni réécrit en entier**. Et les user
stories : l'agent le connaît dans une nouvelle session (US-M4-1), seule la
section visée change (US-M4-2), chaque modification se voit, se trace et
s'annule (US-M4-3).

## Machine et réglages
- Pod RunPod (Community Cloud, GPU de 24 Go), Ollama 0.40.6,
  `qwen3-coder:30b`, **fenêtre de contexte de 32 768 tokens** (lue dans
  `/api/ps`). Adresse du pod hors dépôt.
- Premier appel après le démarrage du pod : 74 s (chargement en mémoire).
- `sensai --no-rag --new-session`, dossier de données jetable, dans un petit
  projet : `calcul.py` (une faute de frappe) et un `SENSAI.md` écrit à la main
  avec un préambule « Note écrite à la main : ne pas toucher. ».
- Les confirmations sont données par une entrée programmée (`o`).

## Scénario et résultats (2026-10-17)

| Étape | Ce que fait l'agent | Résultat |
| --- | --- | --- |
| 1. « Corrige le bug de calcul.py, puis mets à jour le document d'état » | `read_file`, `write_file`, puis `update_state` sur « Fait » et sur « En cours » | ✅ Chaque confirmation affiche la section avant et après. `diff` avec l'original : seules « Fait » et « En cours » ont changé ; le préambule, « Décisions » et « Problèmes connus » sont identiques. 20 s pour le tour |
| 2. Nouvelle session : « Où en est-on ? Réponds sans utiliser d'outil. » | Aucun appel d'outil | ✅ Résumé juste des quatre sections (US-M4-1). 3,5 s avec les commandes |
| 3. `/state history` | — | ✅ Date, action, section et résumé des deux mises à jour |
| 4. `/state undo En cours`, deux fois | — | ⚠️ La 1ʳᵉ remet « - Rien », la 2ᵉ **annule l'annulation**. Conforme à la première version de l'ADR, mais déroutant : corrigé (voir ci-dessous) |
| 5. Après correction : « Ajoute une docstring, note-le, ajoute En cours : écrire des tests », puis `/state undo Fait` deux fois | `write_file`, `update_state` (`append` sur « Fait », `replace` sur « En cours ») | ✅ L'agent utilise `append` sans recopier l'ancienne ligne. Les deux annulations retirent les deux dernières lignes de « Fait », comme Ctrl+Z |

## Ce que l'essai a changé
1. **Annulation à plusieurs niveaux.** Une seconde annulation remonte d'une
   modification de plus au lieu d'annuler la première (ADR-0029 précisé,
   tests `test_deux_annulations_remontent_de_deux_modifications` et
   `test_une_nouvelle_modification_apres_annulation_repart_de_la`).
2. **`append` plutôt que `replace` pour « Fait ».** Au premier essai, le
   modèle remplaçait « Fait » en recopiant l'ancienne ligne : juste, mais un
   oubli aurait effacé une ligne. La description de l'outil recommande
   maintenant `append` pour « Fait » et « Décisions » ; au second essai, il
   l'a utilisé.
3. **Le diff s'affiche à la confirmation.** Le confirmeur du CLI montrait les
   arguments bruts au lieu du plan de l'outil : le diff de `write_file`
   n'était jamais affiché. Corrigé pour les deux outils.

## Limites
- Une mesure par étape : des ordres de grandeur.
- Au second essai, le modèle a aussi proposé d'écrire un fichier de tests ;
  l'entrée programmée n'avait plus de « o » et a répondu par des commandes,
  prises pour des refus. Les refus ont été bien gérés (rien d'écrit), mais
  cette partie ne dit rien du comportement avec un utilisateur réel.
- Un seul projet, petit : le comportement avec un `SENSAI.md` proche de la
  limite de 8 000 caractères n'est vérifié que par les tests.
