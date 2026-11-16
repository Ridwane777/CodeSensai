"""
Tests the LLM judge - feature [EV1], ADR-0019.

The judge is replaced by functions that return canned text: no test talks to
Ollama. What we check is everything the code does with the model output
(validation, retries, faithfulness computation).
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

PASSAGES = [Passage("S1", "src/a.py", "f returns 1.", 1, 3), Passage("S2", "docs/b.md", "g.")]
IDS = {"S1", "S2"}


def judgment(**override):
    data = {
        "relevance": 4,
        "coherence": 5,
        "claims": [
            {"text": "f returns 1", "verdict": "SUPPORTED", "sources": ["S1"], "explanation": "ok"}
        ],
    }
    data.update(override)
    return data


def raw(**override):
    return json.dumps(judgment(**override))


# --- the prompt stored in the registry --------------------------------------------


def test_the_judge_prompt_is_stored_and_the_registry_stays_consistent():
    store = PromptStore(prompts_dir())

    assert store.check() == []
    prompt = load_judge_prompt(store)
    assert prompt.version == store.active("judge")
    assert len(prompt.sha256) == 64
    for token in ("{{QUESTION}}", "{{PASSAGES}}", "{{ANSWER}}"):
        assert token in prompt.text


def test_unknown_prompt_version_raises_keyerror():
    with pytest.raises(KeyError):
        load_judge_prompt(PromptStore(prompts_dir()), "v99")


def test_build_messages_fills_tokens_without_reinterpreting_braces():
    prompt = 'Q={{QUESTION}} P={{PASSAGES}} A={{ANSWER}} {"relevance": 1}'

    [message] = build_messages(prompt, "q {{ANSWER}}", "answer {x}", PASSAGES)

    assert message["role"] == "user"
    # The question contains a token: it stays as is, it is not replaced in turn.
    assert message["content"].startswith("Q=q {{ANSWER}} P=[S1] src/a.py:1-3\nf returns 1.")
    assert message["content"].endswith('A=answer {x} {"relevance": 1}')


# --- output parsing ------------------------------------------------------------------


def test_parse_judgment_valid():
    result = parse_judgment(raw(), IDS)

    assert result["relevance"] == 4 and result["coherence"] == 5
    assert result["claims"][0]["verdict"] == "SUPPORTED"
    assert result["claims"][0]["flags"] == []


def test_parse_judgment_accepts_code_blocks_and_surrounding_text():
    wrapped = f"Here is my evaluation:\n```json\n{raw()}\n```\nHope this helps."

    assert parse_judgment(wrapped, IDS)["relevance"] == 4
    assert parse_judgment(f"```\n{raw()}\n```", IDS)["coherence"] == 5


def test_parse_judgment_normalizes_verdict_case():
    result = parse_judgment(
        raw(claims=[{"text": "x", "verdict": " unverifiable ", "sources": []}]), IDS
    )

    assert result["claims"][0]["verdict"] == "UNVERIFIABLE"


@pytest.mark.parametrize("bad", [
    "no JSON at all",
    '{"relevance": 4, "coherence": ',
    "[1, 2, 3]",
])
def test_parse_judgment_rejects_invalid_json(bad):
    with pytest.raises(JudgeOutputError):
        parse_judgment(bad, IDS)


@pytest.mark.parametrize("override", [
    {"relevance": 0},
    {"relevance": 6},
    {"coherence": "5"},
    {"coherence": 4.5},
    {"relevance": True},
    {"relevance": None},
    {"claims": "none"},
    {"claims": [{"text": "x", "verdict": "MAYBE", "sources": []}]},
    {"claims": [{"verdict": "SUPPORTED", "sources": ["S1"]}]},
    {"claims": ["not an object"]},
    {"claims": [{"text": "x", "verdict": "SUPPORTED", "sources": "S1"}]},
])
def test_parse_judgment_rejects_invalid_schema_or_values(override):
    with pytest.raises(JudgeOutputError):
        parse_judgment(raw(**override), IDS)


def test_parse_judgment_requires_both_scores_and_the_claims_list():
    data = judgment()
    del data["claims"]
    with pytest.raises(JudgeOutputError):
        parse_judgment(json.dumps(data), IDS)


@pytest.mark.parametrize("sources", [[], ["S9"], ["S1", "S9"]])
@pytest.mark.parametrize("verdict", ["SUPPORTED", "CONTRADICTED"])
def test_invalid_citation_downgrades_verdict_to_unverifiable(verdict, sources):
    claims = [{"text": "x", "verdict": verdict, "sources": sources, "explanation": ""}]

    claim = parse_judgment(raw(claims=claims), IDS)["claims"][0]

    assert claim["verdict"] == "UNVERIFIABLE"
    assert claim["verdict_original"] == verdict
    assert "citation_invalide" in claim["flags"]


def test_unverifiable_without_source_is_not_an_invalid_citation():
    claims = [{"text": "x", "verdict": "UNVERIFIABLE", "sources": []}]

    claim = parse_judgment(raw(claims=claims), IDS)["claims"][0]

    assert claim["verdict"] == "UNVERIFIABLE" and claim["flags"] == []
    assert "verdict_original" not in claim


# --- faithfulness --------------------------------------------------------------------


def claim(verdict):
    return {"verdict": verdict}


def test_faithfulness_is_the_share_of_supported_claims():
    claims = [claim("SUPPORTED"), claim("SUPPORTED"), claim("CONTRADICTED"), claim("UNVERIFIABLE")]

    assert faithfulness(claims) == 0.5
    assert faithfulness([claim("SUPPORTED")]) == 1.0
    assert faithfulness([claim("UNVERIFIABLE")]) == 0.0
    assert faithfulness([claim("SUPPORTED")] + [claim("CONTRADICTED")] * 2) == 0.3333


def test_faithfulness_is_none_without_claims():
    assert faithfulness([]) is None


# --- one case: retries and errors -----------------------------------------------------


class ScriptedJudge:
    """Returns the outputs in order and keeps the received messages."""

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
    return judge_case(
        "What does f do?", "f returns 1.", passages, fn, "Q={{QUESTION}}", max_retries
    )


def test_successful_judge_case_computes_scores_citations_and_flagged_claims():
    claims = [
        {"text": "f returns 1", "verdict": "SUPPORTED", "sources": ["S1"], "explanation": ""},
        {"text": "f is slow", "verdict": "UNVERIFIABLE", "sources": [], "explanation": ""},
    ]

    result = run_case(ScriptedJudge(raw(claims=claims)))

    assert result["status"] == "ok" and result["attempts"] == 1
    assert result["scores"] == {"relevance": 4, "coherence": 5, "faithfulness": 0.5}
    assert result["claims"][0]["citations"] == [
        {"id": "S1", "source": "src/a.py", "start": 1, "end": 3}
    ]
    assert [c["text"] for c in result["flagged"]] == ["f is slow"]


def test_malformed_then_valid_output_is_retried_with_a_corrective_message():
    fn = ScriptedJudge("sorry, here is my opinion: rather good", raw())

    result = run_case(fn)

    assert result["status"] == "ok" and result["attempts"] == 2
    second = fn.calls[1]
    assert second[-2] == {"role": "assistant", "content": "sorry, here is my opinion: rather good"}
    assert second[-1]["role"] == "user" and "JSON" in second[-1]["content"]
    # The first call was not modified afterwards.
    assert len(fn.calls[0]) == 1


def test_persistently_malformed_output_gives_judge_error_after_retries():
    fn = ScriptedJudge("x" * 5000, "no", "still no")

    result = run_case(fn, max_retries=2)

    assert result["status"] == "judge_error"
    assert result["attempts"] == 3 and len(fn.calls) == 3
    assert "error" in result and result["raw"] == "still no"
    assert "scores" not in result


def test_the_kept_raw_text_is_truncated():
    result = run_case(ScriptedJudge("x" * 5000), max_retries=0)

    assert result["status"] == "judge_error"
    assert len(result["raw"]) == judge_module.RAW_MAX_CHARS


def test_ollama_error_gives_judge_error_without_retry():
    fn = ScriptedJudge(OllamaError("Cannot reach Ollama"))

    result = run_case(fn)

    assert result["status"] == "judge_error" and result["attempts"] == 1
    assert "Cannot reach Ollama" in result["error"]


def test_judge_case_without_passage_keeps_invalid_claims_unverifiable():
    claims = [{"text": "x", "verdict": "SUPPORTED", "sources": ["S1"], "explanation": ""}]

    result = run_case(ScriptedJudge(raw(claims=claims)), passages=[])

    assert result["claims"][0]["verdict"] == "UNVERIFIABLE"
    assert result["scores"]["faithfulness"] == 0.0


# --- the real judge, no network --------------------------------------------------------


class FakeResponse:
    def __init__(self, payload=None, status=200, text=""):
        self.payload, self.status_code, self.text = payload, status, text

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(f"{self.status_code}")

    def json(self):
        if self.payload is None:
            raise ValueError("not JSON")
        return self.payload


def test_ollama_judge_sends_the_deterministic_request(monkeypatch):
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
    requests.exceptions.ConnectionError("refused"),
    requests.exceptions.Timeout("slow"),
    FakeResponse(status=404, text="model not found"),
    FakeResponse(payload=None),
    FakeResponse({"no_message": 1}),
])
def test_ollama_judge_wraps_errors_in_ollama_error(monkeypatch, failure):
    def fake_post(url, json, timeout):
        if isinstance(failure, Exception):
            raise failure
        return failure

    monkeypatch.setattr(judge_module.requests, "post", fake_post)

    with pytest.raises(OllamaError):
        ollama_judge("http://h", "m")([])


def test_ollama_judge_sends_num_ctx_keeping_seed_and_temperature(monkeypatch):
    seen = {}

    def fake_post(url, json, timeout):
        seen.update(json=json)
        return FakeResponse({"message": {"role": "assistant", "content": "{}"}})

    monkeypatch.setattr(judge_module.requests, "post", fake_post)
    ollama_judge("http://h:1", "m", num_ctx=4096)([{"role": "user", "content": "q"}])
    assert seen["json"]["options"] == {"temperature": 0, "seed": 42, "num_ctx": 4096}
