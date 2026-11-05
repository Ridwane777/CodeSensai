"""
Tests de la persistance de session & profils — feature [M1].

Chaque test renvoie à un critère d'acceptation de
docs/user-stories/M1-session-persistence.md, et les choix testés viennent de
docs/decisions/0007-persistance-des-sessions.md.

Les tests qui comptent le plus :
- `test_une_session_survit_a_la_fermeture` : c'est la Definition of Done de M1.
- `test_reprise_ne_melange_pas_les_projets` : échoue si quelqu'un retire le
  filtre par projet, et « reprendre la dernière » rouvrirait la conversation
  d'un autre projet.
- `test_profil_illisible_leve_valueerror` : le CLI s'appuie sur cette erreur
  précise pour démarrer quand même avec un profil vide.
"""
import os
import sqlite3
import stat
from datetime import UTC, datetime, timedelta

import pytest

from sensai.knowledge.memory import (
    Profile,
    SessionStore,
    build_system_prompt,
    handle_command,
    open_session,
)

PROJET = "/home/dev/mon-projet"
AUTRE_PROJET = "/home/dev/autre-projet"


@pytest.fixture
def store(tmp_path):
    return SessionStore(tmp_path / "sessions.db")


def echange(question: str, reponse: str) -> list[dict]:
    return [
        {"role": "user", "content": question},
        {"role": "assistant", "content": reponse},
    ]


# --- US-M1-1 : reprendre là où je m'étais arrêté ---------------------------


def test_une_session_survit_a_la_fermeture(tmp_path):
    """Deux SessionStore sur le même fichier = deux lancements du CLI."""
    db = tmp_path / "sessions.db"
    premier = SessionStore(db)
    session_id = premier.create(PROJET)
    premier.save(session_id, echange("Le test de login échoue", "Montre-moi la trace."))

    second = SessionStore(db)

    assert second.load(session_id) == echange("Le test de login échoue", "Montre-moi la trace.")


def test_sauvegarde_remplace_au_lieu_d_ajouter(store):
    """History.drop_last() retire un tour : la base ne doit pas le garder."""
    session_id = store.create(PROJET)
    store.save(session_id, [*echange("q1", "r1"), {"role": "user", "content": "q2"}])

    store.save(session_id, echange("q1", "r1"))

    assert store.load(session_id) == echange("q1", "r1")


def test_les_champs_d_un_message_sont_conserves(store):
    """Les appels d'outils (ReAct, Lot A) ajoutent des champs aux messages."""
    message = {
        "role": "assistant",
        "content": "",
        "tool_calls": [{"function": {"name": "search_codebase", "arguments": {"query": "é"}}}],
    }
    session_id = store.create(PROJET)
    store.save(session_id, [message])

    assert store.load(session_id) == [message]


def test_session_inconnue_leve_keyerror(store):
    with pytest.raises(KeyError):
        store.load("nexiste-pas")
    with pytest.raises(KeyError):
        store.save("nexiste-pas", echange("q", "r"))


def test_le_dossier_de_donnees_est_cree(tmp_path):
    SessionStore(tmp_path / "pas" / "encore" / "la" / "sessions.db")

    assert (tmp_path / "pas" / "encore" / "la" / "sessions.db").is_file()


# --- Droits d'accès : l'historique n'est lisible que par son propriétaire ---

posix_seulement = pytest.mark.skipif(os.name != "posix", reason="droits POSIX")


def droits(chemin) -> int:
    return stat.S_IMODE(chemin.stat().st_mode)


@posix_seulement
def test_dossier_cree_en_700_et_base_en_600(tmp_path):
    dossier = tmp_path / ".sensai"
    SessionStore(dossier / "sessions.db")

    assert droits(dossier) == 0o700
    assert droits(dossier / "sessions.db") == 0o600


