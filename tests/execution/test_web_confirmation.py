"""
Teste le broker de confirmation web (A3, issue #47) : seul `True` autorise, tout
le reste (délai, fermeture, panne, mauvais identifiant) refuse, et rien ne reste
en attente. Les attentes passent par des Event, pas par des sleep.
"""
import threading
from typing import Any, ClassVar

import pytest

from sensai.core.tools import ToolRegistry, ToolResult
from sensai.execution.gateway import REFUSED, ConfirmationRequest, ToolGateway
from sensai.execution.tool_policy import Risk, ToolPreferences
from sensai.execution.web_confirmation import WebConfirmationBroker

WAIT = 2.0  # borne de sécurité des attentes : un test qui l'atteint a échoué


def make_request(timeout_s: float = 0.3, **overrides: Any) -> ConfirmationRequest:
    base: dict[str, Any] = {
        "tool": "run_code",
        "risk": Risk.EXECUTE,
        "summary": "Exécuter print(1)",
        "arguments": {"code": "print(1)"},
        "timeout_s": timeout_s,
    }
    base.update(overrides)
    return ConfirmationRequest(**base)


class Recorder:
    """`emit` de test : garde les messages et signale le premier."""

    def __init__(self) -> None:
        self.messages: list[dict] = []
        self.first = threading.Event()
        self.seen = threading.Semaphore(0)

    def __call__(self, message: dict) -> None:
        self.messages.append(message)
        self.first.set()
        self.seen.release()


def run_in_thread(fn, *args) -> tuple[threading.Thread, list]:
    box: list = []
    thread = threading.Thread(target=lambda: box.append(fn(*args)), daemon=True)
    thread.start()
    return thread, box


def ask_async(broker: WebConfirmationBroker, request: ConfirmationRequest):
    return run_in_thread(broker.confirmer, request)


def join(thread: threading.Thread) -> None:
    thread.join(WAIT)
    assert not thread.is_alive(), "le confirmeur est resté bloqué"


# -- charge utile ----------------------------------------------------------------


def test_emitted_payload_is_exactly_the_documented_one():
    rec = Recorder()
    broker = WebConfirmationBroker(rec, id_factory=lambda: "confirm_abc")
    thread, box = ask_async(broker, make_request(timeout_s=1.5))
    assert rec.first.wait(WAIT)
    assert rec.messages == [
        {
            "type": "confirm_request",
            "id": "confirm_abc",
            "tool": "run_code",
            "risk": "execute",
            "summary": "Exécuter print(1)",
            "arguments": {"code": "print(1)"},
            "timeout_s": 1.5,
        }
    ]
    assert broker.resolve("confirm_abc", True) is True
    join(thread)
    assert box == [True]


def test_default_ids_are_prefixed_and_unique():
    rec = Recorder()
    broker = WebConfirmationBroker(rec)
    threads = [ask_async(broker, make_request())[0] for _ in range(2)]
    assert rec.seen.acquire(timeout=WAIT) and rec.seen.acquire(timeout=WAIT)
    ids = [m["id"] for m in rec.messages]
    assert len(set(ids)) == 2
    assert all(i.startswith("confirm_") and len(i) > len("confirm_") for i in ids)
    broker.close()
    for t in threads:
        join(t)


def test_confirmer_and_make_confirmer_are_the_same_callable():
    broker = WebConfirmationBroker(lambda m: None)
    assert broker.make_confirmer() == broker.confirmer


# -- réponses ----------------------------------------------------------------------


def test_true_approves():
    rec = Recorder()
    broker = WebConfirmationBroker(rec)
    thread, box = ask_async(broker, make_request())
    assert rec.first.wait(WAIT)
    assert broker.resolve(rec.messages[0]["id"], True) is True
    join(thread)
    assert box == [True]
    assert broker.pending_ids() == []


@pytest.mark.parametrize("answer", [False, 1, "true", "yes", None, 0, [], {}])
def test_anything_but_literal_true_refuses(answer):
    rec = Recorder()
    broker = WebConfirmationBroker(rec)
    thread, box = ask_async(broker, make_request())
    assert rec.first.wait(WAIT)
    # La réponse est bien prise en compte (True), mais elle vaut refus.
    assert broker.resolve(rec.messages[0]["id"], answer) is True
    join(thread)
    assert box == [False]
    assert broker.pending_ids() == []


