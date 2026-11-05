"""Journal des tours [EV3] (lot D — Valentino) : le stockage et le chronométrage."""
import os
import sqlite3
import stat
from datetime import UTC, datetime, timedelta

from sensai.core.events import Done, Token, ToolCall, ToolReturn
from sensai.observability.journal import (
    JOURNAL_FILE,
    MAX_ARGUMENT_CHARS,
    Journal,
    ToolRecord,
    TurnRecord,
    TurnRecorder,
    open_journal,
)

KEY = "sk-" + "abcdefghijklmnop1234"  # concaténé : un scanner de secrets ne crie pas


def _turn(session="s1", started=None, outcome="final_answer", tools=(), model_ms=100):
    return TurnRecord(session_id=session, project="/p",
                      started_at=(started or datetime.now(UTC)).isoformat(),
                      model_ms=model_ms, tokens_sent=42, outcome=outcome, interface="web",
                      tools=list(tools))


def test_ecrit_et_relit_un_tour_avec_ses_outils(tmp_path):
    j = Journal(tmp_path / JOURNAL_FILE)
    j.write(_turn(tools=[ToolRecord("read_file", '{"path": "a.py"}', 12, True),
                         ToolRecord("write_file", "{}", 30, False, "developpeur")]))
    [turn] = j.turns("s1")
    assert turn["outcome"] == "final_answer" and turn["model_ms"] == 100
    assert turn["tokens_sent"] == 42 and turn["interface"] == "web"
    assert [(t["tool"], t["ok"], t["agent"]) for t in turn["tools"]] == [
        ("read_file", True, "main"), ("write_file", False, "developpeur")]
    assert j.turns("autre") == []


def test_le_plus_recent_d_abord_et_limite(tmp_path):
    j = Journal(tmp_path / JOURNAL_FILE)
    now = datetime.now(UTC)
    for i in range(3):
        j.write(_turn(started=now + timedelta(seconds=i), model_ms=i))
    assert [t["model_ms"] for t in j.turns("s1", limit=2)] == [2, 1]


def test_fichier_en_600(tmp_path):
    j = Journal(tmp_path / "d" / JOURNAL_FILE)
    assert stat.S_IMODE(os.stat(j.db_path).st_mode) == 0o600
    assert stat.S_IMODE(os.stat(j.db_path.parent).st_mode) == 0o700


def test_metriques_par_outil_et_modele(tmp_path):
    j = Journal(tmp_path / JOURNAL_FILE)
    j.write(_turn(tools=[ToolRecord("read_file", "{}", 10, True),
                         ToolRecord("read_file", "{}", 30, False)], model_ms=200))
    j.write(_turn(session="s2", outcome="error", model_ms=400))
    old = datetime.now(UTC) - timedelta(days=30)
    j.write(_turn(started=old, tools=[ToolRecord("run_python", "{}", 999, True)]))
    m = j.metrics(days=7)
    assert m["tools"] == [{"tool": "read_file", "calls": 2, "failures": 1,
                           "mean_ms": 20, "max_ms": 30}]
    assert m["model"] == {"turns": 2, "mean_ms": 300, "max_ms": 400, "not_final": 1}


def test_purge_et_suppression_par_session(tmp_path):
    j = Journal(tmp_path / JOURNAL_FILE)
    old = datetime.now(UTC) - timedelta(days=40)
    j.write(_turn(session="vieux", started=old, tools=[ToolRecord("t", "{}", 1, True)]))
    j.write(_turn(session="s1"))
    j.write(_turn(session="s2"))
    assert j.purge(0) == 0
    assert j.purge(30) == 1
    assert j.delete_session("s1") == 1
    assert j.turns("s1") == [] and len(j.turns("s2")) == 1
    with sqlite3.connect(j.db_path) as conn:  # les outils partent avec leur tour
        assert conn.execute("SELECT COUNT(*) FROM tool_calls").fetchone()[0] == 0


def test_les_secrets_des_arguments_sont_masques_et_tronques(tmp_path):
    j = Journal(tmp_path / JOURNAL_FILE)
    rec = TurnRecorder(j, session_id="s1", project="/p", interface="web")
    rec.on_event(ToolCall(id="1", name="write_file",
                          arguments={"path": ".env", "content": f"OPENAI_API_KEY={KEY}"}))
    rec.on_event(ToolReturn(id="1", name="write_file", ok=True, content="ok"))
    rec.on_event(ToolCall(id="2", name="write_file", arguments={"content": "x" * 5000}))
    rec.on_event(ToolReturn(id="2", name="write_file", ok=True, content="ok"))
    rec.finish()
    tools = j.turns("s1")[0]["tools"]
    assert KEY not in tools[0]["arguments"] and ".env" in tools[0]["arguments"]
    assert len(tools[1]["arguments"]) <= MAX_ARGUMENT_CHARS + 1


def test_le_chronometre_separe_outils_et_modele(tmp_path):
    t = [0.0]
    j = Journal(tmp_path / JOURNAL_FILE)
    rec = TurnRecorder(j, session_id="s1", project="/p", interface="cli", clock=lambda: t[0])
    t[0] = 1.0
    rec.on_event(Token("…"))
    rec.on_event(ToolCall(id="1", name="read_file", arguments={}))
    t[0] = 1.25
    rec.on_event(ToolReturn(id="1", name="read_file", ok=True, content=""))
    rec.subagent_call("search_codebase", {"q": "x"}, False, 80, "explorateur")
    t[0] = 2.0
    rec.on_event(Done("final_answer"))
    rec.finish()
    rec.finish()  # une seule écriture
    [turn] = j.turns("s1")
    assert turn["model_ms"] == 1750 and turn["outcome"] == "final_answer"
    assert [(x["tool"], x["duration_ms"], x["agent"]) for x in turn["tools"]] == [
        ("read_file", 250, "main"), ("search_codebase", 80, "explorateur")]


def test_issue_forcee_interrompue(tmp_path):
    j = Journal(tmp_path / JOURNAL_FILE)
    rec = TurnRecorder(j, session_id="s1", project="/p", interface="web")
    rec.finish("interrupted")
    assert j.turns("s1")[0]["outcome"] == "interrupted"


def test_une_panne_du_journal_ne_leve_jamais(tmp_path, caplog):
    class Casse:
        def write(self, _):
            raise sqlite3.OperationalError("disque plein")

    rec = TurnRecorder(Casse(), session_id="s", project="/p", interface="web")
    rec.on_event(ToolCall(id="1", name="t", arguments={"a": object()}))
    rec.on_event(ToolReturn(id="1", name="t", ok=True, content=""))
    rec.finish()
    assert "tour non enregistré" in caplog.text
    TurnRecorder(None, session_id="s", project="/p", interface="web").finish()


def test_open_journal_renvoie_none_si_impossible(tmp_path):
    blocker = tmp_path / "fichier"
    blocker.write_text("x")
    assert open_journal(blocker) is None