@posix_seulement
def test_profil_ecrit_en_600(tmp_path):
    chemin = tmp_path / ".sensai" / "profile.json"
    Profile(preferences=["utilise pytest"]).save(chemin)

    assert droits(chemin.parent) == 0o700
    assert droits(chemin) == 0o600


@posix_seulement
def test_un_dossier_existant_n_est_pas_modifie(tmp_path):
    """--data-dir peut pointer vers un dossier de l'utilisateur (son $HOME) :
    Sensai ne doit pas en changer les droits."""
    existant = tmp_path / "a-moi"
    existant.mkdir(mode=0o755)
    existant.chmod(0o755)

    SessionStore(existant / "sessions.db")

    assert droits(existant) == 0o755


# --- Purge automatique : durée de conservation (ADR-0007) -------------------


def vieillir(store, session_id, jours):
    """Fait comme si le dernier message de la session datait de `jours` jours."""
    date = (datetime.now(UTC) - timedelta(days=jours)).isoformat()
    with sqlite3.connect(store.db_path) as conn:
        conn.execute("UPDATE sessions SET updated_at = ? WHERE id = ?", (date, session_id))


def test_purge_supprime_les_sessions_inactives(store):
    vieille = store.create(PROJET)
    store.save(vieille, echange("vieux bug", "r"))
    vieillir(store, vieille, 31)
    recente = store.create(PROJET)
    store.save(recente, echange("bug du jour", "r"))

    supprimees = store.purge(30)

    assert supprimees == 1
    assert not store.exists(vieille)
    assert store.load(recente) == echange("bug du jour", "r")


def test_purge_se_fonde_sur_le_dernier_message_pas_sur_la_creation(store):
    """Une conversation commencée il y a longtemps mais toujours active reste."""
    session_id = store.create(PROJET)
    store.save(session_id, echange("q", "r"))
    with sqlite3.connect(store.db_path) as conn:
        conn.execute(
            "UPDATE sessions SET created_at = '2020-01-01T00:00:00+00:00' WHERE id = ?",
            (session_id,),
        )

    assert store.purge(30) == 0
    assert store.exists(session_id)


def test_purge_epargne_la_session_demandee(store):
    """`sensai --session <id>` sur une vieille session : on ne l'efface pas
    au moment même où l'utilisateur la redemande."""
    demandee = store.create(PROJET)
    store.save(demandee, echange("q", "r"))
    vieillir(store, demandee, 90)

    assert store.purge(30, keep=demandee) == 0
    assert store.exists(demandee)


def test_retention_zero_ne_purge_jamais(store):
    session_id = store.create(PROJET)
    store.save(session_id, echange("q", "r"))
    vieillir(store, session_id, 3650)

    assert store.purge(0) == 0
    assert store.exists(session_id)


def test_purge_supprime_aussi_les_messages(store):
    session_id = store.create(PROJET)
    store.save(session_id, echange("secret collé par erreur", "r"))
    vieillir(store, session_id, 31)

    store.purge(30)

    with sqlite3.connect(store.db_path) as conn:
        restants = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
    assert restants == 0


# --- Reprise au démarrage (ADR-0007) ----------------------------------------


def test_reprend_la_derniere_session_du_projet(store):
    ancienne = store.create(PROJET)
    store.save(ancienne, echange("ancienne", "r"))
    recente = store.create(PROJET)
    store.save(recente, echange("récente", "r"))

    session_id, turns = open_session(store, PROJET)

    assert session_id == recente
    assert turns == echange("récente", "r")


def test_reprise_ne_melange_pas_les_projets(store):
    a_moi = store.create(PROJET)
    store.save(a_moi, echange("mon projet", "r"))
    autre = store.create(AUTRE_PROJET)
    store.save(autre, echange("autre projet", "r"))

    session_id, _ = open_session(store, PROJET)

    assert session_id == a_moi


