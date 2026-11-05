"""Le texte enregistré d'une réponse.

Essai réel du 2026-11-01 : morceaux collés, réponse réécrite.
"""
from sensai.core.answer import AnswerBuilder


def build(*parts):
    b = AnswerBuilder()
    for p in parts:
        if p is None:
            b.tool_boundary()
        else:
            b.add(p)
    return b.text()


def test_un_seul_morceau_reste_tel_quel():
    assert build("Bon", "jour.") == "Bonjour."


def test_les_morceaux_separes_par_un_outil_deviennent_des_paragraphes():
    assert build("Je lis le fichier.", None, "Le fichier contient deux lignes.") == \
        "Je lis le fichier.\n\nLe fichier contient deux lignes."


def test_une_reponse_reecrite_apres_un_outil_n_apparait_qu_une_fois():
    answer = "Le fichier deploiement.txt indique la région eu-west-3."
    assert build(answer, None, answer + " Aucun fait enregistré.") == \
        answer + " Aucun fait enregistré."


def test_un_debut_court_identique_n_est_pas_pris_pour_une_repetition():
    assert build("D'accord.", None, "D'accord. Voici la suite.") == \
        "D'accord.\n\nD'accord. Voici la suite."


def test_rien_que_des_outils_donne_une_reponse_vide():
    assert build(None, None) == ""


def test_une_balise_tool_call_vide_est_retiree_du_texte_enregistre():
    assert build("La tâche est planifiée.<tool_call>") == "La tâche est planifiée."


def test_une_reponse_reformulee_apres_un_outil_n_apparait_qu_une_fois():
    """Essai réel du 2026-11-01 après-midi : même phrase, un verbe changé."""
    first = "The function `moyenne` is located in the file `stats.py`, starting at line 4."
    second = "The function `moyenne` is defined in the file `stats.py`, starting at line 4."
    assert build(first, None, second) == second


def test_une_annonce_avant_l_outil_n_est_pas_prise_pour_une_reformulation():
    assert build("Je vais lire le fichier stats.py pour vérifier.", None,
                 "La fonction moyenne divise la somme des notes par leur nombre.") == \
        "Je vais lire le fichier stats.py pour vérifier.\n\n" \
        "La fonction moyenne divise la somme des notes par leur nombre."
