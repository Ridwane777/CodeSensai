"""
Tests for session & profile persistence — feature [M1].

Each test refers to an acceptance criterion in
docs/user-stories/M1-session-persistence.md, and the tested choices come from
docs/decisions/0007-session-persistence.md.

The tests that matter most:
- `test_a_session_survives_closing`: this is the M1 Definition of Done.
- `test_resume_does_not_mix_projects`: fails if someone removes the per-project
  filter, in which case "resume the last one" would reopen another project's
  conversation.
- `test_unreadable_profile_raises_valueerror`: the CLI relies on this exact
  error to start anyway with an empty profile.
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

PROJET = "/home/dev/my-project"
AUTRE_PROJET = "/home/dev/other-project"


@pytest.fixture
def store(tmp_path):
    return SessionStore(tmp_path / "sessions.db")


def echange(question: str, reponse: str) -> list[dict]:
    return [
        {"role": "user", "content": question},
        {"role": "assistant", "content": reponse},
    ]


# --- US-M1-1: pick up where I left off ------------------------------------


def test_a_session_survives_closing(tmp_path):
    """Two SessionStores on the same file = two CLI launches."""
    db = tmp_path / "sessions.db"
    premier = SessionStore(db)
    session_id = premier.create(PROJET)
    premier.save(session_id, echange("The login test fails", "Show me the traceback."))

    second = SessionStore(db)

    assert second.load(session_id) == echange("The login test fails", "Show me the traceback.")


def test_save_replaces_instead_of_appending(store):
    """History.drop_last() removes a turn: the database must not keep it."""
    session_id = store.create(PROJET)
    store.save(session_id, [*echange("q1", "r1"), {"role": "user", "content": "q2"}])

    store.save(session_id, echange("q1", "r1"))

    assert store.load(session_id) == echange("q1", "r1")


def test_message_fields_are_kept(store):
    """Tool calls (ReAct, Workstream A) add fields to messages. The "é" query
    checks that non-ASCII content round-trips."""
    message = {
        "role": "assistant",
        "content": "",
        "tool_calls": [{"function": {"name": "search_codebase", "arguments": {"query": "é"}}}],
    }
    session_id = store.create(PROJET)
    store.save(session_id, [message])

    assert store.load(session_id) == [message]


def test_unknown_session_raises_keyerror(store):
    with pytest.raises(KeyError):
        store.load("nexiste-pas")
    with pytest.raises(KeyError):
        store.save("nexiste-pas", echange("q", "r"))


def test_the_data_folder_is_created(tmp_path):
    SessionStore(tmp_path / "not" / "there" / "yet" / "sessions.db")

    assert (tmp_path / "not" / "there" / "yet" / "sessions.db").is_file()


# --- Permissions: the history is readable by its owner only --------------

posix_seulement = pytest.mark.skipif(os.name != "posix", reason="POSIX permissions")


def droits(chemin) -> int:
    return stat.S_IMODE(chemin.stat().st_mode)


@posix_seulement
def test_folder_created_700_and_database_600(tmp_path):
    dossier = tmp_path / ".sensai"
    SessionStore(dossier / "sessions.db")

    assert droits(dossier) == 0o700
    assert droits(dossier / "sessions.db") == 0o600


@posix_seulement
def test_profile_written_600(tmp_path):
    chemin = tmp_path / ".sensai" / "profile.json"
    Profile(preferences=["use pytest"]).save(chemin)

    assert droits(chemin.parent) == 0o700
    assert droits(chemin) == 0o600


@posix_seulement
def test_an_existing_folder_is_not_modified(tmp_path):
    """--data-dir may point to a user folder (their $HOME): CodeSensai must
    not change its permissions."""
    existant = tmp_path / "mine"
    existant.mkdir(mode=0o755)
    existant.chmod(0o755)

    SessionStore(existant / "sessions.db")

    assert droits(existant) == 0o755


# --- Automatic purge: retention period (ADR-0007) --------------------------


def vieillir(store, session_id, jours):
    """Pretend the last message of the session is `jours` days old."""
    date = (datetime.now(UTC) - timedelta(days=jours)).isoformat()
    with sqlite3.connect(store.db_path) as conn:
        conn.execute("UPDATE sessions SET updated_at = ? WHERE id = ?", (date, session_id))


def test_purge_deletes_inactive_sessions(store):
    vieille = store.create(PROJET)
    store.save(vieille, echange("old bug", "r"))
    vieillir(store, vieille, 31)
    recente = store.create(PROJET)
    store.save(recente, echange("today's bug", "r"))

    supprimees = store.purge(30)

    assert supprimees == 1
    assert not store.exists(vieille)
    assert store.load(recente) == echange("today's bug", "r")


def test_purge_uses_last_message_not_creation(store):
    """A conversation started long ago but still active is kept."""
    session_id = store.create(PROJET)
    store.save(session_id, echange("q", "r"))
    with sqlite3.connect(store.db_path) as conn:
        conn.execute(
            "UPDATE sessions SET created_at = '2020-01-01T00:00:00+00:00' WHERE id = ?",
            (session_id,),
        )

    assert store.purge(30) == 0
    assert store.exists(session_id)


def test_purge_spares_the_requested_session(store):
    """`sensai --session <id>` on an old session: do not delete it at the very
    moment the user asks for it again."""
    demandee = store.create(PROJET)
    store.save(demandee, echange("q", "r"))
    vieillir(store, demandee, 90)

    assert store.purge(30, keep=demandee) == 0
    assert store.exists(demandee)


def test_zero_retention_never_purges(store):
    session_id = store.create(PROJET)
    store.save(session_id, echange("q", "r"))
    vieillir(store, session_id, 3650)

    assert store.purge(0) == 0
    assert store.exists(session_id)


def test_purge_also_deletes_messages(store):
    session_id = store.create(PROJET)
    store.save(session_id, echange("secret pasted by mistake", "r"))
    vieillir(store, session_id, 31)

    store.purge(30)

    with sqlite3.connect(store.db_path) as conn:
        restants = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
    assert restants == 0


# --- Resume at startup (ADR-0007) ------------------------------------------


def test_resumes_the_last_project_session(store):
    ancienne = store.create(PROJET)
    store.save(ancienne, echange("older", "r"))
    recente = store.create(PROJET)
    store.save(recente, echange("recent", "r"))

    session_id, turns = open_session(store, PROJET)

    assert session_id == recente
    assert turns == echange("recent", "r")


def test_resume_does_not_mix_projects(store):
    a_moi = store.create(PROJET)
    store.save(a_moi, echange("my project", "r"))
    autre = store.create(AUTRE_PROJET)
    store.save(autre, echange("other project", "r"))

    session_id, _ = open_session(store, PROJET)

    assert session_id == a_moi


def test_an_empty_session_is_not_resumed(store):
    """Launching then quitting without a word must not hide the real last session."""
    pleine = store.create(PROJET)
    store.save(pleine, echange("q", "r"))
    store.create(PROJET)

    session_id, _ = open_session(store, PROJET)

    assert session_id == pleine


def test_first_launch_creates_an_empty_session(store):
    session_id, turns = open_session(store, PROJET)

    assert turns == []
    assert store.load(session_id) == []


# --- US-M1-3: choose which conversation to resume -------------------------


def test_new_session_ignores_history(store):
    ancienne = store.create(PROJET)
    store.save(ancienne, echange("q", "r"))

    session_id, turns = open_session(store, PROJET, new=True)

    assert session_id != ancienne
    assert turns == []


def test_resume_a_specific_session(store):
    voulue = store.create(PROJET)
    store.save(voulue, echange("bug auth", "r"))
    recente = store.create(PROJET)
    store.save(recente, echange("API redesign", "r"))

    session_id, turns = open_session(store, PROJET, session_id=voulue)

    assert session_id == voulue
    assert turns == echange("bug auth", "r")


def test_resume_unknown_session_raises_keyerror(store):
    with pytest.raises(KeyError):
        open_session(store, PROJET, session_id="nexiste-pas")


def test_list_project_sessions(store):
    session_id = store.create(PROJET)
    store.save(session_id, echange("Why does the   login\ntest fail?", "r"))
    store.save(store.create(AUTRE_PROJET), echange("other", "r"))

    sessions = store.list(PROJET)

    assert [s.id for s in sessions] == [session_id]
    assert sessions[0].title == "Why does the login test fail?"
    assert sessions[0].message_count == 2
    assert sessions[0].updated_at


def test_list_newest_first(store):
    ancienne = store.create(PROJET)
    store.save(ancienne, echange("older", "r"))
    recente = store.create(PROJET)
    store.save(recente, echange("recent", "r"))

    assert [s.id for s in store.list(PROJET)] == [recente, ancienne]


# --- US-M1-2: do not repeat my preferences --------------------------------


def test_profile_survives_closing(tmp_path):
    chemin = tmp_path / "profile.json"
    profil = Profile.load(chemin)
    profil.remember("use pytest, not unittest")
    profil.save(chemin)

    assert Profile.load(chemin).preferences == ["use pytest, not unittest"]


def test_missing_profile_gives_empty_profile(tmp_path):
    assert Profile.load(tmp_path / "absent.json").is_empty()


def test_unreadable_profile_raises_valueerror(tmp_path):
    chemin = tmp_path / "profile.json"
    chemin.write_text("{ not json", encoding="utf-8")

    with pytest.raises(ValueError):
        Profile.load(chemin)


def test_profile_injected_into_system_prompt():
    profil = Profile(name="Ridwane", preferences=["answer in English", "use pytest"])

    prompt = build_system_prompt("You are CodeSensai.", profil)

    assert prompt.startswith("You are CodeSensai.")
    assert "Ridwane" in prompt
    assert "- answer in English" in prompt
    assert "- use pytest" in prompt


def test_resume_instruction_added_to_prompt():
    prompt = build_system_prompt("You are CodeSensai.", Profile(preferences=["use pytest"]),
                                 resumed_note="You have access to the history.")

    assert prompt.startswith("You are CodeSensai.")
    assert "You have access to the history." in prompt
    assert "- use pytest" in prompt


def test_empty_profile_does_not_change_prompt(monkeypatch):
    from datetime import datetime, timedelta, timezone

    from sensai.knowledge import memory
    from sensai.knowledge.memory import date_block

    # Frozen time: two calls straddling a minute would give two texts.
    fixed = datetime(2026, 11, 1, 9, 5, tzinfo=timezone(timedelta(hours=1)))
    monkeypatch.setattr(memory, "local_datetime", lambda: fixed)

    assert build_system_prompt("You are CodeSensai.", Profile()) == \
        "You are CodeSensai.\n\n" + date_block()


def test_prompt_gives_today_date():
    """Real trial run on 2026-11-01: without a date, the model thought it was 2024
    and judged the 2026 web results "wrong"."""
    from datetime import date

    from sensai.knowledge.memory import date_block

    block = date_block(date(2026, 11, 1))
    assert "November 1, 2026" in block and "2026-11-01" in block
    assert "web_search" in block and "untrusted" in block
    assert "local time" not in block  # a date alone gives no time


def test_prompt_gives_session_start_time(monkeypatch):
    """Real trial run on 2026-11-01: without a time, the model searched the web for
    the time and answered with a stale snippet."""
    from datetime import datetime, timedelta, timezone

    from sensai.knowledge import memory

    fixed = datetime(2026, 11, 1, 9, 5, tzinfo=timezone(timedelta(hours=1)))
    monkeypatch.setattr(memory, "local_datetime", lambda: fixed)
    block = memory.date_block()
    assert "November 1, 2026" in block and "09:05 (UTC+0100)" in block
    assert block in build_system_prompt("You are CodeSensai.", Profile())


# --- CLI commands: /remember, /profile, /forget, /sessions ----------------


def test_remember_saves_to_disk(tmp_path, store):
    chemin = tmp_path / "profile.json"
    profil = Profile()

    reponse = handle_command("/remember use pytest", profil, chemin, store, PROJET)

    assert reponse
    assert Profile.load(chemin).preferences == ["use pytest"]


def test_remember_without_text_adds_nothing(tmp_path, store):
    profil = Profile()

    reponse = handle_command("/remember   ", profil, tmp_path / "profile.json", store, PROJET)

    assert reponse
    assert profil.preferences == []


def test_profile_shows_preferences(tmp_path, store):
    profil = Profile(preferences=["use pytest"])

    reponse = handle_command("/profile", profil, tmp_path / "profile.json", store, PROJET)

    assert "use pytest" in reponse


def test_forget_clears_preferences(tmp_path, store):
    chemin = tmp_path / "profile.json"
    profil = Profile(preferences=["use pytest"])
    profil.save(chemin)

    handle_command("/forget", profil, chemin, store, PROJET)

    assert Profile.load(chemin).preferences == []


def test_sessions_lists_the_project(tmp_path, store):
    session_id = store.create(PROJET)
    store.save(session_id, echange("bug auth", "r"))

    reponse = handle_command("/sessions", Profile(), tmp_path / "profile.json", store, PROJET)

    assert session_id in reponse
    assert "bug auth" in reponse


def test_a_normal_message_is_not_a_command(tmp_path, store):
    """Otherwise the user question would never reach the model."""
    reponse = handle_command(
        "Why does /profile return 404?", Profile(), tmp_path / "p.json", store, PROJET
    )

    assert reponse is None


def test_deleting_a_session_also_erases_its_text_from_the_file(store):
    """Without VACUUM, deleted text stayed in SQLite free pages (L11)."""
    sid = store.create("/project")
    store.save(sid, [{"role": "user", "content": "very-recognizable-phrase-1234"}])
    store.delete(sid)
    assert not store.exists(sid)
    assert b"very-recognizable-phrase-1234" not in store.db_path.read_bytes()
