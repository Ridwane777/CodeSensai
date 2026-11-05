"""Teste la commande `sensai-eval` de bout en bout — feature [EV1], ADR-0019.

Le juge et le générateur sont des fonctions préparées : on teste la CLI, le
fichier qu'elle écrit et ses codes de sortie, pas Ollama.
"""
import json

import pytest

from sensai.eval import cli
from sensai.eval.cli import main

VALID = json.dumps({
    "relevance": 4,
    "coherence": 5,
    "claims": [
        {"text": "f renvoie 1", "verdict": "SUPPORTED", "sources": ["S1"], "explanation": "ok"},
        {"text": "f est rapide", "verdict": "UNVERIFIABLE", "sources": [], "explanation": ""},
    ],
})


@pytest.fixture
def dataset(tmp_path):
    path = tmp_path / "d.jsonl"
    path.write_text(
        json.dumps({"id": "c1", "question": "Que fait f ?", "answer": "f renvoie 1.",
                    "sources": ["f renvoie 1."]}, ensure_ascii=False) + "\n"
        + json.dumps({"id": "c2", "question": "Et g ?", "answer": "g aussi.",
                      "sources": []}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return path


@pytest.fixture
def fake_judge(monkeypatch):
    """Remplace `ollama_judge` ; `outputs` est ce que le juge répond, dans l'ordre."""
    state = {"outputs": [VALID, VALID], "calls": [], "built": [], "kwargs": []}

    def factory(host, model, *args, **kwargs):
        state["built"].append((host, model))
        state["kwargs"].append(kwargs)

        def judge(messages):
            state["calls"].append(messages)
            output = state["outputs"].pop(0)
            return output

        return judge

    monkeypatch.setattr(cli, "ollama_judge", factory)
    return state


def run(*args):
    return main(list(args))


def test_aide_de_chaque_commande(capsys):
    for argv in (["--help"], ["run", "--help"], ["compare", "--help"]):
        with pytest.raises(SystemExit) as stop:
            main(argv)
        assert stop.value.code == 0
        assert "usage: sensai-eval" in capsys.readouterr().out


def test_run_ecrit_un_rapport_complet_et_affiche_un_resume(tmp_path, dataset, fake_judge, capsys):
    out = tmp_path / "rapports" / "r.json"

    code = run("run", "--dataset", str(dataset), "--out", str(out), "--judge-model", "juge-x",
               "--host", "http://hote:1234")

    assert code == 0
    assert fake_judge["built"] == [("http://hote:1234", "juge-x")]
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["judge"]["model"] == "juge-x"
    assert report["judge"]["host"] == "http://hote:1234"
    assert report["judge"]["prompt_name"] == "judge"
    assert report["judge"]["prompt_version"] == "v1"
    assert len(report["judge"]["prompt_sha256"]) == 64
    assert report["judge"]["temperature"] == 0 and report["judge"]["seed"] == 42
    assert report["dataset"]["n_cases"] == 2 and len(report["dataset"]["sha256"]) == 64
    assert report["sources_mode"] == "dataset" and report["generator"] is None
    first = report["cases"][0]
    assert first["scores"] == {"relevance": 4, "coherence": 5, "faithfulness": 0.5}
    assert first["claims"][0]["verdict"] == "SUPPORTED" and first["claims"][0]["sources"] == ["S1"]
    assert [c["text"] for c in first["flagged"]] == ["f est rapide"]
    # Le 2e cas n'a aucun passage : « SUPPORTED, S1 » est une citation invalide, dégradée.
    second = report["cases"][1]
    assert second["claims"][0]["verdict"] == "UNVERIFIABLE"
    assert "citation_invalide" in second["claims"][0]["flags"]
    sortie = capsys.readouterr().out
    assert "2 jugé(s)" in sortie and "estimations" in sortie and str(out) in sortie


def test_run_judge_malforme_en_continu_est_compte_sans_planter(
    tmp_path, dataset, fake_judge, capsys
):
    fake_judge["outputs"] = [VALID, "n'importe quoi", "encore", "toujours"]
    out = tmp_path / "r.json"

    code = run("run", "--dataset", str(dataset), "--out", str(out))

    assert code == 0
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["summary"]["judge_errors"] == 1 and report["summary"]["n_scored"] == 1
    assert report["cases"][1]["status"] == "judge_error"
    assert "c2 : judge_error" in capsys.readouterr().out


def test_run_prompt_du_juge_inconnu_sort_en_erreur(tmp_path, dataset, fake_judge, capsys):
    code = run("run", "--dataset", str(dataset), "--out", str(tmp_path / "r.json"),
               "--judge-prompt-version", "v99")

    assert code == 2
    assert "prompt du juge introuvable" in capsys.readouterr().err
    assert not (tmp_path / "r.json").exists()


def test_run_jeu_de_donnees_invalide_nomme_la_ligne(tmp_path, fake_judge, capsys):
    bad = tmp_path / "bad.jsonl"
    bad.write_text('{"id": "a", "question": "Q"}\n{"id": "a", "question": "Q"}\n', encoding="utf-8")

    code = run("run", "--dataset", str(bad), "--out", str(tmp_path / "r.json"))

    assert code == 2
    assert "ligne 2" in capsys.readouterr().err


def test_run_generate_remplit_les_reponses_manquantes(tmp_path, fake_judge, monkeypatch):
    path = tmp_path / "d.jsonl"
    path.write_text(json.dumps({"id": "c1", "question": "Que fait f ?",
                                "sources": ["f renvoie 1."]}) + "\n", encoding="utf-8")
    sent = []

    def fake_stream(host, model, messages, num_ctx=None):
        sent.append((host, model, messages))
        yield "f renvoie "
        yield "1."

    monkeypatch.setattr(cli, "stream_chat", fake_stream)
    fake_judge["outputs"] = [VALID]
    out = tmp_path / "r.json"

    code = run("run", "--dataset", str(path), "--out", str(out), "--generate")

    assert code == 0
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["cases"][0]["answer"] == "f renvoie 1."
    assert report["cases"][0]["answer_origin"] == "generated"
    assert report["generator"]["model"] and report["generator"]["system_prompt_version"]
    messages = sent[0][2]
    assert messages[0]["role"] == "system"
    assert "[S1] dataset" in messages[-1]["content"] and "Que fait f ?" in messages[-1]["content"]


def test_run_sans_reponse_ni_generate_ignore_le_cas(tmp_path, fake_judge):
    path = tmp_path / "d.jsonl"
    path.write_text(json.dumps({"id": "c1", "question": "Q ?"}) + "\n", encoding="utf-8")
    out = tmp_path / "r.json"

    assert run("run", "--dataset", str(path), "--out", str(out)) == 0

    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["cases"][0]["status"] == "skipped" and fake_judge["calls"] == []


def test_run_sources_rag_utilise_le_fournisseur_de_l_index(tmp_path, dataset, fake_judge,
                                                             monkeypatch):
    from sensai.eval.sources import Passage

    monkeypatch.setattr(
        cli, "build_rag_provider",
        lambda host, config: lambda question: [Passage("S1", "src/a.py", "f renvoie 1.", 1, 3)],
    )
    out = tmp_path / "r.json"

    assert run("run", "--dataset", str(dataset), "--out", str(out), "--sources", "rag") == 0

    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["sources_mode"] == "rag"
    assert report["cases"][1]["claims"][0]["verdict"] == "SUPPORTED"  # S1 existe cette fois


# --- compare ------------------------------------------------------------------------


@pytest.fixture
def two_reports(tmp_path, dataset, fake_judge):
    paths = []
    for name, relevance in (("a", 3), ("b", 5)):
        out = tmp_path / f"{name}.json"
        fake_judge["outputs"] = [VALID.replace('"relevance": 4', f'"relevance": {relevance}')] * 2
        assert run("run", "--dataset", str(dataset), "--out", str(out)) == 0
        paths.append(out)
    return paths


def test_compare_affiche_les_ecarts_et_ecrit_le_json(two_reports, tmp_path, capsys):
    a, b = two_reports
    capsys.readouterr()

    code = run("compare", str(a), str(b), "--out", str(tmp_path / "diff.json"), "--strict")

    assert code == 0
    sortie = capsys.readouterr().out
    assert "comparables" in sortie and "+2.00" in sortie
    diff = json.loads((tmp_path / "diff.json").read_text(encoding="utf-8"))
    assert diff["comparable"] is True
    assert diff["deltas"]["mean_relevance"]["delta"] == 2.0


def test_compare_non_comparable_sort_en_0_mais_en_1_avec_strict(two_reports, capsys):
    a, b = two_reports
    report = json.loads(b.read_text(encoding="utf-8"))
    report["judge"]["prompt_sha256"] = "0" * 64
    b.write_text(json.dumps(report), encoding="utf-8")
    capsys.readouterr()

    assert run("compare", str(a), str(b)) == 0
    sortie = capsys.readouterr().out
    assert "NON comparables" in sortie and "prompt du juge" in sortie
    assert run("compare", str(a), str(b), "--strict") == 1


def test_compare_rapport_illisible(tmp_path, capsys):
    bad = tmp_path / "bad.json"
    bad.write_text("pas du json", encoding="utf-8")

    assert run("compare", str(bad), str(bad)) == 2
    assert "JSON" in capsys.readouterr().err


def test_build_rag_provider_reutilise_open_rag_index_du_cli(monkeypatch):
    import sensai.cli as interactive_cli

    class Index:
        def search(self, query, top_k, min_score):
            return [{"source": "a.py", "start": 1, "end": 2, "text": "t", "score": 0.9,
                     "seen": (top_k, min_score)}]

    opened = []

    def fake_open(settings, data_dir, project):
        opened.append((settings, project))
        return Index()

    monkeypatch.setattr(interactive_cli, "open_rag_index", fake_open)

    provider = cli.build_rag_provider("http://h", {"rag_model": "m", "rag_top_k": 2})

    assert opened[0][0] == {"host": "http://h", "rag_model": "m"}
    assert provider("q")[0].source == "a.py"


def test_run_envoie_num_ctx_au_juge_et_au_generateur(tmp_path, fake_judge, monkeypatch):
    """Revue PR #97 : `sensai-eval` oubliait `num_ctx`, donc le juge et le
    générateur restaient soumis à la troncature par défaut d'Ollama."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.json").write_text('{"num_ctx": 4096}', encoding="utf-8")
    path = tmp_path / "d.jsonl"
    path.write_text(json.dumps({"id": "c1", "question": "Q ?", "sources": ["s."]}) + "\n",
                    encoding="utf-8")
    vus = []

    def fake_stream(host, model, messages, num_ctx=None):
        vus.append(num_ctx)
        yield "réponse"

    monkeypatch.setattr(cli, "stream_chat", fake_stream)
    fake_judge["outputs"] = [VALID]

    code = run("run", "--dataset", str(path), "--out", str(tmp_path / "r.json"), "--generate")

    assert code == 0
    assert vus == [4096]
    assert fake_judge["kwargs"][0]["num_ctx"] == 4096


def test_run_num_ctx_invalide_dans_la_config_sort_en_erreur(
    tmp_path, dataset, fake_judge, monkeypatch, capsys
):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.json").write_text('{"num_ctx": "grand"}', encoding="utf-8")
    code = run("run", "--dataset", str(dataset), "--out", str(tmp_path / "r.json"))
    assert code == 2
    assert "num_ctx" in capsys.readouterr().err
