"""Teste le rapport et la comparaison — feature [EV1], ADR-0019."""
import copy
import json
from datetime import UTC, datetime

import pytest

from sensai.core.ollama_client import OllamaError
from sensai.eval.dataset import Case, Dataset
from sensai.eval.judge import JudgePrompt
from sensai.eval.report import (
    SCHEMA_VERSION,
    ReportError,
    compare_reports,
    load_report,
    run_eval,
    write_json,
)
from sensai.eval.sources import Passage
from sensai.knowledge.rag import EmbeddingError

PROMPT = JudgePrompt("Q={{QUESTION}} P={{PASSAGES}} A={{ANSWER}}", "v1", "a" * 64)
JUDGE_INFO = {"model": "juge-test", "host": "http://h", "temperature": 0, "seed": 42}
SOURCES = ["f renvoie 1."]


def dataset(*cases):
    return Dataset(path="d.jsonl", sha256="d" * 64, cases=list(cases))


def case(id="c1", answer="f renvoie 1.", sources=SOURCES, question="Que fait f ?"):
    return Case(id=id, question=question, answer=answer, sources=list(sources))


def verdict_json(relevance, coherence, *verdicts):
    return json.dumps({
        "relevance": relevance,
        "coherence": coherence,
        "claims": [
            {"text": f"affirmation {n}", "verdict": v,
             "sources": ["S1"] if v != "UNVERIFIABLE" else [], "explanation": ""}
            for n, v in enumerate(verdicts)
        ],
    })


class FakeJudge:
    """Répond selon un mot de la question, pour des cas indépendants de l'ordre."""

    def __init__(self, by_question):
        self.by_question = by_question

    def __call__(self, messages):
        content = messages[0]["content"]
        for key, output in self.by_question.items():
            if f"Q={key} " in content:
                if isinstance(output, Exception):
                    raise output
                return output
        raise AssertionError(f"question inattendue : {content[:60]}")


def evaluate(cases, judge, **kwargs):
    return run_eval(
        dataset(*cases),
        judge_fn=judge,
        judge_info=JUDGE_INFO,
        prompt=PROMPT,
        now=lambda: datetime(2026, 10, 14, 12, 0, tzinfo=UTC),
        **kwargs,
    )


def test_rapport_complet_avec_metadonnees_et_agregats():
    judge = FakeJudge({
        "q1": verdict_json(5, 4, "SUPPORTED", "SUPPORTED"),
        "q2": verdict_json(3, 2, "SUPPORTED", "CONTRADICTED", "UNVERIFIABLE", "SUPPORTED"),
    })

    report = evaluate([case("c1", question="q1"), case("c2", question="q2")], judge)

    assert report["schema_version"] == SCHEMA_VERSION
    assert report["created_at"] == "2026-10-14T12:00:00+00:00"
    assert report["judge"] == {
        "model": "juge-test", "host": "http://h", "prompt_name": "judge",
        "prompt_version": "v1", "prompt_sha256": "a" * 64,
        "temperature": 0, "seed": 42, "max_retries": 2,
    }
    assert report["dataset"] == {"path": "d.jsonl", "sha256": "d" * 64, "n_cases": 2}
    assert report["sources_mode"] == "dataset" and report["generator"] is None
    assert "sensai_version" in report
    summary = report["summary"]
    assert summary["mean_relevance"] == 4.0 and summary["mean_coherence"] == 3.0
    assert summary["mean_faithfulness"] == 0.75  # (1.0 + 0.5) / 2
    assert summary["claims_total"] == 6 and summary["claims_flagged"] == 2
    assert summary["flagged_claim_rate"] == 0.3333
    first = report["cases"][0]
    assert first["status"] == "ok" and first["answer_origin"] == "dataset"
    assert first["passages"][0]["id"] == "S1"
    flagged = report["cases"][1]["flagged"]
    assert [c["verdict"] for c in flagged] == ["CONTRADICTED", "UNVERIFIABLE"]
    assert flagged[0]["citations"][0]["id"] == "S1"


def test_cas_en_erreur_exclus_des_moyennes_et_dénombrés_sans_note_zero():
    judge = FakeJudge({
        "q1": verdict_json(4, 4, "SUPPORTED"),
        "q2": "pas du JSON",
        "q3": OllamaError("hors ligne"),
    })

    report = evaluate(
        [case("c1", question="q1"), case("c2", question="q2"), case("c3", question="q3")], judge
    )

    summary = report["summary"]
    assert summary["n_cases"] == 3 and summary["n_scored"] == 1
    assert summary["judge_errors"] == 2
    assert summary["mean_relevance"] == 4.0  # pas 2.67 : les erreurs ne comptent pas comme 0
    failed = report["cases"][1]
    assert failed["status"] == "judge_error" and "scores" not in failed and failed["raw"]


