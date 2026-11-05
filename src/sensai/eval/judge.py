"""
Le juge LLM — feature [EV1], ADR-0019.

Un appel au modèle par cas, qui répond en JSON :

    {"relevance": 1-5, "coherence": 1-5,
     "claims": [{"text", "verdict", "sources": ["S1"], "explanation"}]}

La fidélité n'est pas demandée au modèle : elle se calcule ici, à partir des
verdicts (SUPPORTED / nombre d'affirmations). Un modèle local sort parfois du
JSON bancal ; on le relance avec un message correctif, et si ça ne suffit pas
le cas est marqué `judge_error` — jamais noté 0, jamais compté dans les moyennes.

Le texte du prompt vient du registre de prompts (A4, ADR-0010) sous le nom
`judge` : une modification du prompt est donc une nouvelle version, et le
rapport en garde l'empreinte.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from typing import Any, NamedTuple

import requests

from sensai.config import PROJECT_ROOT, prompts_dir
from sensai.core.ollama_client import OllamaError
from sensai.eval.sources import Passage, format_passages
from sensai.knowledge.prompt_versions import PromptStore

JUDGE_PROMPT_NAME = "judge"
DEFAULT_TEMPERATURE = 0
DEFAULT_SEED = 42
DEFAULT_MAX_RETRIES = 2
DEFAULT_TIMEOUT_S = 300
RAW_MAX_CHARS = 2000

SUPPORTED = "SUPPORTED"
CONTRADICTED = "CONTRADICTED"
UNVERIFIABLE = "UNVERIFIABLE"
VERDICTS = (SUPPORTED, CONTRADICTED, UNVERIFIABLE)
FLAG_INVALID_CITATION = "citation_invalide"

JudgeFn = Callable[[list[dict]], str]
AnswerFn = Callable[[str, list[Passage]], str]

_PLACEHOLDER = re.compile(r"\{\{(QUESTION|PASSAGES|ANSWER)\}\}")
_FENCE = re.compile(r"^```[a-zA-Z]*\s*|\s*```$")


class JudgeOutputError(ValueError):
    """La sortie du juge n'est pas exploitable (JSON, schéma ou valeurs)."""


class JudgePrompt(NamedTuple):
    text: str
    version: str
    sha256: str


# --- prompt ----------------------------------------------------------------


def find_judge_store() -> PromptStore:
    """Registre qui contient le prompt `judge`.

    Celui du dossier courant s'il l'a (même règle que `prompts_dir`), sinon
    celui du dépôt : `sensai-eval` peut se lancer depuis un autre projet, dont
    le `prompts/` n'a pas de juge.
    """
    store = PromptStore(prompts_dir())
    if store.exists() and JUDGE_PROMPT_NAME in store.names():
        return store
    return PromptStore(PROJECT_ROOT / "prompts")


def load_judge_prompt(store: PromptStore, version: str | None = None) -> JudgePrompt:
    """Texte, numéro de version et sha256 du prompt du juge (active par défaut).

    KeyError si le prompt ou la version n'existe pas.
    """
    version_id = store.resolve(JUDGE_PROMPT_NAME, version) if version else store.active(
        JUDGE_PROMPT_NAME
    )
    text = store.load(JUDGE_PROMPT_NAME, version_id)
    return JudgePrompt(text, version_id, hashlib.sha256(text.encode("utf-8")).hexdigest())


def build_messages(
    prompt: str, question: str, answer: str, passages: list[Passage]
) -> list[dict]:
    """Remplit les trois jetons du prompt en un seul passage.

    Pas de `str.format` (le prompt contient des accolades JSON) ni de `replace`
    en série (une question qui contiendrait `{{ANSWER}}` serait réécrite).
    """
    values = {
        "QUESTION": question,
        "PASSAGES": format_passages(passages),
        "ANSWER": answer,
    }
    content = _PLACEHOLDER.sub(lambda m: values[m.group(1)], prompt)
    return [{"role": "user", "content": content}]


