"""Teste les fournisseurs de passages du juge — feature [EV1], ADR-0019."""
from sensai.eval.sources import (
    NO_PASSAGES,
    Passage,
    format_passages,
    rag_sources,
    static_sources,
)


def test_static_sources_numerote_les_passages_et_accepte_deux_formes():
    passages = static_sources(["texte brut", {"source": "src/a.py", "text": "def f(): ..."}])

    assert [p.id for p in passages] == ["S1", "S2"]
    assert passages[0].source == "dataset" and passages[0].text == "texte brut"
    assert passages[1].source == "src/a.py"


def test_format_passages_met_l_identifiant_et_la_position_avant_le_texte():
    text = format_passages([
        Passage("S1", "src/a.py", "def f(): ...", start=10, end=12),
        Passage("S2", "dataset", "texte brut"),
    ])

    assert text == "[S1] src/a.py:10-12\ndef f(): ...\n\n[S2] dataset\ntexte brut"


def test_format_passages_sans_passage_le_dit():
    assert format_passages([]) == NO_PASSAGES


class FakeIndex:
    """Tout objet qui a `.search(query, top_k, min_score)` convient (pas besoin de R1)."""

    def __init__(self, hits):
        self.hits = hits
        self.calls = []

    def search(self, query, top_k, min_score):
        self.calls.append((query, top_k, min_score))
        return self.hits


def test_rag_sources_transmet_la_question_et_convertit_les_resultats():
    index = FakeIndex([
        {"source": "src/a.py", "start": 1, "end": 5, "text": "def f(): ...", "score": 0.9},
        {"source": "docs/b.md", "start": 3, "end": 4, "text": "# B", "score": 0.7},
    ])

    passages = rag_sources(index, top_k=3, min_score=0.4)("Où est f ?")

    assert index.calls == [("Où est f ?", 3, 0.4)]
    assert passages == [
        Passage("S1", "src/a.py", "def f(): ...", 1, 5),
        Passage("S2", "docs/b.md", "# B", 3, 4),
    ]


def test_rag_sources_sans_resultat_donne_une_liste_vide():
    assert rag_sources(FakeIndex([]), top_k=5, min_score=0.5)("rien") == []
