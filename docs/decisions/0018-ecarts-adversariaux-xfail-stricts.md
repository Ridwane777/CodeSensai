# ADR-0018 — Tests adversariaux : les écarts connus sont des échecs attendus stricts

- **Statut** : Accepté (2026-11-01, validé par l'équipe)
- **Date** : 2026-10-14
- **Décideurs** : Méric (Lot B) ; en attente de relecture de l'équipe
- **Lot concerné** : B (défenses testées) ; A (boucle de l'agent) ; D (interface web) : les écarts OUT-14/15 et PERM-15/16 touchent leur code

## Contexte
[EV4] demande de tester les défenses face à des attaques. Le premier corpus
(`tests/adversarial/`, [rapport](../securite/EV4-tests-adversariaux.md)) a trouvé
des attaques qui passent aujourd'hui : 21 sur 85. Il faut décider quoi faire de
ces cas : les supprimer pour garder une CI verte, les laisser en échec, ou les
garder visibles sans casser le travail des autres lots.

## Options envisagées
| Option | Pour | Contre |
| --- | --- | --- |
| A. Cas en échec « normal » (rouge) | Honnête, impossible à oublier | Bloque la CI et les PR des autres lots pour des écarts que le Lot B n'a pas tous le droit de corriger (`agent.py`, `cli.py`) |
| B. Supprimer ou affaiblir les cas qui échouent | CI verte | Cache les faiblesses : c'est l'inverse du but d'EV4 |
| C. `xfail(strict=True)` qui affirme le comportement **sûr**, cause et fichier:ligne dans la raison | CI verte, écart visible à chaque exécution, et le test casse (XPASS) le jour où le trou est comblé : on doit reclasser | Un `xfail` se banalise : il faut lire la liste |
| D. Fichier d'écarts à part, hors des tests | Aucun bruit | Dérive garantie entre le fichier et le code |

## Décision
Option C. Chaque écart connu est un cas du corpus avec `secure` (l'issue d'une
défense corrigée) et `gap` (la cause avec fichier:ligne). Le tableau généré
(`docs/performance/data/EV4-adversarial-results.md`) est versionné et vérifié
par un test, ainsi que sa copie dans le rapport.

Deux familles sont déclarées **hors périmètre** de la détection : un secret ou
une instruction encodés en base64, et les homoglyphes d'autres écritures
(INJ-05, 06, EXF-07, 08). Les motifs ne peuvent pas les couvrir ; la parade est
la confirmation lisible, la sandbox sans réseau et `confirm_after_untrusted`
(déjà dit dans `docs/architecture/tool-contract.md`). Ces cas restent dans le corpus,
marqués comme écarts connus.

## Conséquences
- ✅ Les faiblesses restent visibles à chaque exécution et ne bloquent pas les autres lots.
- ✅ Corriger un écart sans reclasser son cas casse la CI : le rapport ne peut pas mentir en silence.
- ❌ 21 `xfail` dans la suite : on peut s'habituer à les voir. Le rapport classe les écarts par gravité pour éviter cela.
- ❌ Déclarer base64 et homoglyphes hors périmètre accepte un contournement connu de la détection ; seule la défense en profondeur (confirmation, sandbox) le limite.
- ❌ Les numéros de ligne cités dans les raisons glissent quand le code change ; un test ne vérifie que l'existence du fichier et de la ligne, pas son sens.
- Suivi : à revoir quand la CLI branche les garde-fous (OUT-15) ou quand un outil ouvre des liens (NET-08, devient bloquant). Corriger un écart = passer son cas en OK dans `corpus.py` et régénérer le tableau.