def test_une_session_vide_n_est_pas_reprise(store):
    """Lancer puis quitter sans rien dire ne doit pas masquer la vraie dernière session."""
    pleine = store.create(PROJET)
    store.save(pleine, echange("q", "r"))
    store.create(PROJET)

    session_id, _ = open_session(store, PROJET)

    assert session_id == pleine


def test_premier_lancement_cree_une_session_vide(store):
    session_id, turns = open_session(store, PROJET)

    assert turns == []
    assert store.load(session_id) == []


# --- US-M1-3 : choisir quelle conversation reprendre ------------------------


def test_nouvelle_session_ignore_l_historique(store):
    ancienne = store.create(PROJET)
    store.save(ancienne, echange("q", "r"))

    session_id, turns = open_session(store, PROJET, new=True)

    assert session_id != ancienne
    assert turns == []


def test_reprendre_une_session_precise(store):
    voulue = store.create(PROJET)
    store.save(voulue, echange("bug auth", "r"))
    recente = store.create(PROJET)
    store.save(recente, echange("refonte API", "r"))

    session_id, turns = open_session(store, PROJET, session_id=voulue)

    assert session_id == voulue
    assert turns == echange("bug auth", "r")


def test_reprendre_une_session_inconnue_leve_keyerror(store):
    with pytest.raises(KeyError):
        open_session(store, PROJET, session_id="nexiste-pas")


def test_liste_des_sessions_du_projet(store):
    session_id = store.create(PROJET)
    store.save(session_id, echange("Pourquoi le   test\nde login échoue ?", "r"))
    store.save(store.create(AUTRE_PROJET), echange("autre", "r"))

    sessions = store.list(PROJET)

    assert [s.id for s in sessions] == [session_id]
    assert sessions[0].title == "Pourquoi le test de login échoue ?"
    assert sessions[0].message_count == 2
    assert sessions[0].updated_at


def test_liste_la_plus_recente_en_premier(store):
    ancienne = store.create(PROJET)
    store.save(ancienne, echange("ancienne", "r"))
    recente = store.create(PROJET)
    store.save(recente, echange("récente", "r"))

    assert [s.id for s in store.list(PROJET)] == [recente, ancienne]


# --- US-M1-2 : ne pas répéter mes préférences -------------------------------


def test_profil_survit_a_la_fermeture(tmp_path):
    chemin = tmp_path / "profile.json"
    profil = Profile.load(chemin)
    profil.remember("utilise pytest, pas unittest")
    profil.save(chemin)

    assert Profile.load(chemin).preferences == ["utilise pytest, pas unittest"]


def test_profil_absent_donne_un_profil_vide(tmp_path):
    assert Profile.load(tmp_path / "absent.json").is_empty()


def test_profil_illisible_leve_valueerror(tmp_path):
    chemin = tmp_path / "profile.json"
    chemin.write_text("{ pas du json", encoding="utf-8")

    with pytest.raises(ValueError):
        Profile.load(chemin)


def test_profil_injecte_dans_le_prompt_systeme():
    profil = Profile(name="Ridwane", preferences=["réponds en français", "utilise pytest"])

    prompt = build_system_prompt("Tu es CodeSensei.", profil)

    assert prompt.startswith("Tu es CodeSensei.")
    assert "Ridwane" in prompt
    assert "- réponds en français" in prompt
    assert "- utilise pytest" in prompt


def test_consigne_de_reprise_ajoutee_au_prompt():
    prompt = build_system_prompt("Tu es CodeSensei.", Profile(preferences=["utilise pytest"]),
                                 resumed_note="Tu as accès à l'historique.")

    assert prompt.startswith("Tu es CodeSensei.")
    assert "Tu as accès à l'historique." in prompt
    assert "- utilise pytest" in prompt


