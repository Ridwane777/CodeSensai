"""Le corps des requêtes envoyées à Ollama (`/api/chat`), sans réseau — M2, ADR-0045."""
import json

import pytest

from sensai.core import ollama_client
from sensai.core.ollama_client import stream_chat, stream_chat_messages


class FausseReponse:
    def raise_for_status(self):
        pass

    def iter_lines(self):
        yield json.dumps({"message": {"content": "ok"}, "done": True}).encode()


def _capture(monkeypatch):
    envoyes = []

    def faux_post(url, json=None, **kwargs):
        envoyes.append(json)
        return FausseReponse()

    monkeypatch.setattr(ollama_client.requests, "post", faux_post)
    return envoyes


def test_options_num_ctx_part_dans_le_corps(monkeypatch):
    envoyes = _capture(monkeypatch)
    list(stream_chat_messages("http://h", "m", [], options={"num_ctx": 4096}))
    assert envoyes[0]["options"] == {"num_ctx": 4096}


def test_sans_options_le_champ_est_absent(monkeypatch):
    envoyes = _capture(monkeypatch)
    list(stream_chat_messages("http://h", "m", []))
    assert "options" not in envoyes[0]


def test_stream_chat_transmet_num_ctx(monkeypatch):
    """Revue PR #97 : le wrapper `stream_chat` (utilisé par sensai-eval) l'oubliait."""
    envoyes = _capture(monkeypatch)
    assert "".join(stream_chat("http://h", "m", [], num_ctx=8192)) == "ok"
    assert envoyes[0]["options"] == {"num_ctx": 8192}


def test_stream_chat_sans_num_ctx_n_envoie_pas_d_options(monkeypatch):
    envoyes = _capture(monkeypatch)
    list(stream_chat("http://h", "m", []))
    assert "options" not in envoyes[0]


# --- Paramètres de génération (ADR-0057) ---

def test_les_parametres_de_generation_partent_a_chaque_appel(monkeypatch):
    envoyes = _capture(monkeypatch)
    ollama_client.set_generation_options({"temperature": 0.2, "top_p": 0.9, "seed": None})
    list(stream_chat("http://h", "m", [], num_ctx=8192))
    assert envoyes[0]["options"] == {"temperature": 0.2, "top_p": 0.9, "num_ctx": 8192}
    assert ollama_client.generation_options() == {"temperature": 0.2, "top_p": 0.9}


def test_une_option_de_l_appel_l_emporte_sur_le_reglage_global(monkeypatch):
    """Ce qu'un appel fixe lui-même (num_ctx, une température 0…) n'est pas écrasé."""
    envoyes = _capture(monkeypatch)
    ollama_client.set_generation_options({"temperature": 0.7})
    list(stream_chat_messages("http://h", "m", [], options={"temperature": 0}))
    assert envoyes[0]["options"] == {"temperature": 0}


# --- Délai d'attente d'Ollama (essai du 2026-11-06 sur CPU) ---

def _capture_timeout(monkeypatch):
    delais = []

    def faux_post(url, json=None, timeout=None, **kwargs):
        delais.append(timeout)
        return FausseReponse()

    monkeypatch.setattr(ollama_client.requests, "post", faux_post)
    return delais


def test_la_connexion_reste_courte_et_la_lecture_attend_le_cpu(monkeypatch):
    """Sur CPU, qwen3:8b met plusieurs minutes avant le premier morceau : 60 s
    faisaient échouer chaque tour ; un Ollama arrêté doit rester signalé vite."""
    delais = _capture_timeout(monkeypatch)
    list(stream_chat_messages("http://h", "m", []))
    assert delais[0] == (ollama_client.CONNECT_TIMEOUT, ollama_client.DEFAULT_REQUEST_TIMEOUT)
    assert ollama_client.CONNECT_TIMEOUT <= 10 < 300 <= ollama_client.DEFAULT_REQUEST_TIMEOUT


def test_le_delai_regle_au_demarrage_s_applique(monkeypatch):
    delais = _capture_timeout(monkeypatch)
    ollama_client.set_request_timeout(1200)
    list(stream_chat_messages("http://h", "m", []))
    assert delais[0][1] == 1200


def test_un_timeout_donne_un_message_qui_dit_quoi_regler(monkeypatch):
    def lent(*args, **kwargs):
        raise ollama_client.requests.exceptions.ReadTimeout()

    monkeypatch.setattr(ollama_client.requests, "post", lent)
    with pytest.raises(ollama_client.OllamaError, match="request_timeout"):
        list(stream_chat_messages("http://h", "m", []))
