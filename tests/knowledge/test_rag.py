"""
Tests du RAG sur le projet — feature [R1].

Chaque bloc renvoie à une user story de docs/user-stories/R1-basic-rag.md ;
les choix testés viennent de docs/decisions/0009-rag-sur-la-codebase.md.

Ollama n'est jamais appelé : `FauxEmbedder` produit un « sac de mots » haché.
Deux textes qui partagent des mots ont des vecteurs proches, ce qui suffit à
tester la recherche sans réseau ni modèle.

Les tests qui comptent le plus :
- `test_env_jamais_indexe_meme_sans_gitignore` : un secret indexé peut partir
  au modèle, voire sur le pod distant. Il échoue si on retire la liste
  interdite en dur.
- `test_fichier_supprime_n_est_plus_cite` : sinon l'agent cite du code qui
  n'existe plus.
- `test_sous_le_seuil_rien_n_est_renvoye` : c'est ce qui empêche l'agent
  d'inventer une réponse (US-R1-3).
"""
import hashlib
import math
import os
import re
import stat

import pytest

from sensai.knowledge.rag import (
    RagIndex,
    chunk_file,
    format_context,
    scan_files,
)

DIMS = 256


class FauxEmbedder:
    """Sac de mots haché, normalisé. Compte les textes reçus."""

    def __init__(self):
        self.textes_recus = 0

    def __call__(self, textes: list[str]) -> list[list[float]]:
        self.textes_recus += len(textes)
        vecteurs = []
        for texte in textes:
            v = [0.0] * DIMS
            for mot in re.findall(r"\w+", texte.lower()):
                v[int(hashlib.md5(mot.encode()).hexdigest(), 16) % DIMS] += 1.0
            n = math.sqrt(sum(x * x for x in v)) or 1.0
            vecteurs.append([x / n for x in v])
        return vecteurs


@pytest.fixture
def projet(tmp_path):
    racine = tmp_path / "projet"
    (racine / "src").mkdir(parents=True)
    (racine / "src" / "auth.py").write_text(
        '"""Authentification."""\n'
        "import hmac\n"
        "\n"
        "\n"
        "def verifier_token(token, secret):\n"
        '    """Vérifie le token de connexion envoyé par le client."""\n'
        "    return hmac.compare_digest(token, secret)\n"
        "\n"
        "\n"
        "class Session:\n"
        "    def ouvrir(self, utilisateur):\n"
        "        return utilisateur\n",
        encoding="utf-8",
    )
    (racine / "README.md").write_text(
        "# Projet\n"
        "Présentation générale.\n"
        "\n"
        "## Installation\n"
        "Lancer pip install pour installer les dépendances.\n"
        "\n"
        "## Déploiement\n"
        "Le déploiement se fait avec docker compose sur le serveur.\n",
        encoding="utf-8",
    )
    return racine


@pytest.fixture
def index(tmp_path):
    return RagIndex(tmp_path / "donnees" / "rag.db", project="projet", embed=FauxEmbedder())


def sources(resultats):
    return [r["source"] for r in resultats]


def indexes(racine):
    return [str(f.relative_to(racine)) for f in scan_files(racine).files]


# --- US-R1-2 : indexer sans fuite ni attente inutile -------------------------


def test_env_jamais_indexe_meme_sans_gitignore(projet):
    (projet / ".env").write_text("DB_PASSWORD=hunter2\n", encoding="utf-8")
    (projet / ".env.local").write_text("API_KEY=abc\n", encoding="utf-8")
    (projet / "id_rsa").write_text("-----BEGIN OPENSSH PRIVATE KEY-----\n", encoding="utf-8")
    (projet / "serveur.pem").write_text("-----BEGIN CERTIFICATE-----\n", encoding="utf-8")

    fichiers = indexes(projet)

    assert ".env" not in fichiers
    assert ".env.local" not in fichiers
    assert "id_rsa" not in fichiers
    assert "serveur.pem" not in fichiers
    assert "src/auth.py" in fichiers


def test_dossiers_inutiles_ignores(projet):
    for dossier in (".git", ".venv", "node_modules", "__pycache__"):
        (projet / dossier).mkdir()
        (projet / dossier / "bruit.py").write_text("x = 1\n", encoding="utf-8")

    assert all("bruit.py" not in f for f in indexes(projet))


def test_gitignore_respecte(projet):
    (projet / ".gitignore").write_text("build/\n*.log\n", encoding="utf-8")
    (projet / "build").mkdir()
    (projet / "build" / "genere.py").write_text("x = 1\n", encoding="utf-8")
    (projet / "trace.log").write_text("erreur\n", encoding="utf-8")

    fichiers = indexes(projet)

    assert "build/genere.py" not in fichiers
    assert "trace.log" not in fichiers