# --- analyse de la sortie ----------------------------------------------------


def _extract_json(raw: str) -> Any:
    text = _FENCE.sub("", raw.strip()).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise JudgeOutputError("aucun objet JSON dans la réponse")
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError as e:
        raise JudgeOutputError(f"JSON invalide : {e}") from e


def _score(data: dict, key: str) -> int:
    value = data.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 5:
        raise JudgeOutputError(f"« {key} » doit être un entier de 1 à 5 (reçu : {value!r})")
    return value


def _claim(raw: Any, index: int, passage_ids: set[str]) -> dict:
    where = f"claims[{index}]"
    if not isinstance(raw, dict):
        raise JudgeOutputError(f"{where} doit être un objet")
    text = raw.get("text")
    if not isinstance(text, str) or not text.strip():
        raise JudgeOutputError(f"{where} : « text » manquant")
    verdict = raw.get("verdict")
    verdict = verdict.strip().upper() if isinstance(verdict, str) else verdict
    if verdict not in VERDICTS:
        raise JudgeOutputError(
            f"{where} : verdict inconnu {raw.get('verdict')!r} (attendu : {', '.join(VERDICTS)})"
        )
    sources = raw.get("sources", [])
    if not isinstance(sources, list) or not all(isinstance(s, str) for s in sources):
        raise JudgeOutputError(f"{where} : « sources » doit être une liste de chaînes")
    explanation = raw.get("explanation", "")
    if not isinstance(explanation, str):
        raise JudgeOutputError(f"{where} : « explanation » doit être une chaîne")

    claim: dict[str, Any] = {
        "text": text.strip(),
        "verdict": verdict,
        "sources": sources,
        "explanation": explanation.strip(),
        "flags": [],
    }
    # Un verdict qui ne s'appuie sur aucun passage connu n'est pas vérifiable :
    # on le dégrade au lieu de lui faire confiance (et on garde l'original).
    if verdict in (SUPPORTED, CONTRADICTED) and (
        not sources or not all(s in passage_ids for s in sources)
    ):
        claim["verdict"] = UNVERIFIABLE
        claim["verdict_original"] = verdict
        claim["flags"].append(FLAG_INVALID_CITATION)
    return claim


def parse_judgment(raw: str, passage_ids: set[str] | list[str]) -> dict:
    """Valide la sortie du juge ; JudgeOutputError si elle n'est pas exploitable."""
    data = _extract_json(raw)
    if not isinstance(data, dict):
        raise JudgeOutputError("la réponse doit être un objet JSON")
    ids = set(passage_ids)
    relevance = _score(data, "relevance")
    coherence = _score(data, "coherence")
    claims = data.get("claims")
    if not isinstance(claims, list):
        raise JudgeOutputError("« claims » doit être une liste (vide sans affirmation)")
    return {
        "relevance": relevance,
        "coherence": coherence,
        "claims": [_claim(c, i, ids) for i, c in enumerate(claims)],
    }


def faithfulness(claims: list[dict]) -> float | None:
    """Part d'affirmations SUPPORTED ; None sans affirmation (rien à vérifier)."""
    if not claims:
        return None
    return round(sum(c["verdict"] == SUPPORTED for c in claims) / len(claims), 4)


# --- un cas ------------------------------------------------------------------


def _corrective_message(error: Exception) -> str:
    return (
        f"Ta réponse n'est pas exploitable : {error}. Réponds à nouveau uniquement avec "
        'l\'objet JSON demandé ({"relevance", "coherence", "claims"}), sans texte autour.'
    )


