"""
Teste le budget de tokens et la compression par résumé glissant — feature
[M2], ADR-0045.

`stream_chat_messages` est remplacé par un faux résumeur : aucun appel
réseau, le test contrôle exactement ce que le modèle « répond ».
"""
import pytest

from sensai.core.ollama_client import OllamaError
from sensai.knowledge import compression
from sensai.knowledge.compression import (
    CompressionError,
    budget_from_num_ctx,
    compress_messages,
    count_tokens,
    summarize,
)


def _turn(role, content):
    return {"role": role, "content": content}


def test_count_tokens_approxime_quatre_caracteres_par_token():
    assert count_tokens("a" * 40) == 10
    assert count_tokens("") == 1  # jamais zéro : un texte vide compte quand même


def test_budget_from_num_ctx_retire_la_marge_de_reponse():
    assert budget_from_num_ctx(8000) == 8000 - compression.RESPONSE_MARGIN_TOKENS


def test_sous_le_budget_rien_ne_change():
    messages = [_turn("system", "consigne"), _turn("user", "courte question")]
    resultat, compresse = compress_messages("host", "modele", messages, max_tokens=1000)
    assert resultat == messages
    assert compresse is False


def test_peu_de_tours_meme_au_dessus_du_budget_ne_declenche_rien():
    # keep_recent par défaut (6) >= le nombre de tours : rien à résumer.
    messages = [_turn("user", "x" * 100), _turn("assistant", "y" * 100)]
    resultat, compresse = compress_messages("host", "modele", messages, max_tokens=1)
    assert resultat == messages
    assert compresse is False


def test_au_dessus_du_budget_resume_les_plus_anciens(monkeypatch):
    def faux_stream(host, model, messages, options=None):
        yield {"content": "résumé compact"}

    monkeypatch.setattr(compression, "stream_chat_messages", faux_stream)

    anciens = [_turn("user" if i % 2 == 0 else "assistant", f"tour {i}" * 20) for i in range(10)]
    recents = [_turn("user", "question récente"), _turn("assistant", "réponse récente")]
    messages = [_turn("system", "consigne"), *anciens, *recents]

    resultat, compresse = compress_messages(
        "host", "modele", messages, max_tokens=1, keep_recent=2
    )
    assert compresse is True
    assert len(resultat) == 1 + len(recents)  # un seul message système, puis les tours récents
    assert resultat[0]["role"] == "system"
    assert "consigne" in resultat[0]["content"]
    assert "résumé compact" in resultat[0]["content"]
    assert resultat[-2:] == recents


def test_alternance_user_assistant_respectee_apres_compression(monkeypatch):
    """Revue PR #97 : le résumé fond dans le système, jamais un second
    message `user` d'affilée avec le premier tour gardé."""
    def faux_stream(host, model, messages, options=None):
        yield {"content": "résumé"}

    monkeypatch.setattr(compression, "stream_chat_messages", faux_stream)

    anciens = [_turn("user" if i % 2 == 0 else "assistant", "x" * 50) for i in range(8)]
    recents = [_turn("user", "une question"), _turn("assistant", "une réponse")]
    messages = [_turn("system", "consigne"), *anciens, *recents]

    resultat, _ = compress_messages("host", "modele", messages, max_tokens=1, keep_recent=2)
    roles = [m["role"] for m in resultat]
    assert roles == ["system", "user", "assistant"]


def test_un_seul_message_plus_gros_que_le_budget_part_sans_avertir(monkeypatch):
    """Rien à résumer (un seul tour, en dessous de keep_recent) : le message
    part tel quel, même hors budget — pas de boucle infinie ni d'erreur."""
    def faux_stream(host, model, messages, options=None):
        pytest.fail("ne doit jamais être appelé : rien à résumer")

    monkeypatch.setattr(compression, "stream_chat_messages", faux_stream)

    messages = [_turn("system", "consigne"), _turn("user", "x" * 1_000_000)]
    resultat, compresse = compress_messages(
        "host", "modele", messages, max_tokens=1, keep_recent=6
    )
    assert resultat == messages
    assert compresse is False