def test_moyennes_nulles_quand_aucun_cas_n_est_juge():
    report = evaluate([case(question="q1")], FakeJudge({"q1": "non"}))

    summary = report["summary"]
    assert summary["n_scored"] == 0 and summary["judge_errors"] == 1
    assert summary["mean_relevance"] is None and summary["mean_faithfulness"] is None
    assert summary["flagged_claim_rate"] is None


def test_fidelite_nulle_sans_affirmation_exclue_de_la_moyenne():
    judge = FakeJudge({"q1": verdict_json(5, 5), "q2": verdict_json(4, 4, "SUPPORTED")})

    report = evaluate([case("c1", question="q1"), case("c2", question="q2")], judge)

    assert report["cases"][0]["scores"]["faithfulness"] is None
    assert report["summary"]["mean_faithfulness"] == 1.0
    assert report["summary"]["n_faithfulness"] == 1
    assert report["summary"]["mean_relevance"] == 4.5


def test_cas_sans_reponse_et_sans_generateur_est_ignore():
    never = FakeJudge({})

    report = evaluate([case(answer=None)], never)

    assert report["cases"][0]["status"] == "skipped"
    assert report["summary"]["skipped"] == 1 and report["summary"]["n_scored"] == 0


def test_generation_remplit_les_reponses_manquantes_et_enregistre_le_generateur():
    seen = []

    def answer_fn(question, passages):
        seen.append((question, [p.id for p in passages]))
        return "réponse générée"

    judge = FakeJudge({"q1": verdict_json(4, 4, "SUPPORTED")})
    generator = {"model": "agent", "host": "http://h", "system_prompt_version": "v1"}

    report = evaluate([case(answer=None, question="q1")], judge,
                      answer_fn=answer_fn, generator=generator)

    assert seen == [("q1", ["S1"])]
    assert report["generator"] == generator
    assert report["cases"][0]["answer"] == "réponse générée"
    assert report["cases"][0]["answer_origin"] == "generated"


def test_echec_de_generation_ne_plante_pas():
    def failing(question, passages):
        raise OllamaError("modèle absent")

    def empty(question, passages):
        return "  "

    judge = FakeJudge({})

    for answer_fn, reason in ((failing, "modèle absent"), (empty, "vide")):
        report = evaluate([case(answer=None)], judge, answer_fn=answer_fn)
        assert report["cases"][0]["status"] == "generation_error"
        assert reason in report["cases"][0]["error"]
        assert report["summary"]["generation_errors"] == 1


def test_mode_rag_interroge_le_fournisseur_avec_la_question():
    asked = []

    def provider(question):
        asked.append(question)
        return [Passage("S1", "src/a.py", "f renvoie 1.", 1, 3)]

    judge = FakeJudge({"q1": verdict_json(4, 4, "SUPPORTED")})

    report = evaluate([case(question="q1", sources=[])], judge,
                      sources_mode="rag", source_provider=provider)

    assert asked == ["q1"]
    assert report["sources_mode"] == "rag"
    assert report["cases"][0]["passages"][0]["source"] == "src/a.py"
    assert report["cases"][0]["claims"][0]["citations"][0]["start"] == 1


def test_mode_rag_en_erreur_de_recherche_marque_le_cas_sans_planter():
    def provider(question):
        raise EmbeddingError("Ollama injoignable")

    report = evaluate([case(question="q1")], FakeJudge({}),
                      sources_mode="rag", source_provider=provider)

    assert report["cases"][0]["status"] == "source_error"
    assert report["summary"]["source_errors"] == 1


def test_mode_rag_ne_cherche_pas_pour_un_cas_ignore():
    def provider(question):
        raise AssertionError("ne doit pas être appelé")

    report = evaluate([case(answer=None)], FakeJudge({}),
                      sources_mode="rag", source_provider=provider)

    assert report["cases"][0]["status"] == "skipped"


def test_sources_mode_inconnu_est_refuse():
    with pytest.raises(ValueError, match="sources_mode"):
        evaluate([case()], FakeJudge({}), sources_mode="web")


def test_ecriture_et_relecture_du_rapport(tmp_path):
    report = evaluate([case(question="q1")], FakeJudge({"q1": verdict_json(4, 4, "SUPPORTED")}))
    path = tmp_path / "sous" / "r.json"

    write_json(path, report)

    assert load_report(path) == report
    assert not list(path.parent.glob("*.tmp"))