def test_timeout_refuses_and_leaves_nothing_pending():
    broker = WebConfirmationBroker(lambda m: None, id_factory=lambda: "confirm_t")
    assert broker.confirmer(make_request(timeout_s=0.05)) is False
    assert broker.pending_ids() == []
    # Une réponse tardive n'a plus rien à réveiller.
    assert broker.resolve("confirm_t", True) is False


def test_pending_while_waiting_then_cleaned_up():
    rec = Recorder()
    broker = WebConfirmationBroker(rec, id_factory=lambda: "confirm_p")
    thread, _ = ask_async(broker, make_request())
    assert rec.first.wait(WAIT)
    assert broker.pending_ids() == ["confirm_p"]
    broker.resolve("confirm_p", False)
    join(thread)
    assert broker.pending_ids() == []


# -- identifiants inconnus, doublons, retards -----------------------------------


def test_unknown_id_returns_false_without_raising():
    broker = WebConfirmationBroker(lambda m: None)
    assert broker.resolve("confirm_nope", True) is False
    assert broker.resolve("", True) is False


@pytest.mark.parametrize("bad_id", [None, 42, ["x"], {"a": 1}, b"confirm_x"])
def test_non_string_ids_never_raise(bad_id):
    broker = WebConfirmationBroker(lambda m: None)
    assert broker.resolve(bad_id, True) is False


def test_duplicate_answer_first_one_wins():
    rec = Recorder()
    broker = WebConfirmationBroker(rec)
    thread, box = ask_async(broker, make_request())
    assert rec.first.wait(WAIT)
    confirm_id = rec.messages[0]["id"]
    assert broker.resolve(confirm_id, False) is True
    assert broker.resolve(confirm_id, True) is False  # trop tard : la première gagne
    join(thread)
    assert box == [False]


def test_late_answer_after_timeout_is_ignored():
    broker = WebConfirmationBroker(lambda m: None, id_factory=lambda: "confirm_late")
    assert broker.confirmer(make_request(timeout_s=0.05)) is False
    assert broker.resolve("confirm_late", True) is False
    assert broker.pending_ids() == []


# -- pannes ----------------------------------------------------------------------


def test_emit_raising_refuses_and_cleans_up():
    def boom(message: dict) -> None:
        raise RuntimeError("SSE fermé")

    broker = WebConfirmationBroker(boom, id_factory=lambda: "confirm_x")
    assert broker.confirmer(make_request(timeout_s=WAIT)) is False  # immédiat, pas d'attente
    assert broker.pending_ids() == []
    assert broker.resolve("confirm_x", True) is False


def test_id_factory_raising_refuses():
    def bad_factory() -> str:
        raise RuntimeError("panne")

    broker = WebConfirmationBroker(lambda m: None, id_factory=bad_factory)
    assert broker.confirmer(make_request()) is False
    assert broker.pending_ids() == []


def test_id_collision_refuses_without_hijacking_the_first_request():
    rec = Recorder()
    broker = WebConfirmationBroker(rec, id_factory=lambda: "confirm_same")
    thread, box = ask_async(broker, make_request())
    assert rec.first.wait(WAIT)
    assert broker.confirmer(make_request()) is False
    assert broker.pending_ids() == ["confirm_same"]
    assert broker.resolve("confirm_same", True) is True
    join(thread)
    assert box == [True]


def test_emit_that_answers_synchronously_does_not_deadlock():
    holder: dict[str, WebConfirmationBroker] = {}

    def auto_approve(message: dict) -> None:
        # Appelé depuis le thread de l'agent : resolve prend le verrou, qui ne
        # doit donc pas être tenu pendant emit.
        assert holder["broker"].resolve(message["id"], True) is True

    broker = WebConfirmationBroker(auto_approve)
    holder["broker"] = broker
    thread, box = ask_async(broker, make_request(timeout_s=WAIT))
    join(thread)
    assert box == [True]
    assert broker.pending_ids() == []


# -- fermeture ---------------------------------------------------------------------


def test_close_unblocks_waiter_with_a_refusal():
    rec = Recorder()
    broker = WebConfirmationBroker(rec)
    thread, box = ask_async(broker, make_request(timeout_s=WAIT))
    assert rec.first.wait(WAIT)
    broker.close()
    join(thread)
    assert box == [False]
    assert broker.pending_ids() == []
    assert broker.resolve(rec.messages[0]["id"], True) is False


def test_requests_after_close_refuse_immediately_without_emit():
    rec = Recorder()
    broker = WebConfirmationBroker(rec)
    broker.close()
    assert broker.confirmer(make_request(timeout_s=WAIT)) is False  # immédiat
    assert rec.messages == []
    assert broker.pending_ids() == []


