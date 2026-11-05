# Essais réels — [M1] Persistance de session & profils

Ce document garde la trace des vérifications de M1 faites avec de vrais
modèles, en plus des tests automatiques (`tests/knowledge/test_memory.py`,
`tests/test_cli_persistence.py`). Choix : [ADR-0007](../decisions/0007-persistance-des-sessions.md).

## Scénario

```
1. sensai                          /remember réponds en français et utilise pytest
                                   Je travaille sur un bug de login : test_login échoue
                                   avec une KeyError sur "token".
                                   exit
2. sensai                          (reprise attendue)  Tu te souviens de mon bug ?
                                   Quel test échouait, et avec quelle erreur ?
3. sensai --new-session            Écris un test pour une fonction add(a, b).
```

Ce qui est vérifié : la reprise de la session, l'usage réel de l'historique par
le modèle, l'application du profil dans une session vierge.

## Résultats

| Date | Modèle (machine) | Reprise | « Tu te souviens de mon bug ? » | « Quel test, quelle erreur ? » | Profil dans une nouvelle session |
|---|---|---|---|---|---|
| 2026-10-11 | `llama3` (poste de dev, CPU) | ✅ « reprise (2 messages) » | ❌ « Je n'ai pas de mémoire » | — | ✅ pytest, en français |
| 2026-10-11 | `granite3.1-moe` (poste de dev, CPU) | ✅ | ✅ cite le test et la KeyError | ⚠️ répond par un plan d'action | ✅ pytest, en français |
| 2026-10-12 | `qwen3-coder:30b` (pod RunPod, GPU), M1 au commit `9a9724e`, RAG désactivé | ✅ | ⚠️ « Je ne peux pas me souvenir des détails… mais je peux t'aider avec le `KeyError` sur "token" » | ✅ « `test_login` échouait avec une `KeyError` sur "token" » | ✅ test au format pytest |
| 2026-10-12 | `qwen3-coder:30b` (pod RunPod, GPU), avec la consigne de reprise | ✅ | ✅ « Oui, tu avais un bug de login où le test échouait avec une erreur `KeyError` sur "token"… » | ✅ même réponse exacte | — (dans une nouvelle session, à la même question : demande les détails, n'invente pas) |

Lors de l'essai du 2026-10-12, `/sessions` a listé les deux sessions du projet
avec titre, date et nombre de messages, et `sessions.db` comme `profile.json`
ont été créés en `600`.

## Ce que les essais ont changé

**Le réflexe « je n'ai pas de mémoire ».** Il existe sur `llama3` et aussi sur
le modèle de démonstration : `qwen3-coder:30b` niait se souvenir dans la phrase
même où il citait le bug de la session précédente. L'historique était pourtant
bien envoyé (le test `test_historique_conserve_apres_relance` vérifie ce que le
modèle reçoit). Correction : quand une session est reprise, une consigne lue
dans `prompts/memory_prompt.txt` (depuis A4 : `prompts/memory/v1.txt`) est ajoutée au prompt système (« les messages
qui suivent ont réellement eu lieu […] ne dis pas que tu n'as pas de
mémoire »). Elle n'est pas envoyée dans une session vierge, où elle serait
fausse ; le test `test_consigne_de_reprise_seulement_si_session_reprise` le
vérifie.

## Limites

- Un scénario, une exécution par modèle : ces essais montrent que le
  mécanisme fonctionne, pas un taux de réussite.
- Les cas d'erreur (base corrompue, disque plein, tour en échec non
  sauvegardé), les droits d'accès et la purge à 30 jours ne sont vérifiés que
  par les tests automatiques.
- `/sessions` affiche les dates en UTC, pas en heure locale.
