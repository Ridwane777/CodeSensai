"""
Teste le juge LLM — feature [EV1], ADR-0019.

Le juge est remplacé par des fonctions qui renvoient du texte préparé : aucun
test ne parle à Ollama. Ce qu'on vérifie, c'est tout ce que le code fait de la
sortie du modèle (validation, relances, calcul de la fidélité).
"""
import json

import pytest
import requests

from sensai.config import prompts_dir
from sensai.core.ollama_client import OllamaError
from sensai.eval import judge as judge_module
from sensai.eval.judge import (
    JudgeOutputError,
    build_messages,
    faithfulness,
    judge_case,
    load_judge_prompt,
    ollama_judge,
    parse_judgment,
)
from sensai.eval.sources import Passage
from sensai.knowledge.prompt_versions import PromptStore

PASSAGES = [Passage("S1", "src/a.py", "f renvoie 1.", 1, 3), Passage("S2", "docs/b.md", "g.")]
IDS = {"S1", "S2"}


def judgment(**override):
    data = {
        "relevance": 4,
        "coherence": 5,
        "claims": [
            {"text": "f renvoie 1", "verdict": "SUPPORTED", "sources": ["S1"], "explanation": "ok"}
        ],
    }
    data.update(override)
    return data


def raw(**override):
    return json.dumps(judgment(**override))


# --- le prompt rangé dans le registre ---------------------------------------------


def test_le_prompt_du_juge_est_range_et_le_registre_reste_coherent():
    store = PromptStore(prompts_dir())

    assert store.check() == []
    prompt = load_judge_prompt(store)
    assert prompt.version == store.active("judge")
    assert len(prompt.sha256) == 64
    for token in ("{{QUESTION}}", "{{PASSAGES}}", "{{ANSWER}}"):
        assert token in prompt.text


def test_version_inconnue_du_prompt_leve_keyerror():
    with pytest.raises(KeyError):
        load_judge_prompt(PromptStore(prompts_dir()), "v99")


def test_build_messages_remplit_les_jetons_sans_reinterpreter_les_accolades():
    prompt = 'Q={{QUESTION}} P={{PASSAGES}} A={{ANSWER}} {"relevance": 1}'

    [message] = build_messages(prompt, "q {{ANSWER}}", "réponse {x}", PASSAGES)

    assert message["role"] == "user"
    # La question contient un jeton : il reste tel quel, il n'est pas remplacé à son tour.
    assert message["content"].startswith("Q=q {{ANSWER}} P=[S1] src/a.py:1-3\nf renvoie 1.")
    assert message["content"].endswith('A=réponse {x} {"relevance": 1}')


# --- analyse de la sortie ------------------------------------------------------------


def test_parse_judgment_valide():
    result = parse_judgment(raw(), IDS)

    assert result["relevance"] == 4 and result["coherence"] == 5
    assert result["claims"][0]["verdict"] == "SUPPORTED"
    assert result["claims"][0]["flags"] == []


def test_parse_judgment_accepte_les_blocs_de_code_et_le_texte_autour():
    wrapped = f"Voici mon évaluation :\n```json\n{raw()}\n```\nJ'espère que ça aide."

    assert parse_judgment(wrapped, IDS)["relevance"] == 4
    assert parse_judgment(f"```\n{raw()}\n```", IDS)["coherence"] == 5


def test_parse_judgment_normalise_la_casse_du_verdict():
    result = parse_judgment(
        raw(claims=[{"text": "x", "verdict": " unverifiable ", "sources": []}]), IDS
    )

    assert result["claims"][0]["verdict"] == "UNVERIFIABLE"


@pytest.mark.parametrize("bad", [
    "pas de JSON du tout",
    '{"relevance": 4, "coherence": ',
    "[1, 2, 3]",
])
def test_parse_judgment_refuse_un_json_invalide(bad):
    with pytest.raises(JudgeOutputError):
        parse_judgment(bad, IDS)


