"""Essai de bout en bout de chaque feature avec le vrai modèle (qwen3:8b par défaut).

Un scénario par feature, tiré de ses user stories, joué comme un utilisateur :
le CLI `sensai` (réponses tapées dans un tube), les commandes `sensai-prompt`,
`sensai-eval`, `sensai-schedule`, et l'API de `sensai-web`. Chaque scénario a
un critère observable (texte affiché, fichier écrit, réponse HTTP) et sa durée
est mesurée. Tout se passe dans un projet jetable (dossier temporaire) avec
son propre `SENSAI_HOME` : ni le dépôt ni ~/.sensai ne sont touchés.

Les résultats sont écrits au fil de l'eau (un essai long peut être coupé) :
    python scripts/essai_features.py --out docs/performance/data/features-qwen3-8b.json
    python scripts/essai_features.py --only T4,A3 --out /tmp/essai.json

Prérequis : Ollama avec le modèle et bge-m3 ; Docker et les images
`python:3.12-slim` (T2) et `sensai-browser` (T3).
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
CLI_TIMEOUT = 1800  # un tour d'agent sur CPU peut dépasser 10 min

STATS = '''def moyenne(notes):
    """Moyenne d'une liste de notes."""
    return sum(notes) / len(notes)


def maximum(notes):
    return max(notes)
'''
TEST_STATS = '''from stats import moyenne


def test_moyenne():
    assert moyenne([10, 20]) == 15
