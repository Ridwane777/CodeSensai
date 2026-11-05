"""
Teste l'affichage du CLI (src/sensai/ui.py) sans terminal : les résumés
d'outils, les libellés, le diff numéroté et la consigne donnée après un refus.
Le rendu interactif (couleurs, animation, menu) se vérifie à la main.
"""
from rich.console import Console

from sensai import ui
from sensai.core.events import ToolCall


def rendu(renderable) -> str:
    console = Console(record=True, width=100, color_system=None)
    console.print(renderable)
    return console.export_text()


def test_resumes_utiles_plutot_que_la_premiere_ligne():
    assert ui.tool_summary("read_file", True, "a\nb\nc\nd") == "4 lignes lues"
    assert ui.tool_summary("write_file", True, "Created x.py (8 bytes).") == "Fichier créé"
    assert ui.tool_summary("write_file", True, "Replaced x.py (8 bytes).") == "Fichier modifié"
    resultats = "Results for: q\n1. A\n   u\n2. B"
    assert ui.tool_summary("web_search", True, resultats) == "2 résultat(s)"
    assert ui.tool_summary(
        "search_codebase", True, '[Recherche "q" : 5 passage(s) du projet.]') == \
        "5 passage(s) trouvé(s)"
    assert ui.tool_summary("recall_facts", True, "Faits trouvés :\n- a\n- b") == \
        "2 fait(s) trouvé(s)"


def test_un_echec_montre_le_message():
    assert ui.tool_summary("run_code", False, "Execution failed: NameError\nTrace") == \
        "Execution failed: NameError"


def test_libelles_lisibles():
    assert str(ui.tool_label(ToolCall(id="1", name="read_file",
                                      arguments={"path": "calcul.py"}))) == "Lecture(calcul.py)"
    assert str(ui.tool_label(ToolCall(id="2", name="run_code",
                                      arguments={"code": "print(1)\nprint(2)"}))) == \
        "Exécution(print(1))"
    assert str(ui.tool_label(ToolCall(id="3", name="outil_inconnu"))) == "outil_inconnu"


def test_diff_numerote_sans_en_tetes():
    diff = ("REPLACE calcul.py\n--- before\n+++ after\n@@ -1,2 +1,2 @@\n"
            " def moyenne(valeurs):\n-    return len(valeur)\n+    return len(valeurs)")

    texte = rendu(ui.diff_view(diff))

    assert "--- before" not in texte and "+++ after" not in texte
    assert "2 -    return len(valeur)" in texte
    assert "2 +    return len(valeurs)" in texte
    assert "1  def moyenne(valeurs):" in texte


def test_texte_sans_diff_affiche_tel_quel():
    assert "Retenir : auth" in rendu(ui.diff_view("Retenir : auth — port : 8080"))


def test_la_consigne_n_est_donnee_qu_une_fois(monkeypatch):
    monkeypatch.setattr(ui, "_pending_instruction", "utilise pytest plutôt")

    assert ui.take_instruction() == "utilise pytest plutôt"
    assert ui.take_instruction() is None


def test_un_appel_ecrit_en_texte_n_est_pas_affiche():
    reponse = "Je lis le fichier.\n<function=read_file>\n<parameter=path>\nx\n</parameter>"

    assert ui.visible_answer(reponse) == "Je lis le fichier."
    assert ui.visible_answer("<tool_call>\n<function=x>") == ""
    assert ui.visible_answer("Réponse normale.") == "Réponse normale."