def test_les_tours_recents_restent_intacts_apres_compression(monkeypatch):
    def faux_stream(host, model, messages, options=None):
        yield {"content": "résumé"}

    monkeypatch.setattr(compression, "stream_chat_messages", faux_stream)

    anciens = [_turn("user" if i % 2 == 0 else "assistant", "x" * 50) for i in range(8)]
    recents = [_turn("user", "une vraie question précise")]
    messages = [*anciens, *recents]

    resultat, _ = compress_messages("host", "modele", messages, max_tokens=1, keep_recent=1)
    assert resultat[-1] == _turn("user", "une vraie question précise")


def test_ollama_indisponible_leve_compressionerror(monkeypatch):
    def faux_stream(host, model, messages, options=None):
        raise OllamaError("injoignable")
        yield  # pragma: no cover

    monkeypatch.setattr(compression, "stream_chat_messages", faux_stream)
    with pytest.raises(CompressionError, match="injoignable"):
        summarize("host", "modele", [_turn("user", "a"), _turn("assistant", "b")])


def test_reponse_vide_leve_compressionerror(monkeypatch):
    def faux_stream(host, model, messages, options=None):
        yield {"content": ""}

    monkeypatch.setattr(compression, "stream_chat_messages", faux_stream)
    with pytest.raises(CompressionError, match="aucun résumé"):
        summarize("host", "modele", [_turn("user", "a")])


def test_summarize_passe_num_ctx_en_options(monkeypatch):
    recu = {}

    def faux_stream(host, model, messages, options=None):
        recu["options"] = options
        yield {"content": "résumé"}

    monkeypatch.setattr(compression, "stream_chat_messages", faux_stream)
    summarize("host", "modele", [_turn("user", "a")], num_ctx=8192)
    assert recu["options"] == {"num_ctx": 8192}


def test_summarize_borne_lentree_a_num_ctx(monkeypatch):
    """Revue PR #97 : résumer des tours eux-mêmes trop gros pour num_ctx ne
    doit pas se faire tronquer en silence par Ollama — on les borne nous-mêmes."""
    recu = {}

    def faux_stream(host, model, messages, options=None):
        recu["transcript"] = messages[-1]["content"]
        yield {"content": "résumé"}

    monkeypatch.setattr(compression, "stream_chat_messages", faux_stream)
    enormes_tours = [_turn("user", "x" * 100_000)]
    summarize("host", "modele", enormes_tours, num_ctx=1000)
    limite = budget_from_num_ctx(1000) * compression.CHARS_PER_TOKEN
    assert len(recu["transcript"]) <= limite + len("[…début tronqué, trop ancien "
                                                     "pour entrer dans le contexte…]\n")


def test_resolve_budget_prefere_le_reglage_explicite():
    assert compression.resolve_budget(100, 4096) == 100


def test_resolve_budget_derive_de_num_ctx_sinon():
    assert compression.resolve_budget(None, 4096) == budget_from_num_ctx(4096)
    defaut = budget_from_num_ctx(compression.DEFAULT_NUM_CTX)
    assert compression.resolve_budget(None, None) == defaut


def test_compress_messages_sans_budget_explicite_suit_num_ctx(monkeypatch):
    """Un seul défaut (revue PR #97) : sans `max_tokens`, la limite est celle de
    `num_ctx` moins la marge — plus de constante 8000 qui contredit le reste."""
    def faux_stream(host, model, messages, options=None):
        yield {"content": "résumé"}

    monkeypatch.setattr(compression, "stream_chat_messages", faux_stream)
    # num_ctx minuscule : le budget dérivé vaut 1 token, tout dépasse.
    messages = [_turn("user" if i % 2 == 0 else "assistant", "x" * 400) for i in range(10)]
    _, compresse = compress_messages("host", "modele", messages, keep_recent=2, num_ctx=1)
    assert compresse is True
    # num_ctx large : le même historique tient largement.
    _, compresse = compress_messages("host", "modele", messages, keep_recent=2, num_ctx=32768)
    assert compresse is False