def judge_case(
    question: str,
    answer: str,
    passages: list[Passage],
    judge_fn: JudgeFn,
    prompt: str,
    max_retries: int = DEFAULT_MAX_RETRIES,
) -> dict:
    """Fait juger un cas. Ne lève jamais : un échec devient `status: judge_error`.

    Une sortie inexploitable est renvoyée au juge (avec sa propre sortie et un
    message correctif) jusqu'à `max_retries` fois. Une `OllamaError` n'est pas
    rejouée : si le serveur est tombé, trois appels de plus n'y changent rien.
    """
    messages = build_messages(prompt, question, answer, passages)
    by_id = {p.id: p for p in passages}
    attempts = 0
    raw = ""
    error: Exception | None = None
    while attempts <= max_retries:
        attempts += 1
        try:
            raw = judge_fn(list(messages))
        except OllamaError as e:
            return _failure(f"Ollama : {e}", raw, attempts)
        try:
            judgment = parse_judgment(raw, set(by_id))
        except JudgeOutputError as e:
            error = e
            messages += [
                {"role": "assistant", "content": raw},
                {"role": "user", "content": _corrective_message(e)},
            ]
            continue
        return _success(judgment, by_id, attempts)
    return _failure(str(error), raw, attempts)


def _success(judgment: dict, by_id: dict[str, Passage], attempts: int) -> dict:
    claims = judgment["claims"]
    for claim in claims:
        claim["citations"] = [by_id[s].citation() for s in claim["sources"] if s in by_id]
    return {
        "status": "ok",
        "scores": {
            "relevance": judgment["relevance"],
            "coherence": judgment["coherence"],
            "faithfulness": faithfulness(claims),
        },
        "claims": claims,
        "flagged": [c for c in claims if c["verdict"] != SUPPORTED],
        "attempts": attempts,
    }


def _failure(error: str, raw: str, attempts: int) -> dict:
    return {
        "status": "judge_error",
        "error": error,
        "raw": raw[:RAW_MAX_CHARS],
        "attempts": attempts,
    }


# --- le vrai juge --------------------------------------------------------------


def ollama_judge(
    host: str,
    model: str,
    temperature: float = DEFAULT_TEMPERATURE,
    seed: int = DEFAULT_SEED,
    timeout: float = DEFAULT_TIMEOUT_S,
    num_ctx: int | None = None,
) -> JudgeFn:
    """Juge réel : `POST /api/chat`, sans streaming, sortie JSON, température 0.

    `num_ctx` (M2, ADR-0045) : le prompt du juge colle la réponse et ses
    passages ; sans lui, Ollama peut les tronquer en silence et le score
    jugerait un texte coupé.

    `stream_chat` n'accepte pas d'`options` et streame ; un juge a besoin du
    texte entier, d'une sortie reproductible (graine fixe) et du mode JSON
    d'Ollama. On ne touche pas à `ollama_client.py` (ADR-0019).
    """
    url = f"{host.rstrip('/')}/api/chat"
    options: dict[str, float | int] = {"temperature": temperature, "seed": seed}
    if num_ctx:
        options["num_ctx"] = num_ctx

    def judge(messages: list[dict]) -> str:
        payload = {
            "model": model,
            "messages": messages,
            "stream": False,
            "format": "json",
            "options": options,
        }
        response = None
        try:
            response = requests.post(url, json=payload, timeout=timeout)
            response.raise_for_status()
            return response.json()["message"]["content"]
        except requests.exceptions.ConnectionError as e:
            raise OllamaError(
                f"Impossible de contacter Ollama sur {host}. "
                "Vérifiez que `ollama serve` tourne bien."
            ) from e
        except requests.exceptions.Timeout as e:
            raise OllamaError(f"Le juge ne répond pas (timeout de {timeout:g} s).") from e
        except requests.exceptions.HTTPError as e:
            detail = response.text[:200] if response is not None else str(e)
            raise OllamaError(f"Erreur Ollama : {detail}") from e
        except (requests.exceptions.RequestException, ValueError, KeyError, TypeError) as e:
            raise OllamaError(f"Réponse d'Ollama inattendue : {e}") from e

    return judge
