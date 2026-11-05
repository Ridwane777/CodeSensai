"""
Teste la commande `sensai-prompt` de bout en bout — feature [A4], ADR-0010.

`test_dod_historique_puis_retour_en_arriere` rejoue la Definition of Done :
montrer l'historique des prompts, puis revenir à une ancienne version en une
commande.
"""
import pytest

from sensai import prompt_cli
from sensai.knowledge.prompt_versions import PromptStore


@pytest.fixture
def dossier(tmp_path):
    s = PromptStore(tmp_path)
    s.save("system", "Tu es CodeSensei.", "prompt initial", author="Alice", date="2026-09-28")
    s.save("system", "Tu es CodeSensei.\nSois concis.", "concision", author="Bob",
           date="2026-10-12")
    s.use("system", "v2")
    return tmp_path


def lancer(dossier, *args):
    return prompt_cli.main(["--dir", str(dossier), *args])


def test_dod_historique_puis_retour_en_arriere(dossier, capsys):
    assert lancer(dossier, "history", "system") == 0
    sortie = capsys.readouterr().out
    assert "v2" in sortie and "2026-10-12" in sortie and "Bob" in sortie
    assert "concision" in sortie and "active" in sortie

    assert lancer(dossier, "use", "system", "v1") == 0

    assert PromptStore(dossier).active("system") == "v1"
    assert "v1" in capsys.readouterr().out


def test_show_affiche_la_version_active_par_defaut(dossier, capsys):
    lancer(dossier, "show", "system")

    assert capsys.readouterr().out.strip() == "Tu es CodeSensei.\nSois concis."


def test_show_d_une_version_precise(dossier, capsys):
    lancer(dossier, "show", "system", "1")

    assert capsys.readouterr().out.strip() == "Tu es CodeSensei."


def test_diff(dossier, capsys):
    assert lancer(dossier, "diff", "system", "v1") == 0

    assert "+Sois concis." in capsys.readouterr().out


def test_save_depuis_un_fichier(dossier, tmp_path, capsys):
    brouillon = tmp_path / "brouillon.txt"
    brouillon.write_text("Tu es CodeSensei, en français.", encoding="utf-8")

    assert lancer(dossier, "save", "system", str(brouillon), "langue") == 0

    store = PromptStore(dossier)
    assert store.history("system")[0]["id"] == "v3"
    assert store.active("system") == "v2"
    sortie = capsys.readouterr().out
    assert "v3" in sortie and "use system v3" in sortie


def test_save_d_un_texte_identique_refuse(dossier, tmp_path, capsys):
    brouillon = tmp_path / "brouillon.txt"
    brouillon.write_text("Tu es CodeSensei.", encoding="utf-8")

    assert lancer(dossier, "save", "system", str(brouillon), "doublon") == 1
    assert "v1" in capsys.readouterr().err


def test_version_inconnue_message_clair(dossier, capsys):
    assert lancer(dossier, "use", "system", "v9") == 1
    assert "v9" in capsys.readouterr().err


def test_fichier_brouillon_absent(dossier, capsys):
    assert lancer(dossier, "save", "system", "nexiste_pas.txt", "x") == 1
    assert "nexiste_pas.txt" in capsys.readouterr().err


def test_check(dossier, capsys):
    assert lancer(dossier, "check") == 0

    (dossier / "system" / "v1.txt").write_text("modifié", encoding="utf-8")
    assert lancer(dossier, "check") == 1
    assert "system v1" in capsys.readouterr().err
