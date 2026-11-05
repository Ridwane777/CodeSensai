"""`/structured` et run_structured_query (T5, ADR-0036) — sans Ollama."""
import json

import pytest

from sensai.core.ollama_client import OllamaError
from sensai.core.structured import (
    StructuredOutputError,
    handle_structured_command,
    is_structured_command,
    run_structured_query,
)


class FakeOllama:
    """Remplace stream_chat_messages : rejoue une réponse déjà écrite, ou lève."""

    def __init__(self, reply):
        self.reply = reply
        self.calls = []

    def __call__(self, host, model, messages, tools=None, format=None, options=None):
        self.calls.append({"host": host, "model": model, "messages": messages, "format": format,
                           "options": options})
        if isinstance(self.reply, Exception):
            raise self.reply
        yield {"content": self.reply}


@pytest.fixture
def fake(monkeypatch):
    def install(reply):
        ollama = FakeOllama(reply)
        monkeypatch.setattr("sensai.core.structured.stream_chat_messages", ollama)
        return ollama
    return install


SCHEMA = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]}


def test_renvoie_le_json_parse(fake):
    fake('{"ok": true}')
    assert run_structured_query("http://h:1", "m1", "question", SCHEMA) == {"ok": True}


def test_passe_le_schema_dans_le_champ_format(fake):
    ollama = fake('{"ok": true}')
    run_structured_query("http://h:1", "m1", "question", SCHEMA)
    assert ollama.calls[0]["format"] == SCHEMA


def test_json_invalide_leve_une_erreur_explicite(fake):
    fake("ceci n'est pas du json")
    with pytest.raises(StructuredOutputError, match="JSON invalide"):
        run_structured_query("http://h:1", "m1", "question", SCHEMA)


def test_panne_ollama_devient_structured_output_error(fake):
    fake(OllamaError("Ollama ne répond pas (timeout)."))
    with pytest.raises(StructuredOutputError, match="timeout"):
        run_structured_query("http://h:1", "m1", "question", SCHEMA)


@pytest.mark.parametrize("line", ['/structured s.json "fais X"', "/structured x"])
def test_les_lignes_qui_commencent_par_la_commande_sont_reconnues(line):
    assert is_structured_command(line)


def test_autre_chose_n_est_pas_reconnu():
    assert not is_structured_command("pourquoi /structured échoue ?")


def test_sans_assez_d_arguments_affiche_l_usage():
    out = handle_structured_command("/structured schema.json", host="h", model="m")
    assert "Usage" in out


def test_schema_absent_est_signale(tmp_path):
    missing = tmp_path / "absent.json"
    out = handle_structured_command(
        f"/structured {missing} \"fais X\"", host="h", model="m"
    )
    assert "[Erreur]" in out and str(missing) in out


def test_schema_mal_forme_est_signale(tmp_path):
    bad = tmp_path / "schema.json"
    bad.write_text("{pas du json", encoding="utf-8")
    out = handle_structured_command(f'/structured {bad} "fais X"', host="h", model="m")
    assert "[Erreur]" in out


def test_commande_complete_renvoie_le_json_mis_en_forme(tmp_path):
    schema_file = tmp_path / "schema.json"
    schema_file.write_text(json.dumps(SCHEMA), encoding="utf-8")

    def query(host, model, prompt, schema):
        assert schema == SCHEMA
        assert prompt == "fais X"
        return {"ok": True}

    out = handle_structured_command(
        f'/structured {schema_file} "fais X"', host="h", model="m", query=query
    )
    assert json.loads(out) == {"ok": True}


def test_erreur_du_modele_est_signalee_sans_lever(tmp_path):
    schema_file = tmp_path / "schema.json"
    schema_file.write_text(json.dumps(SCHEMA), encoding="utf-8")

    def query(host, model, prompt, schema):
        raise StructuredOutputError("réponse non conforme")

    out = handle_structured_command(
        f'/structured {schema_file} "fais X"', host="h", model="m", query=query
    )
    assert "[Erreur]" in out


# --- Réponse fondée sur le projet (ADR-0039) ---------------------------------------------


def test_avec_gather_la_reponse_de_l_agent_sert_de_source(tmp_path):
    """Essai réel du 2026-10-24 : sans outils, /structured inventait les fonctions
    de stats.py. L'agent cherche d'abord (avec ses outils), puis la mise en forme
    selon le schéma ne s'appuie que sur ce qu'il a trouvé."""
    schema_file = tmp_path / "schema.json"
    schema_file.write_text(json.dumps(SCHEMA), encoding="utf-8")
    asked = []

    def gather(prompt):
        asked.append(prompt)
        return "stats.py ne définit qu'une fonction : maximum."

    def query(host, model, prompt, schema):
        assert "fais X" in prompt
        assert "stats.py ne définit qu'une fonction : maximum." in prompt
        return {"ok": True}

    out = handle_structured_command(
        f'/structured {schema_file} "fais X"', host="h", model="m", query=query, gather=gather
    )
    assert asked == ["fais X"]
    assert json.loads(out) == {"ok": True}


def test_echec_de_la_recherche_est_signale_sans_appel_structure(tmp_path):
    schema_file = tmp_path / "schema.json"
    schema_file.write_text(json.dumps(SCHEMA), encoding="utf-8")

    def gather(prompt):
        raise StructuredOutputError("Ollama ne répond pas")

    def query(*args):
        raise AssertionError("pas de mise en forme sans recherche")

    out = handle_structured_command(
        f'/structured {schema_file} "fais X"', host="h", model="m", query=query, gather=gather
    )
    assert out.startswith("[Erreur]") and "Ollama ne répond pas" in out


def test_le_schema_est_verifie_avant_de_lancer_la_recherche(tmp_path):
    def gather(prompt):
        raise AssertionError("schéma absent : rien ne doit être lancé")

    out = handle_structured_command(
        f'/structured {tmp_path / "absent.json"} "fais X"', host="h", model="m", gather=gather
    )
    assert "[Erreur]" in out


def test_num_ctx_part_dans_les_options_de_l_appel(fake):
    """Revue PR #97 : sans lui, Ollama tronque en silence un prompt long."""
    ollama = fake('{"ok": true}')
    run_structured_query("http://h:1", "m1", "question", SCHEMA, num_ctx=4096)
    assert ollama.calls[0]["options"] == {"num_ctx": 4096}


def test_sans_num_ctx_aucune_option_n_est_envoyee(fake):
    ollama = fake('{"ok": true}')
    run_structured_query("http://h:1", "m1", "question", SCHEMA)
    assert ollama.calls[0]["options"] is None


def test_la_commande_transmet_num_ctx_a_l_appel(fake, tmp_path):
    ollama = fake('{"ok": true}')
    schema = tmp_path / "schema.json"
    schema.write_text(json.dumps(SCHEMA), encoding="utf-8")
    out = handle_structured_command(
        f'/structured {schema} "fais X"', host="h", model="m", num_ctx=2048
    )
    assert json.loads(out) == {"ok": True}
    assert ollama.calls[0]["options"] == {"num_ctx": 2048}