@pytest.mark.parametrize("content", ["pas du json", "[1]", '{"summary": {}}'])
def test_rapport_illisible_est_refuse(tmp_path, content):
    path = tmp_path / "r.json"
    path.write_text(content, encoding="utf-8")

    with pytest.raises(ReportError):
        load_report(path)
    with pytest.raises(ReportError):
        load_report(tmp_path / "absent.json")


# --- comparaison -------------------------------------------------------------------------


def make_report(relevance, *verdicts, prompt_sha="a" * 64, model="juge-test", ids=("c1",)):
    judge = FakeJudge({"q": verdict_json(relevance, 4, *verdicts)})
    info = {**JUDGE_INFO, "model": model}
    report = run_eval(
        dataset(*[case(i, question="q") for i in ids]),
        judge_fn=judge,
        judge_info=info,
        prompt=JudgePrompt(PROMPT.text, "v1", prompt_sha),
    )
    return report


def test_comparaison_calcule_les_ecarts_b_moins_a():
    a = make_report(3, "SUPPORTED", "CONTRADICTED")
    b = make_report(5, "SUPPORTED", "SUPPORTED")

    result = compare_reports(a, b)

    assert result["comparable"] is True and result["warnings"] == []
    assert result["deltas"]["mean_relevance"] == {"a": 3.0, "b": 5.0, "delta": 2.0}
    assert result["deltas"]["mean_faithfulness"] == {"a": 0.5, "b": 1.0, "delta": 0.5}
    assert result["deltas"]["flagged_claim_rate"] == {"a": 0.5, "b": 0.0, "delta": -0.5}
    assert result["deltas"]["judge_errors"]["delta"] == 0
    [case_delta] = result["cases"]
    assert case_delta["id"] == "c1" and case_delta["relevance"]["delta"] == 2.0
    assert case_delta["flagged"] == {"a": 1, "b": 0, "delta": -1}


@pytest.mark.parametrize(("change", "label"), [
    ({"prompt_sha": "b" * 64}, "prompt du juge"),
    ({"model": "autre-juge"}, "modèle du juge"),
])
def test_comparaison_signale_un_juge_different_mais_calcule_quand_meme_les_ecarts(change, label):
    a = make_report(3, "SUPPORTED")
    b = make_report(4, "SUPPORTED", **change)

    result = compare_reports(a, b)

    assert result["comparable"] is False
    assert any(label in w for w in result["warnings"])
    assert result["deltas"]["mean_relevance"]["delta"] == 1.0


def test_comparaison_signale_un_jeu_de_donnees_ou_des_passages_differents():
    a = make_report(3, "SUPPORTED")
    b = copy.deepcopy(a)
    b["dataset"]["sha256"] = "e" * 64
    b["sources_mode"] = "rag"

    result = compare_reports(a, b)

    assert result["comparable"] is False
    assert len(result["warnings"]) == 2
    assert any("jeu de données" in w for w in result["warnings"])
    assert any("origine des passages" in w for w in result["warnings"])


def test_comparaison_ne_bloque_pas_sur_un_generateur_different():
    a = make_report(3, "SUPPORTED")
    b = copy.deepcopy(a)
    b["generator"] = {"model": "agent", "host": "h", "system_prompt_version": "v2"}

    assert compare_reports(a, b)["comparable"] is True


def test_comparaison_liste_les_cas_presents_d_un_seul_cote_et_garde_les_ecarts_des_autres():
    a = make_report(3, "SUPPORTED", ids=("c1", "c2"))
    b = make_report(4, "SUPPORTED", ids=("c2", "c3"))

    result = compare_reports(a, b)

    assert [c["id"] for c in result["cases"]] == ["c2"]
    assert result["only_in_a"] == ["c1"] and result["only_in_b"] == ["c3"]


def test_ecart_nul_quand_un_cote_n_a_aucun_cas_juge():
    a = make_report(3, "SUPPORTED")
    b = evaluate([case(question="q1")], FakeJudge({"q1": "non"}))
    b["judge"] = a["judge"]
    b["dataset"] = a["dataset"]

    result = compare_reports(a, b)

    assert result["deltas"]["mean_relevance"] == {"a": 3.0, "b": None, "delta": None}
    assert result["cases"][0]["status_b"] == "judge_error"
    assert result["cases"][0]["relevance"]["delta"] is None
    assert result["deltas"]["judge_errors"]["delta"] == 1