@pytest.mark.parametrize("override", [
    {"relevance": 0},
    {"relevance": 6},
    {"coherence": "5"},
    {"coherence": 4.5},
    {"relevance": True},
    {"relevance": None},
    {"claims": "aucune"},
    {"claims": [{"text": "x", "verdict": "PEUT-ETRE", "sources": []}]},
    {"claims": [{"verdict": "SUPPORTED", "sources": ["S1"]}]},
    {"claims": ["pas un objet"]},
    {"claims": [{"text": "x", "verdict": "SUPPORTED", "sources": "S1"}]},
])
def test_parse_judgment_refuse_un_schema_ou_des_valeurs_invalides(override):
    with pytest.raises(JudgeOutputError):
        parse_judgment(raw(**override), IDS)


def test_parse_judgment_exige_les_deux_notes_et_la_liste_d_affirmations():
    data = judgment()
    del data["claims"]
    with pytest.raises(JudgeOutputError):
        parse_judgment(json.dumps(data), IDS)


@pytest.mark.parametrize("sources", [[], ["S9"], ["S1", "S9"]])
@pytest.mark.parametrize("verdict", ["SUPPORTED", "CONTRADICTED"])
def test_citation_invalide_degrade_le_verdict_en_unverifiable(verdict, sources):
    claims = [{"text": "x", "verdict": verdict, "sources": sources, "explanation": ""}]

    claim = parse_judgment(raw(claims=claims), IDS)["claims"][0]

    assert claim["verdict"] == "UNVERIFIABLE"
    assert claim["verdict_original"] == verdict
    assert "citation_invalide" in claim["flags"]


def test_unverifiable_sans_source_n_est_pas_une_citation_invalide():
    claims = [{"text": "x", "verdict": "UNVERIFIABLE", "sources": []}]

    claim = parse_judgment(raw(claims=claims), IDS)["claims"][0]

    assert claim["verdict"] == "UNVERIFIABLE" and claim["flags"] == []
    assert "verdict_original" not in claim


# --- fidélité -----------------------------------------------------------------------


def claim(verdict):
    return {"verdict": verdict}


def test_faithfulness_est_la_part_d_affirmations_soutenues():
    claims = [claim("SUPPORTED"), claim("SUPPORTED"), claim("CONTRADICTED"), claim("UNVERIFIABLE")]

    assert faithfulness(claims) == 0.5
    assert faithfulness([claim("SUPPORTED")]) == 1.0
    assert faithfulness([claim("UNVERIFIABLE")]) == 0.0
    assert faithfulness([claim("SUPPORTED")] + [claim("CONTRADICTED")] * 2) == 0.3333


def test_faithfulness_est_nulle_sans_affirmation():
    assert faithfulness([]) is None


# --- un cas : relances et erreurs ----------------------------------------------------


class ScriptedJudge:
    """Renvoie les sorties dans l'ordre et garde les messages reçus."""

    def __init__(self, *outputs):
        self.outputs = list(outputs)
        self.calls = []

    def __call__(self, messages):
        self.calls.append(messages)
        output = self.outputs.pop(0)
        if isinstance(output, Exception):
            raise output
        return output


def run_case(fn, max_retries=2, passages=PASSAGES):
    return judge_case("Que fait f ?", "f renvoie 1.", passages, fn, "Q={{QUESTION}}", max_retries)


def test_judge_case_reussi_calcule_les_scores_les_citations_et_les_cas_signales():
    claims = [
        {"text": "f renvoie 1", "verdict": "SUPPORTED", "sources": ["S1"], "explanation": ""},
        {"text": "f est lente", "verdict": "UNVERIFIABLE", "sources": [], "explanation": ""},
    ]

    result = run_case(ScriptedJudge(raw(claims=claims)))

    assert result["status"] == "ok" and result["attempts"] == 1
    assert result["scores"] == {"relevance": 4, "coherence": 5, "faithfulness": 0.5}
    assert result["claims"][0]["citations"] == [
        {"id": "S1", "source": "src/a.py", "start": 1, "end": 3}
    ]
    assert [c["text"] for c in result["flagged"]] == ["f est lente"]