def test_binaires_et_gros_fichiers_ignores(projet):
    (projet / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00binaire")
    (projet / "dump.sql").write_text("x" * 2_000_000, encoding="utf-8")

    fichiers = indexes(projet)

    assert "logo.png" not in fichiers
    assert "dump.sql" not in fichiers


def test_format_non_pris_en_charge_liste_avec_un_conseil(projet):
    """US-R1-4 / décision 7 : un format qu'on ne sait pas lire n'est pas indexé,
    mais on dit quoi faire. (Depuis ADR-0034, le PDF est un document converti :
    tests/knowledge/test_rag_documents.py.)"""
    (projet / "notes.odt").write_bytes(b"PK\x03\x04binaire")

    resultat = scan_files(projet)

    assert all(f.name != "notes.odt" for f in resultat.files)
    conseils = {str(p.relative_to(projet)): c for p, c in resultat.unsupported}
    assert "notes.odt" in conseils
    assert "pandoc" in conseils["notes.odt"].lower()


def test_premiere_indexation_compte_fichiers_et_passages(projet, index):
    rapport = index.update(projet)

    assert rapport.files_indexed == 2
    assert rapport.chunks > 0


def test_seuls_les_fichiers_modifies_sont_reindexes(projet, index):
    index.update(projet)
    avant = index.embed.textes_recus

    (projet / "README.md").write_text("# Projet\nNouveau contenu.\n", encoding="utf-8")
    rapport = index.update(projet)

    assert rapport.files_indexed == 1, "seul README.md a changé"
    nouveaux_textes = index.embed.textes_recus - avant
    assert 0 < nouveaux_textes <= 2, "auth.py ne doit pas être réembarqué"


def test_rien_a_refaire_si_rien_n_a_change(projet, index):
    index.update(projet)
    avant = index.embed.textes_recus

    rapport = index.update(projet)

    assert rapport.files_indexed == 0
    assert index.embed.textes_recus == avant


def test_fichier_supprime_n_est_plus_cite(projet, index):
    index.update(projet)
    (projet / "src" / "auth.py").unlink()

    rapport = index.update(projet)

    assert rapport.files_removed == 1
    resultats = index.search("vérifie le token de connexion", min_score=0.0)
    assert "src/auth.py" not in sources(resultats)


def test_l_index_survit_a_la_fermeture(projet, tmp_path):
    db = tmp_path / "donnees" / "rag.db"
    RagIndex(db, project="projet", embed=FauxEmbedder()).update(projet)

    relu = RagIndex(db, project="projet", embed=FauxEmbedder())

    assert not relu.is_empty()
    assert "src/auth.py" in sources(relu.search("token de connexion", min_score=0.0))


def test_les_projets_ne_se_melangent_pas(projet, tmp_path):
    db = tmp_path / "donnees" / "rag.db"
    RagIndex(db, project="projet", embed=FauxEmbedder()).update(projet)

    autre = RagIndex(db, project="autre-projet", embed=FauxEmbedder())

    assert autre.is_empty()
    assert autre.search("token de connexion", min_score=0.0) == []


# --- Découpage par structure (décision 3) -----------------------------------


def test_une_fonction_python_est_un_passage_avec_ses_lignes(projet):
    passages = chunk_file(projet / "src" / "auth.py", "src/auth.py")

    fonction = next(p for p in passages if "def verifier_token" in p.text)
    assert (fonction.start, fonction.end) == (5, 7)
    assert "class Session" not in fonction.text


def test_une_classe_python_est_un_passage(projet):
    passages = chunk_file(projet / "src" / "auth.py", "src/auth.py")

    classe = next(p for p in passages if "class Session" in p.text)
    assert (classe.start, classe.end) == (10, 12)


def test_python_invalide_decoupe_par_lignes(tmp_path):
    """Un fichier en cours d'écriture ne doit pas faire échouer l'indexation."""
    fichier = tmp_path / "casse.py"
    fichier.write_text("def oups(:\n    pass\n", encoding="utf-8")

    passages = chunk_file(fichier, "casse.py")

    assert passages and passages[0].start == 1


def test_markdown_decoupe_par_section(projet):
    passages = chunk_file(projet / "README.md", "README.md")

    deploiement = next(p for p in passages if "docker compose" in p.text)
    assert deploiement.text.lstrip().startswith("## Déploiement")
    assert "pip install" not in deploiement.text
    assert (deploiement.start, deploiement.end) == (7, 8)


def test_long_fichier_texte_decoupe_en_blocs(tmp_path):
    fichier = tmp_path / "notes.txt"
    fichier.write_text("\n".join(f"ligne {i}" for i in range(1, 101)), encoding="utf-8")

    passages = chunk_file(fichier, "notes.txt")

    assert len(passages) > 1
    assert passages[0].start == 1
    assert passages[-1].end == 100


# --- US-R1-1 : poser une question sur mon code ------------------------------


def test_la_bonne_fonction_est_trouvee(projet, index):
    index.update(projet)

    resultats = index.search("où vérifie-t-on le token de connexion du client ?",
                             min_score=0.0)

    assert resultats[0]["source"] == "src/auth.py"
    assert resultats[0]["start"] == 5


def test_la_bonne_section_de_doc_est_trouvee(projet, index):
    index.update(projet)

    resultats = index.search("comment se fait le déploiement avec docker ?", min_score=0.0)

    assert resultats[0]["source"] == "README.md"


def test_le_contexte_cite_fichier_et_lignes(projet, index):
    index.update(projet)
    resultats = index.search("token de connexion", min_score=0.0, top_k=1)

    contexte = format_context(resultats)

    assert "src/auth.py:5-7" in contexte
    assert "verifier_token" in contexte


def test_le_contexte_numerote_chaque_ligne(projet, index):
    """Essai réel sur RunPod : sans numéros, le modèle a cité cli.py:123-127 pour
    du code situé ligne 112. Un modèle ne compte pas les lignes d'un passage : il
    doit lire le numéro devant chacune."""
    index.update(projet)
    resultats = index.search("token de connexion", min_score=0.0, top_k=1)

    contexte = format_context(resultats)

    assert "5│ def verifier_token(token, secret):" in contexte
    assert "7│     return hmac.compare_digest(token, secret)" in contexte


def test_le_contexte_ne_montre_pas_le_score(projet, index):
    """Le score n'aide pas le modèle à répondre ; affiché, il le commentait
    (« la pertinence est de 0.51 ») au lieu de répondre."""
    index.update(projet)

    contexte = format_context(index.search("token de connexion", min_score=0.0))

    assert "pertinence" not in contexte.lower()
    assert "score" not in contexte.lower()


def test_le_contexte_autorise_une_reponse_normale_hors_projet(projet, index):
    """US-R1-1 : « c'est quoi une closure ? » doit être répondu comme avant, sans
    commentaire sur des passages qui ne la concernent pas."""
    index.update(projet)

    for contexte in (format_context(index.search("token", min_score=0.0)), format_context([])):
        assert "réponds normalement" in contexte
        assert "sans mentionner" in contexte


def test_top_k_limite_le_nombre_de_passages(projet, index):
    index.update(projet)

    assert len(index.search("projet", min_score=0.0, top_k=2)) <= 2


# --- US-R1-3 : dire quand le projet ne contient pas la réponse --------------


def test_sous_le_seuil_rien_n_est_renvoye(projet, index):
    index.update(projet)

    assert index.search("broker kafka zookeeper", min_score=0.5) == []


def test_contexte_vide_previent_le_modele():
    assert "aucun passage" in format_context([]).lower()


def test_index_vide(index):
    assert index.is_empty()
    assert index.search("n'importe quoi", min_score=0.0) == []


# --- Protection des données (ADR-0007, réutilisé par R1) ---------------------


@pytest.mark.skipif(os.name != "posix", reason="droits POSIX")
def test_index_cree_en_prive(tmp_path):
    dossier = tmp_path / ".sensai"
    RagIndex(dossier / "rag.db", project="p", embed=FauxEmbedder())

    assert stat.S_IMODE(dossier.stat().st_mode) == 0o700
    assert stat.S_IMODE((dossier / "rag.db").stat().st_mode) == 0o600


def test_le_document_d_etat_n_est_pas_indexe(tmp_path):
    """SENSAI.md est déjà donné en entier à l'agent (ADR-0029) : l'indexer
    l'enverrait deux fois au modèle."""
    racine = tmp_path / "projet"
    racine.mkdir()
    (racine / "SENSAI.md").write_text("## Fait\n\n- x\n", encoding="utf-8")
    (racine / "README.md").write_text("# Projet\n", encoding="utf-8")

    assert indexes(racine) == ["README.md"]


def test_un_fichier_cree_apres_l_ouverture_entre_dans_la_recherche(tmp_path):
    """Essai du 2026-11-01 : un fichier créé après la première question restait
    invisible, et le modèle affirmait qu'il n'existait pas."""
    projet = tmp_path / "projet"
    projet.mkdir()
    (projet / "a.md").write_text("Lancer les tests avec pytest.\n", encoding="utf-8")
    index = RagIndex(tmp_path / "rag.db", str(projet), FauxEmbedder(), model="faux")
    index.update(projet)
    (projet / "deploiement.txt").write_text("Région de déploiement : eu-west-3\n", encoding="utf-8")

    assert index.refresh_if_stale(projet) is None  # moins de 30 s : rien n'est refait
    index._updated_at -= 31
    report = index.refresh_if_stale(projet)
    assert report is not None and report.files_indexed == 1
    hits = index.search("région de déploiement", top_k=3, min_score=0.0)
    assert any(h["source"] == "deploiement.txt" for h in hits)
