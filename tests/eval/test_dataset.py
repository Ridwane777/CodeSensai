"""Teste la lecture du jeu de données JSONL — feature [EV1], ADR-0019."""
import hashlib
import json
import re
from pathlib import Path

import pytest

from sensai.eval.dataset import DatasetError, load_dataset

SAMPLE = Path(__file__).resolve().parents[2] / "datasets" / "eval" / "ev1_sample.jsonl"


def write(tmp_path, *lines):
    path = tmp_path / "d.jsonl"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def line(**fields):
    return json.dumps({"id": "a", "question": "Q ?", **fields}, ensure_ascii=False)


def test_lecture_minimale_et_empreinte_du_fichier(tmp_path):
    path = write(tmp_path, line(), "", line(id="b", answer="R", notes="n",
                                            sources=["t", {"source": "f.py", "text": "x"}]))

    dataset = load_dataset(path)

    assert [c.id for c in dataset.cases] == ["a", "b"]
    assert dataset.cases[0].answer is None and dataset.cases[0].sources == []
    assert dataset.cases[1].sources == ["t", {"source": "f.py", "text": "x"}]
    assert dataset.sha256 == hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.parametrize(("lines", "expected"), [
    (['{"id": "a", "question": "Q"', ], "ligne 1 : JSON invalide"),
    ([line(), "[1]"], "ligne 2 : chaque ligne doit être un objet"),
    ([line(), "", json.dumps({"question": "Q"})], "ligne 3 : « id » est obligatoire"),
    ([json.dumps({"id": "a"})], "ligne 1 : « question » est obligatoire"),
    ([json.dumps({"id": "a", "question": "  "})], "ligne 1 : « question » ne doit pas être vide"),
    ([line(), line()], "ligne 2 : id « a » déjà utilisé à la ligne 1"),
    ([line(anwser="faute de frappe")], "ligne 1 : clé inconnue anwser"),
    ([line(answer=3)], "ligne 1 : « answer » doit être une chaîne"),
    ([line(sources="texte")], "ligne 1 : « sources » doit être une liste"),
    ([line(sources=[3])], "ligne 1 : sources[1] doit être"),
    ([line(sources=[{"source": "f.py"}])], "ligne 1 : sources[1] doit être"),
])
def test_erreurs_nommant_la_ligne(tmp_path, lines, expected):
    with pytest.raises(DatasetError, match=re.escape(expected)):
        load_dataset(write(tmp_path, *lines))


def test_fichier_absent_ou_vide(tmp_path):
    with pytest.raises(DatasetError, match="illisible"):
        load_dataset(tmp_path / "absent.jsonl")
    with pytest.raises(DatasetError, match="vide"):
        load_dataset(write(tmp_path, "", ""))


def test_le_jeu_d_exemple_se_charge_et_couvre_les_cinq_situations():
    dataset = load_dataset(SAMPLE)

    assert len(dataset.cases) >= 5
    assert all(c.answer for c in dataset.cases)
    # Au moins un cas sans aucun passage : le juge doit alors tout déclarer invérifiable.
    assert any(not c.sources for c in dataset.cases)
    assert {"fidele", "contredit", "inverifiable", "hors-sujet", "sans-source"} <= {
        c.id for c in dataset.cases
    }
