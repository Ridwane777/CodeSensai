"""End-to-end trial run of every feature with the real model (qwen3:8b by default).

One scenario per feature, taken from its user stories, played like a user would:
the `sensai` CLI (answers typed through a pipe), the `sensai-prompt`,
`sensai-eval` and `sensai-schedule` commands, and the `sensai-web` API. Each
scenario has an observable criterion (printed text, written file, HTTP
response) and its duration is measured. Everything happens in a throwaway
project (temporary directory) with its own `SENSAI_HOME`: neither the
repository nor ~/.sensai is touched.

Results are written as they come (a long trial run may be cut short):
    python scripts/essai_features.py --out docs/performance/data/features-qwen3-8b.json
    python scripts/essai_features.py --only T4,A3 --out /tmp/trial.json

Prerequisites: Ollama with the model and bge-m3; Docker and the
`python:3.12-slim` (T2) and `sensai-browser` (T3) images.

The prompts were translated from French after the published trial runs. Output
checks accept both the French and English UI labels.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import httpx

REPO = Path(__file__).resolve().parent.parent
BIN = Path(sys.executable).parent
FAKE_MCP = REPO / "tests" / "tools" / "fake_mcp_server.py"
CLI_TIMEOUT = 1800  # an agent turn on CPU can exceed 10 min

STATS = '''def moyenne(notes):
    """Mean of a list of grades."""
    return sum(notes) / len(notes)


def maximum(notes):
    return max(notes)
'''
TEST_STATS = '''from stats import moyenne


def test_moyenne():
    assert moyenne([10, 20]) == 15
'''
SCHEMA = {"type": "object",
          "properties": {"function": {"type": "string"}, "file": {"type": "string"}},
          "required": ["function", "file"]}
FEWSHOT = {"id": "ex-tests", "question": "How do I run this project's tests?",
           "answer": "Run `pytest -q` at the root: it finds tests/test_stats.py.",
           "sources": [], "notes": "few-shot example of the trial run"}


@dataclass
class Run:
    out: str
    seconds: float
    code: int | None


@dataclass
class Scenario:
    feature: str
    what: str
    play: Callable[["Trial"], tuple[bool, "Run"]]


class Trial:
    rag = False  # --rag: RAG stays on in every scenario
    """The throwaway project and the means to drive it."""

    def __init__(self, base: Path, model: str, host: str,
                 delegation_timeout: int | None = None) -> None:
        self.base, self.model, self.host = base, model, host
        self.project = base / "project"
        self.data = base / "data"
        self.project.mkdir()
        (self.project / "tests").mkdir()
        (self.project / "stats.py").write_text(STATS, encoding="utf-8")
        (self.project / "tests" / "test_stats.py").write_text(TEST_STATS, encoding="utf-8")
        (self.project / "schema.json").write_text(json.dumps(SCHEMA), encoding="utf-8")
        (self.project / "fewshot.jsonl").write_text(json.dumps(FEWSHOT, ensure_ascii=False) + "\n",
                                                    encoding="utf-8")
        config = json.loads((REPO / "config.json").read_text(encoding="utf-8"))
        config.update(model=model, host=host, share_links=True,
                      mcp_servers={"calc": {"command": sys.executable,
                                            "args": [str(FAKE_MCP), "normal"]}})
        if delegation_timeout:  # A2 on CPU: give sub-agents time for one call
            config["tools"] = {"tool_timeout_s": delegation_timeout,
                               "delegation_timeout_s": delegation_timeout}
        (self.project / "config.json").write_text(json.dumps(config, indent=2), encoding="utf-8")
        for cmd in (["git", "init", "-q"], ["git", "add", "."],
                    ["git", "-c", "user.name=trial", "-c", "user.email=trial@local",
                     "commit", "-qm", "init"]):
            subprocess.run(cmd, cwd=self.project, check=True)
        self.env = {**os.environ, "SENSAI_HOME": str(self.data), "NO_COLOR": "1",
                    "PYTHONUNBUFFERED": "1"}

    def run(self, argv: list[str], lines: list[str] = (), timeout: int | None = None) -> Run:
        timeout = timeout or CLI_TIMEOUT
        start = time.monotonic()
        try:
            p = subprocess.run(argv, cwd=self.project, env=self.env, text=True,
                               input="\n".join(lines) + "\n", capture_output=True,
                               timeout=timeout)
            out, code = p.stdout + p.stderr, p.returncode
        except subprocess.TimeoutExpired as exc:
            raw = exc.stdout or ""
            out = raw.decode(errors="replace") if isinstance(raw, bytes) else raw
            out, code = out + f"\n[TIMEOUT {timeout}s]", None
        return Run(out, round(time.monotonic() - start, 1), code)

    def chat(self, lines: list[str], *extra: str, new: bool = True) -> Run:
        argv = [str(BIN / "sensai"), "--model", self.model, "--host", self.host, *extra]
        if new:
            argv.append("--new-session")
        if not self.rag and not any(a.startswith("--rag") for a in extra):
            argv.append("--no-rag")  # RAG is only measured by R1/R2: too slow on CPU otherwise
        return self.run(argv, [*lines, "exit"])


def has(pattern: str, text: str) -> bool:
    return re.search(pattern, text, re.IGNORECASE | re.DOTALL) is not None


# --- CLI scenarios ----------------------------------------------------------------


def b1_a1(t: Trial):
    r = t.chat(["Read stats.py and tell me in one sentence what the moyenne function does."])
    # The CLI prints "Lecture(stats.py)" (or "Read(...)"), not the tool name
    # (trial run of 2026-11-06).
    read = has(r"read_file|Lecture\(|Read\(", r.out)
    return read and has(r"moyenne|mean|average|sum|somme|divi", r.out), r


def t4_write(t: Trial):
    r = t.chat(["Create the file notes.txt containing exactly the word hello.", "y"])
    f = t.project / "notes.txt"
    return f.exists() and "hello" in f.read_text(encoding="utf-8"), r


def a3_refuse(t: Trial):
    r = t.chat(["Create the file refused.txt containing the word no.", "n"])
    refused = has(r"confirm|refus|annul|cancel|declin", r.out)
    return not (t.project / "refused.txt").exists() and refused, r


def t2_sandbox(t: Trial):
    r = t.chat(["Use run_code to run in Python: print(6 * 7)", "y"])
    return has(r"run_code", r.out) and has(r"\b42\b", r.out), r


def t3_web(t: Trial):
    r = t.chat(["Search the web for the official website of the Python language "
                "and give its address.",
                "y"])
    return has(r"web_search", r.out) and has(r"python\.org", r.out), r


def t1_mcp(t: Trial):
    r = t.chat(["Use the calc MCP tool to add 19 and 23.", "y"])
    return has(r"calc", r.out) and has(r"\b42\b", r.out), r


def t5_structured(t: Trial):
    r = t.chat(["/structured schema.json Which function of this project computes a mean, "
                "and in which file?"])
    m = re.search(r"\{[^{}]*\"function\"[^{}]*\}", r.out)
    return bool(m) and "moyenne" in m.group(0) and "stats.py" in m.group(0), r


def a2_team(t: Trial):
    r = t.chat(["Use team_task: moyenne([]) must raise ValueError; add a test for this "
                "case.", "y", "y", "y", "y"])
    tests = subprocess.run([sys.executable, "-m", "pytest", "-q"], cwd=t.project,
                           capture_output=True, text=True)
    ok = has(r"team_task", r.out) and "ValueError" in (t.project / "stats.py").read_text()
    return ok, Run(r.out + "\n[pytest] " + tests.stdout[-300:], r.seconds, r.code)


def m1_session(t: Trial):
    a = t.chat(["Remember this game password: ANANAS. Just answer OK."])
    b = t.chat(["Which game password did I give you earlier?"], new=False)
    return has(r"ananas", b.out), Run(a.out + "\n----\n" + b.out, a.seconds + b.seconds, b.code)


def m2_context(t: Trial):
    r = t.chat(["/context"])
    return has(r"num_ctx|token|budget", r.out), r


def m3_profile(t: Trial):
    r = t.chat(["/remember This project uses pytest for its tests.", "/profile"])
    return has(r"pytest", r.out), r


def m4_state(t: Trial):
    r = t.chat(["/state"])
    return has(r"SENSAI\.md|\u00e9tat|state", r.out), r


def r1_r2_rag(t: Trial):
    r = t.chat(["In which file is the maximum function defined?"], "--rag-model", "bge-m3")
    return has(r"stats\.py", r.out), r


def a6_cache(t: Trial):
    q = "What does maximum([3, 9, 4]) return? Answer with the number only."
    a = t.chat([q], "--cache")
    b = t.chat([q], "--cache")
    note = f"1st call {a.seconds}s, 2nd call {b.seconds}s"
    return has(r"cache", b.out) and b.seconds < a.seconds, \
        Run(a.out + "\n----\n" + b.out + "\n" + note, a.seconds + b.seconds, b.code)


def a7_fewshot(t: Trial):
    r = t.chat(["How do I run the tests of this project?"],
               "--fewshot-examples", "fewshot.jsonl")
    return has(r"pytest", r.out) and has(r"ex-tests|exemple|example", r.out), r


def a5_persona(t: Trial):
    r = t.chat(["/persona list"])
    return has(r"\* \w+ - ", r.out), r


def ev2_secret(t: Trial):
    r = t.chat(["Without using any tool, copy exactly this example line from the "
                "AWS documentation: AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE"])
    # The prompt echoes the typed text on screen: only look at the answer.
    answer = r.out.split("AKIAIOSFODNN7EXAMPLE", 1)[-1]
    return "AKIAIOSFODNN7EXAMPLE" not in answer and has(r"REDACTED", answer), r


# --- Standalone commands ------------------------------------------------------------------


def a4_prompts(t: Trial):
    p = [str(BIN / "sensai-prompt"), "--dir", str(REPO / "prompts")]
    r = t.run([*p, "history", "system"])
    c = t.run([*p, "check"])
    return r.code == 0 and c.code == 0 and has(r"v3", r.out), Run(r.out + c.out, r.seconds,
                                                                     r.code)


def ev1_eval(t: Trial):
    out = t.base / "ev1.json"
    r = t.run([str(BIN / "sensai-eval"), "run", "--dataset",
               str(REPO / "datasets" / "eval" / "ev1_sample.jsonl"), "--out", str(out),
               "--judge-model", t.model, "--host", t.host])
    return r.code == 0 and out.exists(), Run(r.out[-2000:], r.seconds, r.code)


def ev4_adversarial(t: Trial):
    r = t.run([sys.executable, str(REPO / "scripts" / "adversarial_run.py"), "--out",
               str(t.base / "ev4.md")])
    return r.code == 0, r


def x5_schedule(t: Trial):
    s = [str(BIN / "sensai-schedule"), "--data-dir", str(t.data), "--model", t.model,
         "--host", t.host]
    a = t.run([*s, "add", "resume", "--every", "1d", "--tools", "read_file",
               "--prompt", "Read stats.py and list its functions in one line."])
    r = t.run([*s, "run", "resume"])
    h = t.run([*s, "history", "resume"])
    ok = a.code == 0 and r.code == 0 and has(r"moyenne|maximum", r.out + h.out)
    return ok, Run(a.out + r.out + h.out, a.seconds + r.seconds, r.code)


# --- Web --------------------------------------------------------------------------------


class Web:
    def __init__(self, t: Trial, port: int = 8765) -> None:
        self.proc = subprocess.Popen([str(BIN / "sensai-web"), "--port", str(port)],
                                     cwd=t.project, env=t.env, text=True,
                                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        token, deadline = None, time.monotonic() + 120
        while token is None and time.monotonic() < deadline:
            line = self.proc.stdout.readline()
            m = re.search(r"(?:Access token|Jeton d'acc\u00e8s).*: (\S+)", line)
            token = m.group(1) if m else None
        if token is None:
            raise RuntimeError("sensai-web did not print an access token")
        self.http = httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=CLI_TIMEOUT,
                                 headers={"Authorization": f"Bearer {token}"})
        for _ in range(60):
            try:
                if self.http.get("/api/health").status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(1)

    def session(self) -> str:
        return self.http.post("/api/sessions", json={}).json()["session_id"]

    def send(self, sid: str, text: str, on_event=None) -> list[dict]:
        events = []
        with self.http.stream("POST", f"/api/sessions/{sid}/messages",
                              json={"content": text}) as r:
            for line in r.iter_lines():
                if line.startswith("data: "):
                    ev = json.loads(line[6:])
                    events.append(ev)
                    if on_event:
                        on_event(sid, ev)
        return events

    def close(self) -> None:
        self.proc.terminate()
        self.proc.wait(timeout=30)


def text_of(events: list[dict]) -> str:
    tokens = "".join(e.get("text", "") for e in events if e.get("type") == "token")
    return tokens + " | events: " + " ".join(sorted({e.get("type", "?") for e in events}))


def web_scenarios(w: Web) -> list[Scenario]:
    def timed(sid: str, text: str, on_event=None) -> tuple[list[dict], float]:
        start = time.monotonic()
        ev = w.send(sid, text, on_event)
        return ev, round(time.monotonic() - start, 1)

    def x1(t):
        ev, s = timed(w.session(), "Read stats.py and say in one sentence what maximum does.")
        done = any(e.get("type") == "done" for e in ev)
        return done and has(r"max", text_of(ev)), Run(text_of(ev), s, 0)

    def a3_web(t):
        def approve(sid, e):
            if e.get("type") == "confirm_request":
                w.http.post(f"/api/sessions/{sid}/confirm",
                            json={"confirm_id": e["confirm_id"], "approved": True})

        ev, s = timed(w.session(), "Create the file web.txt containing the word web.", approve)
        asked = any(e.get("type") == "confirm_request" for e in ev)
        ok = (t.project / "web.txt").exists() and asked
        return ok, Run(text_of(ev), s, 0)

    def x4(t):
        def values_of(e):
            values = {}
            for f in e.get("fields") or []:
                if f["kind"] == "choice":
                    values[f["id"]] = next((o for o in f["options"] if "rust" in o.lower()),
                                           f["options"][0])
                else:
                    values[f["id"]] = True if f["kind"] == "toggle" else "Rust"
            return values

        def answer(sid, e):
            if e.get("type") == "question":
                w.http.post(f"/api/sessions/{sid}/answer",
                            json={"question_id": e["question_id"], "values": values_of(e)})

        chosen = []

        def answer_and_note(sid, e):
            answer(sid, e)
            if e.get("type") == "question":
                chosen.extend(str(v) for v in values_of(e).values() if v is not True)

        ev, s = timed(w.session(), "Use ask_user to ask me for my favorite "
                                   "programming language in a form, then repeat my "
                                   "answer.", answer_and_note)
        # The model picks the options itself: check that the submitted value comes back.
        ok = bool(chosen) and all(has(re.escape(c), text_of(ev)) for c in chosen)
        return ok, Run(text_of(ev) + "\n" + json.dumps([e for e in ev if e.get("type") ==
                                                        "question"], ensure_ascii=False), s, 0)

    def x2(t):
        sid = w.session()
        w.send(sid, "Just answer: hello.")
        # Fork after the 1st question: the new session only has that one.
        fork = w.http.post(f"/api/sessions/{sid}/fork", json={"at_message": 1})
        if fork.status_code != 201:
            return False, Run(fork.text, 0, fork.status_code)
        copy = w.http.get(f"/api/sessions/{fork.json()['session_id']}")
        return has(r"hello", copy.text), Run(fork.text + "\n" + copy.text[:500], 0, 201)

    def x3(t):
        sid = w.session()
        w.send(sid, "Just answer: hello.")
        exp = w.http.get(f"/api/sessions/{sid}/export")
        share = w.http.post(f"/api/sessions/{sid}/share", json={})
        ok = exp.status_code == 200 and share.status_code == 201
        return ok, Run(exp.text[:300] + "\n" + share.text, 0, share.status_code)

    def ev3(t):
        sid = w.session()
        w.send(sid, "Just answer: hello.")
        m = w.http.get("/api/journal/metrics")
        j = w.http.get("/api/journal", params={"session": sid})
        ok = has(r"\"turns\":\s*[1-9]", m.text) and has(r"\"turns\":\s*\[\s*\{", j.text)
        return ok, Run(m.text[:800] + "\n" + j.text[:800], 0, j.status_code)

    def a5_web(t):
        p = w.http.get("/api/personas")
        return p.status_code == 200 and len(p.json()) > 0, Run(p.text[:500], 0, p.status_code)

    return [
        Scenario("X1", "web: a full streamed turn (SSE)", x1),
        Scenario("A3-web", "web: confirmation approved through the API", a3_web),
        Scenario("X4", "web: ask_user form filled through the API", x4),
        Scenario("X2", "web: forking a conversation", x2),
        Scenario("X3", "web: export and share link", x3),
        Scenario("EV3", "web: turn log and metrics", ev3),
        Scenario("A5-web", "web: list of personas", a5_web),
    ]


CLI = [
    Scenario("B1/A1", "read a file and explain it (ReAct loop + read_file)", b1_a1),
    Scenario("T4", "write a file after confirmation", t4_write),
    Scenario("A3", "refuse a write: nothing is written", a3_refuse),
    Scenario("T2", "run code in the Docker sandbox", t2_sandbox),
    Scenario("T3", "isolated web search", t3_web),
    Scenario("T1", "call a tool from an MCP server", t1_mcp),
    Scenario("T5", "JSON answer matching a schema (/structured)", t5_structured),
    Scenario("M1", "resume the session and recall a piece of information", m1_session),
    Scenario("M2", "/context: prompt and budget sent", m2_context),
    Scenario("M3", "/remember then /profile", m3_profile),
    Scenario("M4", "/state: state document", m4_state),
    Scenario("R1/R2", "RAG: find the file that defines a function", r1_r2_rag),
    Scenario("A6", "semantic cache: 2nd question served faster", a6_cache),
    Scenario("A7", "few-shot: the close example is used", a7_fewshot),
    Scenario("A5", "/persona list", a5_persona),
    Scenario("EV2", "an AWS key written by the model is masked", ev2_secret),
    Scenario("A4", "sensai-prompt history + check", a4_prompts),
    Scenario("EV4", "adversarial corpus (no model)", ev4_adversarial),
    Scenario("X5", "scheduled task added then run", x5_schedule),
    Scenario("EV1", "LLM judge evaluation on ev1_sample", ev1_eval),
    Scenario("A2", "team_task: explorer → developer → reviewer", a2_team),
]


def main() -> None:
    global CLI_TIMEOUT
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--model", default="qwen3:8b")
    parser.add_argument("--host", default="http://localhost:11434")
    parser.add_argument("--only", help="features to play, comma-separated")
    parser.add_argument("--no-web", action="store_true")
    parser.add_argument("--rag", action="store_true",
                        help="keep RAG on in every scenario "
                             "(off by default, except R1/R2)")
    parser.add_argument("--delegation-timeout", type=int,
                        help="sub-agent timeout (tools section of config.json), in seconds")
    parser.add_argument("--scenario-timeout", type=int, default=CLI_TIMEOUT,
                        help="maximum duration of a CLI scenario, in seconds")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    only = set(args.only.split(",")) if args.only else None

    base = Path(tempfile.mkdtemp(prefix="sensai-trial-"))
    CLI_TIMEOUT = args.scenario_timeout
    t = Trial(base, args.model, args.host, args.delegation_timeout)
    t.rag = args.rag
    report = {"date": date.today().isoformat(), "model": args.model,
              "delegation_timeout": args.delegation_timeout, "rag": args.rag, "results": []}

    def record(s: Scenario) -> None:
        print(f"[{s.feature}] {s.what} …", flush=True)
        try:
            ok, run = s.play(t)
        except Exception as exc:  # a broken scenario must not stop the others
            ok, run = False, Run(f"{type(exc).__name__}: {exc}", 0, None)
        print(f"  {'OK' if ok else 'FAIL'} in {run.seconds}s", flush=True)
        report["results"].append({"feature": s.feature, "what": s.what, "ok": ok,
                                  "seconds": run.seconds, "exit": run.code,
                                  "output": run.out[-3000:]})
        args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    try:
        for s in CLI:
            if only is None or s.feature in only:
                record(s)
        if not args.no_web:
            w = Web(t)
            try:
                for s in web_scenarios(w):
                    if only is None or s.feature in only:
                        record(s)
            finally:
                w.close()
    finally:
        shutil.rmtree(base, ignore_errors=True)
    passed = sum(r["ok"] for r in report["results"])
    print(f"{passed}/{len(report['results'])} scenarios passed -> {args.out}")


if __name__ == "__main__":
    main()
