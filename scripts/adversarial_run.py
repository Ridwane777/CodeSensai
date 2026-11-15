"""
Replays the adversarial corpus [EV4] and writes the results table.

No model, no network, no Docker: the same attacks as `tests/adversarial/`, from
the same source (`src/sensai/eval/adversarial.py`). The output is deterministic
(no date, no temporary path): rerunning the script on the same commit produces
exactly the same file.

Usage (from the repository root):
    python scripts/adversarial_run.py
    python scripts/adversarial_run.py --out /tmp/results.md

Exit code: 0 if no case outside the "known gaps" fails; 1 otherwise, including
when a known gap gets fixed (the FIXED verdict): the case must then be
reclassified, as the tests' strict xfail would require.
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
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="Markdown file to write")
    args = parser.parse_args(argv)

    # The defenses log their refusals (by design); here that noise would hide the summary.
    logging.disable(logging.CRITICAL)
    with tempfile.TemporaryDirectory(prefix="ev4-") as base:
        results = corpus.run_all(Path(base))

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(corpus.render_markdown(results), encoding="utf-8")

    bad = [r for r in results if r.verdict in (corpus.REGRESSION, corpus.FIXED)]
    for r in bad:
        print(f"{r.verdict}: {r.case.id} - observed {r.observed}, {r.detail}", file=sys.stderr)
    known = sum(r.verdict == corpus.KNOWN for r in results)
    print(f"{len(results)} cases, {known} known gaps, {len(bad)} to address -> {args.out}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