def test_sortie_malformee_puis_valide_est_relancee_avec_un_message_correctif():
    fn = ScriptedJudge("désolé, voici mon avis : plutôt bien", raw())

    result = run_case(fn)

    assert result["status"] == "ok" and result["attempts"] == 2
    second = fn.calls[1]
    assert second[-2] == {"role": "assistant", "content": "désolé, voici mon avis : plutôt bien"}
    assert second[-1]["role"] == "user" and "JSON" in second[-1]["content"]
    # Le premier appel n'a pas été modifié après coup.
    assert len(fn.calls[0]) == 1


def test_sortie_malformee_en_continu_donne_judge_error_apres_les_relances():
    fn = ScriptedJudge("x" * 5000, "non", "toujours non")

    result = run_case(fn, max_retries=2)

    assert result["status"] == "judge_error"
    assert result["attempts"] == 3 and len(fn.calls) == 3
    assert "error" in result and result["raw"] == "toujours non"
    assert "scores" not in result


def test_le_texte_brut_conserve_est_tronque():
    result = run_case(ScriptedJudge("x" * 5000), max_retries=0)

    assert result["status"] == "judge_error"
    assert len(result["raw"]) == judge_module.RAW_MAX_CHARS


def test_ollama_error_donne_judge_error_sans_relance():
    fn = ScriptedJudge(OllamaError("Impossible de contacter Ollama"))

    result = run_case(fn)

    assert result["status"] == "judge_error" and result["attempts"] == 1
    assert "Impossible de contacter Ollama" in result["error"]


def test_judge_case_sans_passage_garde_les_affirmations_invalides_en_unverifiable():
    claims = [{"text": "x", "verdict": "SUPPORTED", "sources": ["S1"], "explanation": ""}]

    result = run_case(ScriptedJudge(raw(claims=claims)), passages=[])

    assert result["claims"][0]["verdict"] == "UNVERIFIABLE"
    assert result["scores"]["faithfulness"] == 0.0


# --- le vrai juge, sans réseau ----------------------------------------------------------


class FakeResponse:
    def __init__(self, payload=None, status=200, text=""):
        self.payload, self.status_code, self.text = payload, status, text

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(f"{self.status_code}")

    def json(self):
        if self.payload is None:
            raise ValueError("pas du JSON")
        return self.payload


def test_ollama_judge_envoie_la_requete_deterministe(monkeypatch):
    seen = {}

    def fake_post(url, json, timeout):
        seen.update(url=url, json=json, timeout=timeout)
        return FakeResponse({"message": {"role": "assistant", "content": "{}"}})

    monkeypatch.setattr(judge_module.requests, "post", fake_post)

    out = ollama_judge("http://h:1/", "m", timeout=12)([{"role": "user", "content": "q"}])

    assert out == "{}"
    assert seen["url"] == "http://h:1/api/chat" and seen["timeout"] == 12
    assert seen["json"] == {
        "model": "m",
        "messages": [{"role": "user", "content": "q"}],
        "stream": False,
        "format": "json",
        "options": {"temperature": 0, "seed": 42},
    }


@pytest.mark.parametrize("failure", [
    requests.exceptions.ConnectionError("refusé"),
    requests.exceptions.Timeout("lent"),
    FakeResponse(status=404, text="model not found"),
    FakeResponse(payload=None),
    FakeResponse({"pas_de_message": 1}),
])
def test_ollama_judge_enveloppe_les_erreurs_dans_ollama_error(monkeypatch, failure):
    def fake_post(url, json, timeout):
        if isinstance(failure, Exception):
            raise failure
        return failure

    monkeypatch.setattr(judge_module.requests, "post", fake_post)

    with pytest.raises(OllamaError):
        ollama_judge("http://h", "m")([])


def test_ollama_judge_envoie_num_ctx_en_gardant_la_graine_et_la_temperature(monkeypatch):
    seen = {}

    def fake_post(url, json, timeout):
        seen.update(json=json)
        return FakeResponse({"message": {"role": "assistant", "content": "{}"}})

    monkeypatch.setattr(judge_module.requests, "post", fake_post)
    ollama_judge("http://h:1", "m", num_ctx=4096)([{"role": "user", "content": "q"}])
    assert seen["json"]["options"] == {"temperature": 0, "seed": 42, "num_ctx": 4096}