'''
SCHEMA = {"type": "object",
          "properties": {"fonction": {"type": "string"}, "fichier": {"type": "string"}},
          "required": ["fonction", "fichier"]}
FEWSHOT = {"id": "ex-tests", "question": "Comment lancer les tests de ce projet ?",
           "answer": "Lance `pytest -q` à la racine : il trouve tests/test_stats.py.",
           "sources": [], "notes": "exemple few-shot de l'essai"}


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
    """Le projet jetable et les moyens de le piloter."""

    def __init__(self, base: Path, model: str, host: str,
                 delegation_timeout: int | None = None) -> None:
        self.base, self.model, self.host = base, model, host
        self.project = base / "projet"
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
        if delegation_timeout:  # A2 sur CPU : laisser aux sous-agents le temps d'un appel
            config["tools"] = {"tool_timeout_s": delegation_timeout,
                               "delegation_timeout_s": delegation_timeout}
        (self.project / "config.json").write_text(json.dumps(config, indent=2), encoding="utf-8")
        for cmd in (["git", "init", "-q"], ["git", "add", "."],
                    ["git", "-c", "user.name=essai", "-c", "user.email=essai@local",
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
        if not any(a.startswith("--rag") for a in extra):
            argv.append("--no-rag")  # le RAG n'est mesuré que par R1/R2 : sinon trop lent sur CPU
        return self.run(argv, [*lines, "exit"])


def has(pattern: str, text: str) -> bool:
    return re.search(pattern, text, re.IGNORECASE | re.DOTALL) is not None


# --- Scénarios CLI ----------------------------------------------------------------


def b1_a1(t: Trial):
    r = t.chat(["Lis stats.py et dis-moi en une phrase ce que fait la fonction moyenne."])
    return has(r"read_file", r.out) and has(r"moyenne|somme|divis", r.out), r


def t4_write(t: Trial):
    r = t.chat(["Crée le fichier notes.txt contenant exactement le mot bonjour.", "o"])
    f = t.project / "notes.txt"
    return f.exists() and "bonjour" in f.read_text(encoding="utf-8"), r


def a3_refuse(t: Trial):
    r = t.chat(["Crée le fichier refus.txt contenant le mot non.", "n"])
    return not (t.project / "refus.txt").exists() and has(r"confirm|refus|annul", r.out), r


def t2_sandbox(t: Trial):
    r = t.chat(["Utilise run_code pour exécuter en Python : print(6 * 7)", "o"])
    return has(r"run_code", r.out) and has(r"\b42\b", r.out), r


def t3_web(t: Trial):
    r = t.chat(["Cherche sur le web le site officiel du langage Python et donne son adresse.",
                "o"])
    return has(r"web_search", r.out) and has(r"python\.org", r.out), r


def t1_mcp(t: Trial):
    r = t.chat(["Utilise l'outil MCP calc pour additionner 19 et 23.", "o"])
    return has(r"calc", r.out) and has(r"\b42\b", r.out), r


def t5_structured(t: Trial):
    r = t.chat(["/structured schema.json Quelle fonction de ce projet calcule une moyenne, "
                "et dans quel fichier ?"])
    m = re.search(r"\{[^{}]*\"fonction\"[^{}]*\}", r.out)
    return bool(m) and "moyenne" in m.group(0) and "stats.py" in m.group(0), r


def a2_team(t: Trial):
    r = t.chat(["Utilise team_task : moyenne([]) doit lever ValueError ; ajoute un test pour ce "
                "cas.", "o", "o", "o", "o"])
    tests = subprocess.run([sys.executable, "-m", "pytest", "-q"], cwd=t.project,
                           capture_output=True, text=True)
    ok = has(r"team_task", r.out) and "ValueError" in (t.project / "stats.py").read_text()
    return ok, Run(r.out + "\n[pytest] " + tests.stdout[-300:], r.seconds, r.code)


def m1_session(t: Trial):
    a = t.chat(["Retiens ce mot de passe de jeu : ANANAS. Réponds juste OK."])
    b = t.chat(["Quel mot de passe de jeu t'ai-je donné tout à l'heure ?"], new=False)
    return has(r"ananas", b.out), Run(a.out + "\n----\n" + b.out, a.seconds + b.seconds, b.code)


def m2_context(t: Trial):
    r = t.chat(["/context"])
    return has(r"num_ctx|token|budget", r.out), r


def m3_profile(t: Trial):
    r = t.chat(["/remember Ce projet utilise pytest pour les tests.", "/profile"])
    return has(r"pytest", r.out), r


def m4_state(t: Trial):
    r = t.chat(["/state"])
    return has(r"SENSAI\.md|état|state", r.out), r


def r1_r2_rag(t: Trial):
    r = t.chat(["Dans quel fichier est définie la fonction maximum ?"], "--rag-model", "bge-m3")
    return has(r"stats\.py", r.out), r


def a6_cache(t: Trial):
    q = "Que renvoie maximum([3, 9, 4]) ? Réponds juste par le nombre."
    a = t.chat([q], "--cache")
    b = t.chat([q], "--cache")
    note = f"1er appel {a.seconds}s, 2e appel {b.seconds}s"
    return has(r"cache", b.out) and b.seconds < a.seconds, \
        Run(a.out + "\n----\n" + b.out + "\n" + note, a.seconds + b.seconds, b.code)


def a7_fewshot(t: Trial):
    r = t.chat(["Comment je lance les tests de ce projet ?"],
               "--fewshot-examples", "fewshot.jsonl")
    return has(r"pytest", r.out) and has(r"ex-tests|exemple", r.out), r


def a5_persona(t: Trial):
    r = t.chat(["/persona list"])
    return has(r"\* \w+ — ", r.out), r


def ev2_secret(t: Trial):
    r = t.chat(["Sans utiliser d'outil, recopie exactement cette ligne d'exemple de la "
                "documentation AWS : AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE"])
    # Le texte tapé est renvoyé à l'écran par l'invite : on ne regarde que la réponse.
    answer = r.out.split("AKIAIOSFODNN7EXAMPLE", 1)[-1]
    return "AKIAIOSFODNN7EXAMPLE" not in answer and has(r"REDACTED", answer), r


# --- Commandes à part ------------------------------------------------------------------


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
               "--prompt", "Lis stats.py et liste ses fonctions en une ligne."])
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
            m = re.search(r"Jeton d'accès.*: (\S+)", self.proc.stdout.readline())
            token = m.group(1) if m else None
        if token is None:
            raise RuntimeError("sensai-web n'a pas donné de jeton")
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
    return tokens + " | événements : " + " ".join(sorted({e.get("type", "?") for e in events}))


def web_scenarios(w: Web) -> list[Scenario]:
    def timed(sid: str, text: str, on_event=None) -> tuple[list[dict], float]:
        start = time.monotonic()
        ev = w.send(sid, text, on_event)
        return ev, round(time.monotonic() - start, 1)

    def x1(t):
        ev, s = timed(w.session(), "Lis stats.py et dis en une phrase ce que fait maximum.")
        done = any(e.get("type") == "done" for e in ev)
        return done and has(r"max", text_of(ev)), Run(text_of(ev), s, 0)

    def a3_web(t):
        def approve(sid, e):
            if e.get("type") == "confirm_request":
                w.http.post(f"/api/sessions/{sid}/confirm",
                            json={"confirm_id": e["confirm_id"], "approved": True})

        ev, s = timed(w.session(), "Crée le fichier web.txt contenant le mot web.", approve)
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

        ev, s = timed(w.session(), "Utilise ask_user pour me demander mon langage de "
                                   "programmation préféré dans un formulaire, puis répète ma "
                                   "réponse.", answer_and_note)
        # Le modèle choisit lui-même les options : on vérifie que la valeur envoyée revient.
        ok = bool(chosen) and all(has(re.escape(c), text_of(ev)) for c in chosen)
        return ok, Run(text_of(ev) + "\n" + json.dumps([e for e in ev if e.get("type") ==
                                                        "question"], ensure_ascii=False), s, 0)

    def x2(t):
        sid = w.session()
        w.send(sid, "Réponds juste : bonjour.")
        # Bifurquer après la 1re question : la nouvelle session n'a qu'elle.
        fork = w.http.post(f"/api/sessions/{sid}/fork", json={"at_message": 1})
        if fork.status_code != 201:
            return False, Run(fork.text, 0, fork.status_code)
        copy = w.http.get(f"/api/sessions/{fork.json()['session_id']}")
        return has(r"bonjour", copy.text), Run(fork.text + "\n" + copy.text[:500], 0, 201)

    def x3(t):
        sid = w.session()
        w.send(sid, "Réponds juste : bonjour.")
        exp = w.http.get(f"/api/sessions/{sid}/export")
        share = w.http.post(f"/api/sessions/{sid}/share", json={})
        ok = exp.status_code == 200 and share.status_code == 201
        return ok, Run(exp.text[:300] + "\n" + share.text, 0, share.status_code)

    def ev3(t):
        sid = w.session()
        w.send(sid, "Réponds juste : bonjour.")
        m = w.http.get("/api/journal/metrics")
        j = w.http.get("/api/journal", params={"session": sid})
        ok = has(r"\"turns\":\s*[1-9]", m.text) and has(r"\"turns\":\s*\[\s*\{", j.text)
        return ok, Run(m.text[:800] + "\n" + j.text[:800], 0, j.status_code)

    def a5_web(t):
        p = w.http.get("/api/personas")
        return p.status_code == 200 and len(p.json()) > 0, Run(p.text[:500], 0, p.status_code)

    return [
        Scenario("X1", "web : un tour complet en streaming (SSE)", x1),
        Scenario("A3-web", "web : confirmation approuvée par l'API", a3_web),
        Scenario("X4", "web : formulaire ask_user rempli par l'API", x4),
        Scenario("X2", "web : bifurcation d'une conversation (fork)", x2),
        Scenario("X3", "web : export et lien de partage", x3),
        Scenario("EV3", "web : journal des tours et métriques", ev3),
        Scenario("A5-web", "web : liste des personas", a5_web),
    ]


CLI = [
    Scenario("B1/A1", "lire un fichier et l'expliquer (boucle ReAct + read_file)", b1_a1),
    Scenario("T4", "écrire un fichier après confirmation", t4_write),
    Scenario("A3", "refuser une écriture : rien n'est écrit", a3_refuse),
    Scenario("T2", "exécuter du code dans la sandbox Docker", t2_sandbox),
    Scenario("T3", "recherche web isolée", t3_web),
    Scenario("T1", "appeler un outil d'un serveur MCP", t1_mcp),
    Scenario("T5", "réponse JSON conforme à un schéma (/structured)", t5_structured),
    Scenario("M1", "reprendre la session et retrouver une information", m1_session),
    Scenario("M2", "/context : prompt et budget envoyés", m2_context),
    Scenario("M3", "/remember puis /profile", m3_profile),
    Scenario("M4", "/state : document d'état", m4_state),
    Scenario("R1/R2", "RAG : trouver le fichier qui définit une fonction", r1_r2_rag),
    Scenario("A6", "cache sémantique : 2e question servie plus vite", a6_cache),
    Scenario("A7", "few-shot : l'exemple proche est utilisé", a7_fewshot),
    Scenario("A5", "/persona list", a5_persona),
    Scenario("EV2", "une clé AWS écrite par le modèle est masquée", ev2_secret),
    Scenario("A4", "sensai-prompt history + check", a4_prompts),
    Scenario("EV4", "corpus adversarial (sans modèle)", ev4_adversarial),
    Scenario("X5", "tâche planifiée ajoutée puis lancée", x5_schedule),
    Scenario("EV1", "évaluation par juge LLM sur ev1_sample", ev1_eval),
    Scenario("A2", "team_task : explorateur → développeur → relecteur", a2_team),
]


def main() -> None:
    global CLI_TIMEOUT
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--model", default="qwen3:8b")
    parser.add_argument("--host", default="http://localhost:11434")
    parser.add_argument("--only", help="features à jouer, séparées par des virgules")
    parser.add_argument("--no-web", action="store_true")
    parser.add_argument("--delegation-timeout", type=int,
                        help="délai des sous-agents (section tools de config.json), en secondes")
    parser.add_argument("--scenario-timeout", type=int, default=CLI_TIMEOUT,
                        help="durée maximale d'un scénario CLI, en secondes")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    only = set(args.only.split(",")) if args.only else None

    base = Path(tempfile.mkdtemp(prefix="sensai-essai-"))
    CLI_TIMEOUT = args.scenario_timeout
    t = Trial(base, args.model, args.host, args.delegation_timeout)
    report = {"date": date.today().isoformat(), "model": args.model,
              "delegation_timeout": args.delegation_timeout, "results": []}

    def record(s: Scenario) -> None:
        print(f"[{s.feature}] {s.what} …", flush=True)
        try:
            ok, run = s.play(t)
        except Exception as exc:  # un scénario cassé ne doit pas arrêter les autres
            ok, run = False, Run(f"{type(exc).__name__}: {exc}", 0, None)
        print(f"  {'OK' if ok else 'ÉCHEC'} en {run.seconds}s", flush=True)
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
    print(f"{passed}/{len(report['results'])} scénarios réussis -> {args.out}")


if __name__ == "__main__":
    main()