def test_close_twice_is_harmless():
    broker = WebConfirmationBroker(lambda m: None)
    broker.close()
    broker.close()


# -- concurrence -------------------------------------------------------------------


def test_two_concurrent_requests_are_independent():
    rec = Recorder()
    broker = WebConfirmationBroker(rec)
    t1, b1 = ask_async(broker, make_request(tool="run_code", timeout_s=WAIT))
    assert rec.seen.acquire(timeout=WAIT)
    t2, b2 = ask_async(broker, make_request(tool="write_file", timeout_s=WAIT))
    assert rec.seen.acquire(timeout=WAIT)
    by_tool = {m["tool"]: m["id"] for m in rec.messages}
    assert sorted(broker.pending_ids()) == sorted(by_tool.values())

    assert broker.resolve(by_tool["write_file"], False) is True
    join(t2)
    assert b2 == [False]
    assert t1.is_alive()  # la première attend toujours
    assert broker.pending_ids() == [by_tool["run_code"]]

    assert broker.resolve(by_tool["run_code"], True) is True
    join(t1)
    assert b1 == [True]
    assert broker.pending_ids() == []


# -- intégration avec la passerelle ------------------------------------------


class CountingTool:
    name = "run_code"
    description = "outil de test"
    risk = "execute"
    parameters: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {"text": {"type": "string"}},
        "required": ["text"],
    }

    def __init__(self) -> None:
        self.runs = 0

    def run(self, **kwargs) -> ToolResult:
        self.runs += 1
        return ToolResult(ok=True, content=kwargs["text"])


def make_gateway(emit, timeout_s: float = 0.3):
    tool = CountingTool()
    registry = ToolRegistry()
    registry.register(tool)
    broker = WebConfirmationBroker(emit)
    gateway = ToolGateway(
        registry,
        preferences=ToolPreferences(confirm_timeout_s=timeout_s),
        confirm=broker.confirmer,
    )
    return tool, broker, gateway


def wait_until_nothing_pending(broker: WebConfirmationBroker) -> None:
    """Le thread d'attente de la passerelle peut survivre quelques ms à son délai."""
    done = threading.Event()
    for _ in range(int(WAIT / 0.01)):
        if not broker.pending_ids():
            return
        done.wait(0.01)
    raise AssertionError(f"demandes restées en attente : {broker.pending_ids()}")


def call_in_thread(gateway: ToolGateway):
    return run_in_thread(lambda: gateway.call("run_code", text="hi"))


def test_gateway_approve_runs_the_tool_once():
    rec = Recorder()
    tool, broker, gateway = make_gateway(rec, timeout_s=WAIT)
    thread, box = call_in_thread(gateway)
    assert rec.first.wait(WAIT)
    assert tool.runs == 0  # rien ne tourne avant la réponse
    assert broker.resolve(rec.messages[0]["id"], True) is True
    join(thread)
    assert box[0].ok is True
    assert tool.runs == 1


def test_gateway_refusal_does_not_run_the_tool_and_is_not_an_exception():
    rec = Recorder()
    tool, broker, gateway = make_gateway(rec, timeout_s=WAIT)
    thread, box = call_in_thread(gateway)
    assert rec.first.wait(WAIT)
    broker.resolve(rec.messages[0]["id"], False)
    join(thread)
    result = box[0]
    assert result.ok is False
    assert result.data == {"error": REFUSED}
    assert tool.runs == 0


def test_gateway_timeout_refuses_without_running_the_tool():
    tool, broker, gateway = make_gateway(lambda m: None, timeout_s=0.1)
    result = gateway.call("run_code", text="hi")
    assert result.ok is False
    assert result.data == {"error": REFUSED}
    assert tool.runs == 0
    wait_until_nothing_pending(broker)


def test_gateway_close_while_waiting_refuses_without_running_the_tool():
    rec = Recorder()
    tool, broker, gateway = make_gateway(rec, timeout_s=WAIT)
    thread, box = call_in_thread(gateway)
    assert rec.first.wait(WAIT)
    broker.close()
    join(thread)
    assert box[0].ok is False
    assert box[0].data == {"error": REFUSED}
    assert tool.runs == 0
    assert broker.pending_ids() == []


def test_gateway_after_close_refuses_without_emitting():
    rec = Recorder()
    tool, broker, gateway = make_gateway(rec, timeout_s=WAIT)
    broker.close()
    result = gateway.call("run_code", text="hi")
    assert result.data == {"error": REFUSED}
    assert tool.runs == 0
    assert rec.messages == []
