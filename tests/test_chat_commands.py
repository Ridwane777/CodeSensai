"""/schedule et /eval dans le chat (ADR-0028).

Les premiers tests font tourner le vrai `sensai-schedule` (aucun modèle n'est
nécessaire pour ajouter, lister ou simuler). Ceux de `/eval` vérifient ce qui
est transmis, car un vrai jugement demande Ollama.
"""
import builtins

import pytest

from sensai import cli
from sensai.chat_commands import is_chat_command, run_chat_command


@pytest.fixture
def sortie():
    lignes = []
    return lignes


def _lancer(line, tmp_path, lignes, **kwargs):
    return run_chat_command(
        line, host="http://h:1", model="m1", data_dir=str(tmp_path), output_fn=lignes.append,
        **kwargs,
    )


@pytest.mark.parametrize("line", ["/schedule list", "/eval run", "/schedule"])
def test_les_lignes_qui_commencent_par_la_commande_sont_reconnues(line):
    assert is_chat_command(line)


@pytest.mark.parametrize(
    "line", ["pourquoi /eval échoue ?", "/profile", "bonjour", "", "/scheduler list"]
)
def test_une_question_ou_une_autre_commande_n_est_pas_interceptee(line):
    assert not is_chat_command(line)


def test_schedule_ajoute_puis_liste_une_tache(tmp_path, capsys, sortie):
    ajout = '/schedule add resume --every 1d --prompt "Résume le journal"'
    assert _lancer(ajout, tmp_path, sortie) == 0
    assert _lancer("/schedule list", tmp_path, sortie) == 0

    sortie_ecran = capsys.readouterr().out
    assert "resume" in sortie_ecran and "1d" in sortie_ecran
    assert (tmp_path / "schedule").is_dir(), "le dossier de données de la session est utilisé"


def test_schedule_loop_est_refuse_car_il_figerait_le_chat(tmp_path, sortie):
    appels = []
    code = _lancer("/schedule loop", tmp_path, sortie, schedule=lambda argv: appels.append(argv))

    assert code == 2 and appels == []
    assert "autre terminal" in sortie[0]


def test_schedule_recoit_le_dossier_l_hote_et_le_modele_de_la_session(tmp_path, sortie):
    recu = []
    _lancer("/schedule list", tmp_path, sortie, schedule=lambda argv: recu.append(list(argv)) or 0)

    argv = recu[0]
    assert argv[argv.index("--data-dir") + 1] == str(tmp_path)
    assert argv[argv.index("--host") + 1] == "http://h:1"
    assert argv[argv.index("--model") + 1] == "m1"
    assert argv[-1] == "list"


def test_une_option_donnee_par_l_utilisateur_n_est_pas_ecrasee(tmp_path, sortie):
    recu = []
    _lancer(
        "/schedule --model autre list", tmp_path, sortie,
        schedule=lambda argv: recu.append(list(argv)) or 0,
    )

    assert recu[0].count("--model") == 1 and "autre" in recu[0]


def test_eval_run_recoit_l_hote_et_le_juge_de_la_session(tmp_path, sortie):
    recu = []
    _lancer(
        "/eval run --dataset d.jsonl --out r.json", tmp_path, sortie,
        evaluate=lambda argv: recu.append(list(argv)) or 0,
    )

    argv = recu[0]
    assert argv[argv.index("--judge-model") + 1] == "m1"
    assert argv[argv.index("--host") + 1] == "http://h:1"
    assert argv[argv.index("--dataset") + 1] == "d.jsonl"


def test_eval_compare_n_ajoute_aucun_modele(tmp_path, sortie):
    recu = []
    _lancer("/eval compare a.json b.json", tmp_path, sortie,
            evaluate=lambda argv: recu.append(list(argv)) or 0)

    assert recu[0] == ["compare", "a.json", "b.json"]


@pytest.mark.parametrize("line", ["/schedule", "/eval"])
def test_sans_argument_la_commande_affiche_son_usage(line, tmp_path, sortie):
    assert _lancer(line, tmp_path, sortie) == 2
    assert sortie[0].startswith("Usage")


def test_un_guillemet_non_ferme_est_une_erreur_lisible(tmp_path, sortie):
    assert _lancer('/schedule add x --prompt "oups', tmp_path, sortie) == 2
    assert "illisible" in sortie[0]


def test_une_option_inconnue_ne_ferme_pas_le_chat(tmp_path, sortie, capsys):
    assert _lancer("/schedule add --nope", tmp_path, sortie) == 2
    assert "usage" in capsys.readouterr().err.lower()


def test_un_outil_en_panne_ne_ferme_pas_le_chat(tmp_path, sortie):
    def panne(argv):
        raise RuntimeError("boom")

    assert _lancer("/eval run --dataset d --out o", tmp_path, sortie, evaluate=panne) == 1
    assert "boom" in sortie[0]


def test_dans_le_vrai_cli_la_commande_ne_part_pas_au_modele(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    settings = {
        "model": "faux", "host": "http://localhost:11434", "system_prompt": "S.",
        "session": None, "new_session": False, "data_dir": str(tmp_path / "donnees"),
        "retention_days": 30, "rag": False, "rag_model": "bge-m3",
        "rag_min_score": 0.0, "rag_top_k": 3,
    }
    envoyes = []

    def faux_stream_chat(host, model, messages):
        envoyes.append(messages)
        yield "ok"

    entrees = iter(['/schedule add t1 --every 1h --prompt "x"', "/schedule list", "Bonjour"])

    def faux_input(_=""):
        try:
            return next(entrees)
        except StopIteration:
            raise EOFError from None

    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    monkeypatch.setattr(cli, "stream_chat", faux_stream_chat)
    monkeypatch.setattr(builtins, "input", faux_input)
    cli.main()

    assert len(envoyes) == 1, "seul « Bonjour » atteint le modèle"
    assert all("/schedule" not in m["content"] for m in envoyes[0])
    assert "t1" in capsys.readouterr().out
    assert (tmp_path / "donnees" / "schedule" / "tasks.json").exists()
