"""
Rejoue le corpus adversarial [EV4] et écrit le tableau de résultats.

Aucun modèle, aucun réseau, aucun Docker : les mêmes attaques que
`tests/adversarial/`, sur la même source (`src/sensai/eval/adversarial.py`). La
sortie est déterministe (ni date, ni chemin temporaire) : relancer le script sur
le même commit redonne exactement le même fichier.

Usage (depuis la racine du dépôt) :
    python scripts/adversarial_run.py
    python scripts/adversarial_run.py --out /tmp/resultats.md

Code de sortie : 0 si aucun cas hors « écart connu » n'échoue ; 1 sinon, y compris
quand un écart connu est corrigé (verdict « ÉCART CORRIGÉ ») : le cas est alors à
reclasser, comme le ferait le xfail strict des tests.
"""

from __future__ import annotations

import argparse
import logging
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from sensai.eval import adversarial as corpus  # noqa: E402

DEFAULT_OUT = ROOT / "docs" / "performance" / "data" / "EV4-adversarial-results.md"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="fichier Markdown à écrire")
    args = parser.parse_args(argv)

    # Les défenses journalisent leurs refus (c'est voulu) ; ici ce bruit masquerait le résumé.
    logging.disable(logging.CRITICAL)
    with tempfile.TemporaryDirectory(prefix="ev4-") as base:
        results = corpus.run_all(Path(base))

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(corpus.render_markdown(results), encoding="utf-8")

    bad = [r for r in results if r.verdict in (corpus.REGRESSION, corpus.FIXED)]
    for r in bad:
        print(f"{r.verdict} : {r.case.id} — observé {r.observed}, {r.detail}", file=sys.stderr)
    known = sum(r.verdict == corpus.KNOWN for r in results)
    print(f"{len(results)} cas, {known} écarts connus, {len(bad)} à traiter -> {args.out}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