def test_profil_vide_ne_change_pas_le_prompt(monkeypatch):
    from datetime import datetime, timedelta, timezone

    from sensai.knowledge import memory
    from sensai.knowledge.memory import date_block

    # Heure figée : deux appels à cheval sur une minute donneraient deux textes.
    fixed = datetime(2026, 11, 1, 9, 5, tzinfo=timezone(timedelta(hours=1)))
    monkeypatch.setattr(memory, "local_datetime", lambda: fixed)

    assert build_system_prompt("Tu es CodeSensei.", Profile()) == \
        "Tu es CodeSensei.\n\n" + date_block()


def test_le_prompt_donne_la_date_du_jour():
    """Essai réel du 2026-11-01 : sans date, le modèle se croyait en 2024 et jugeait
    « erronés » les résultats web de 2026."""
    from datetime import date

    from sensai.knowledge.memory import date_block

    block = date_block(date(2026, 11, 1))
    assert "1 novembre 2026" in block and "2026-11-01" in block
    assert "web_search" in block and "untrusted" in block
    assert "heure" not in block  # une date seule ne donne pas d'heure


def test_le_prompt_donne_l_heure_du_debut_de_session(monkeypatch):
    """Essai réel du 2026-11-01 : sans heure, le modèle cherchait l'heure sur le web
    et répondait avec un extrait figé."""
    from datetime import datetime, timedelta, timezone

    from sensai.knowledge import memory

    fixed = datetime(2026, 11, 1, 9, 5, tzinfo=timezone(timedelta(hours=1)))
    monkeypatch.setattr(memory, "local_datetime", lambda: fixed)
    block = memory.date_block()
    assert "1 novembre 2026" in block and "09:05 (UTC+0100)" in block
    assert block in build_system_prompt("Tu es CodeSensei.", Profile())


# --- Commandes du CLI : /remember, /profile, /forget, /sessions -------------


def test_remember_enregistre_sur_le_disque(tmp_path, store):
    chemin = tmp_path / "profile.json"
    profil = Profile()

    reponse = handle_command("/remember utilise pytest", profil, chemin, store, PROJET)

    assert reponse
    assert Profile.load(chemin).preferences == ["utilise pytest"]


def test_remember_sans_texte_n_ajoute_rien(tmp_path, store):
    profil = Profile()

    reponse = handle_command("/remember   ", profil, tmp_path / "profile.json", store, PROJET)

    assert reponse
    assert profil.preferences == []


def test_profile_affiche_les_preferences(tmp_path, store):
    profil = Profile(preferences=["utilise pytest"])

    reponse = handle_command("/profile", profil, tmp_path / "profile.json", store, PROJET)

    assert "utilise pytest" in reponse


def test_forget_efface_les_preferences(tmp_path, store):
    chemin = tmp_path / "profile.json"
    profil = Profile(preferences=["utilise pytest"])
    profil.save(chemin)

    handle_command("/forget", profil, chemin, store, PROJET)

    assert Profile.load(chemin).preferences == []


def test_sessions_liste_le_projet(tmp_path, store):
    session_id = store.create(PROJET)
    store.save(session_id, echange("bug auth", "r"))

    reponse = handle_command("/sessions", Profile(), tmp_path / "profile.json", store, PROJET)

    assert session_id in reponse
    assert "bug auth" in reponse


def test_un_message_normal_n_est_pas_une_commande(tmp_path, store):
    """Sinon la question de l'utilisateur ne partirait jamais au modèle."""
    reponse = handle_command(
        "Pourquoi /profile renvoie 404 ?", Profile(), tmp_path / "p.json", store, PROJET
    )

    assert reponse is None


def test_supprimer_une_session_efface_aussi_son_texte_du_fichier(store):
    """Sans VACUUM, le texte supprimé restait dans les pages libres de SQLite (L11)."""
    sid = store.create("/projet")
    store.save(sid, [{"role": "user", "content": "phrase-tres-reconnaissable-1234"}])
    store.delete(sid)
    assert not store.exists(sid)
    assert b"phrase-tres-reconnaissable-1234" not in store.db_path.read_bytes()
