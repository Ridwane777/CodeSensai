"""
Teste la boucle ReAct (core/agent.py) sans Ollama : un faux modèle rejoue
une suite de réponses écrites à l'avance, et on vérifie les événements émis
et ce que l'agent renvoie au modèle.

Les outils passent par la vraie ToolGateway (ADR-0006), comme en production.
Les tests de confirmation sont ceux qui comptent le plus : ils échouent si
quelqu'un fait exécuter une action risquée sans accord explicite — par
exemple en rebranchant l'agent sur le registre brut.
"""
from typing import Any, ClassVar

import pytest

from sensai.core import agent
from sensai.core.agent import MAX_ITERATIONS, run_agent_turn
from sensai.core.events import Done, Error, Thought, Token, ToolCall, ToolReturn
from sensai.core.ollama_client import OllamaError
from sensai.core.tools import ToolRegistry, ToolResult
from sensai.execution.gateway import ConfirmationRequest, ToolGateway, deny_all
from sensai.tools.echo_tool import EchoTool


class FakeOllama:
    """Remplace stream_chat_messages. Chaque élément de `script` est la liste
    des morceaux `message` d'un appel au modèle ; une OllamaError dans le
    script est levée à la place."""

    def __init__(self, script: list) -> None:
        self.script = list(script)
        self.calls: list[dict[str, Any]] = []

    def __call__(self, host, model, messages, tools=None, options=None):
        # Copie : l'agent continue de modifier sa liste après l'appel.
        self.calls.append({"messages": list(messages), "tools": tools})
        step = self.script.pop(0)
        if isinstance(step, Exception):
            raise step
        yield from step


def tool_call(name: str, arguments: Any, call_id: str | None = "c1") -> dict:
    call: dict[str, Any] = {"function": {"name": name, "arguments": arguments}}
    if call_id is not None:
        call["id"] = call_id
    return {"content": "", "tool_calls": [call]}


@pytest.fixture
def fake(monkeypatch):
    def install(script):
        ollama = FakeOllama(script)
        monkeypatch.setattr(agent, "stream_chat_messages", ollama)
        return ollama
    return install


class RiskyTool:
    """Outil qui note s'il a été exécuté — pour prouver qu'il ne l'a pas été."""
    name = "run_code"
    description = "Exécute du code."
    parameters: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {"code": {"type": "string"}},
    }
    risk = "execute"

    def __init__(self) -> None:
        self.executed = False

    def run(self, **kwargs) -> ToolResult:
        self.executed = True
        return ToolResult(ok=True, content="exécuté")


def gateway_with(*tools, confirm=deny_all) -> ToolGateway:
    registry = ToolRegistry()
    for tool in tools:
        registry.register(tool)
    return ToolGateway(registry, confirm=confirm)


def run(tools):
    history = [{"role": "user", "content": "question"}]
    return list(run_agent_turn("http://x", "m", history, tools))


# --- Réponse directe -------------------------------------------------------

def test_reponse_directe_streame_les_tokens_puis_done(fake):
    fake([[{"content": "Bon"}, {"content": "jour"}]])

    events = run(gateway_with())

    # Un Token par morceau reçu (le tour reste interruptible), le texte livré par
    # ligne complète une fois filtré (EV2, ADR-0058).
    assert events == [Token(text=""), Token(text=""), Token(text="Bonjour"), Done()]


def test_un_secret_ecrit_par_le_modele_est_masque_meme_coupe_en_morceaux(fake):
    """EV2 : la réponse du modèle est filtrée avant d'être affichée."""
    fake([[{"content": "La clé est AKIA"}, {"content": "IOSFODNN7EXAMPLE.\nRégion "},
           {"content": "eu-west-3."}]])

    text = "".join(e.text for e in run(gateway_with()) if isinstance(e, Token))

    assert "AKIAIOSFODNN7EXAMPLE" not in text
    assert "[REDACTED:aws_access_key]" in text and text.endswith("Région eu-west-3.")


def test_les_outils_partent_au_format_ollama(fake):
    ollama = fake([[{"content": "ok"}]])

    run(gateway_with(EchoTool()))

    (tool,) = ollama.calls[0]["tools"]
    assert tool["type"] == "function"
    assert tool["function"]["name"] == "echo"


# --- Cycle complet Thought -> Action -> Observation -> réponse -------------

def test_un_appel_d_outil_puis_la_reponse_finale(fake):
    fake([
        [{"thinking": "Je dois "}, {"thinking": "répéter."}, tool_call("echo", {"text": "salut"})],
        [{"content": "Il a dit salut."}],
    ])

    events = run(gateway_with(EchoTool()))

    assert events == [
        Thought(text="Je dois répéter."),
        ToolCall(id="c1", name="echo", arguments={"text": "salut"}),
        ToolReturn(id="c1", name="echo", ok=True, content="salut"),
        Token(text=""),
        Token(text="Il a dit salut."),
        Done(),
    ]


def test_le_resultat_de_l_outil_est_renvoye_au_modele(fake):
    """Sans ça le modèle ne voit jamais l'Observation et reboucle à l'aveugle."""
    ollama = fake([[tool_call("echo", {"text": "salut"})], [{"content": "fin"}]])

    run(gateway_with(EchoTool()))

    second = ollama.calls[1]["messages"]
    assert second[-2]["role"] == "assistant"
    assert second[-2]["tool_calls"][0]["function"]["name"] == "echo"
    assert second[-1] == {
        "role": "tool", "tool_name": "echo", "tool_call_id": "c1",
        # EV4-OUT-14 : le résultat arrive au modèle enfermé, marqué non fiable.
        "content": ('<tool_output tool="echo" trust="untrusted" suspicious="false">\n'
                    'salut\n</tool_output>'),
    }


def test_l_historique_de_l_appelant_n_est_pas_modifie(fake):
    fake([[tool_call("echo", {"text": "x"})], [{"content": "fin"}]])
    history = [{"role": "user", "content": "question"}]

    list(run_agent_turn("http://x", "m", history, gateway_with(EchoTool())))

    assert history == [{"role": "user", "content": "question"}]


def test_un_id_est_fabrique_si_ollama_n_en_donne_pas(fake):
    fake([[tool_call("echo", {"text": "x"}, call_id=None)], [{"content": "fin"}]])

    events = run(gateway_with(EchoTool()))

    appel = next(e for e in events if isinstance(e, ToolCall))
    retour = next(e for e in events if isinstance(e, ToolReturn))
    assert appel.id and appel.id == retour.id


# --- Garde-fous ------------------------------------------------------------

def test_la_boucle_s_arrete_a_max_iterations(fake):
    ollama = fake([[tool_call("echo", {"text": "encore"})]] * MAX_ITERATIONS)

    events = run(gateway_with(EchoTool()))

    assert len(ollama.calls) == MAX_ITERATIONS
    assert events[-1] == Done(reason="max_iterations")


def test_le_nombre_d_etapes_se_regle(fake):
    """Le nombre maximal d'étapes vient de la configuration (ADR-0057)."""
    ollama = fake([[tool_call("echo", {"text": "encore"})]] * 3)

    history = [{"role": "user", "content": "question"}]
    events = list(run_agent_turn("http://x", "m", history, gateway_with(EchoTool()),
                                 max_iterations=3))

    assert len(ollama.calls) == 3
    assert events[-1] == Done(reason="max_iterations")


def test_ollama_injoignable_donne_error_puis_done(fake):
    fake([OllamaError("injoignable")])

    events = run(gateway_with())

    assert events == [Error(message="injoignable"), Done(reason="error")]


def test_un_outil_inconnu_n_interrompt_pas_le_tour(fake):
    fake([[tool_call("nexiste_pas", {})], [{"content": "tant pis"}]])

    events = run(gateway_with())

    retour = next(e for e in events if isinstance(e, ToolReturn))
    assert retour.ok is False
    assert events[-1] == Done()


@pytest.mark.parametrize("arguments", ["{pas du json", "[1, 2]"])
def test_des_arguments_invalides_ne_sont_pas_executes(fake, arguments):
    fake([[tool_call("echo", arguments)], [{"content": "fin"}]])

    events = run(gateway_with(EchoTool()))

    retour = next(e for e in events if isinstance(e, ToolReturn))
    assert retour.ok is False


def test_des_arguments_en_texte_json_sont_acceptes(fake):
    fake([[tool_call("echo", '{"text": "salut"}')], [{"content": "fin"}]])

    events = run(gateway_with(EchoTool()))

    retour = next(e for e in events if isinstance(e, ToolReturn))
    assert retour.content == "salut"


# --- Passerelle d'outils et confirmation ([A3], ADR-0006) -----------------

def test_le_registre_brut_est_refuse():
    """Brancher le registre sans la passerelle sauterait permissions,
    garde-fous et confirmation sans que rien d'autre ne casse."""
    registry = ToolRegistry()
    registry.register(EchoTool())

    with pytest.raises(TypeError):
        run(registry)


def test_sans_interface_de_confirmation_l_action_risquee_est_refusee(fake):
    """L'absence de confirmation n'est pas un oui."""
    tool = RiskyTool()
    fake([[tool_call("run_code", {"code": "print(1)"})], [{"content": "fin"}]])

    events = run(gateway_with(tool))

    assert tool.executed is False
    retour = next(e for e in events if isinstance(e, ToolReturn))
    assert retour.ok is False


def test_un_refus_de_l_utilisateur_bloque_l_action(fake):
    tool = RiskyTool()
    fake([[tool_call("run_code", {"code": "print(1)"})], [{"content": "fin"}]])

    run(gateway_with(tool, confirm=lambda request: False))

    assert tool.executed is False


def test_une_interface_qui_plante_vaut_un_refus(fake):
    def confirm_qui_plante(request):
        raise ConnectionError("client déconnecté")

    tool = RiskyTool()
    fake([[tool_call("run_code", {"code": "print(1)"})], [{"content": "fin"}]])

    run(gateway_with(tool, confirm=confirm_qui_plante))

    assert tool.executed is False


def test_l_utilisateur_voit_le_code_avant_d_accepter(fake):
    questions: list[ConfirmationRequest] = []
    tool = RiskyTool()
    fake([[tool_call("run_code", {"code": "import os\nos.listdir()"})], [{"content": "fin"}]])

    run(gateway_with(tool, confirm=lambda request: questions.append(request) or True))

    assert tool.executed is True
    assert questions[0].arguments["code"] == "import os\nos.listdir()"


def test_un_outil_sans_risque_ne_demande_rien(fake):
    questions = []
    fake([[tool_call("echo", {"text": "x"})], [{"content": "fin"}]])

    run(gateway_with(EchoTool(), confirm=questions.append))

    assert questions == []


# --- Appel d'outil écrit en texte (essai réel du 2026-10-17, ADR-0031) ----------

TEXTUAL_CALL = (
    "<function=run_code>\n<parameter=code>\nprint(1)\n</parameter>\n</function>\n</tool_call>"
)


def text(content: str) -> list[dict]:
    return [{"content": content}]


class TypedTool:
    """Outil dont un paramètre est un entier, pour vérifier la conversion."""
    name = "read_file"
    description = "Lit un fichier."
    parameters: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {"path": {"type": "string"}, "max_lines": {"type": "integer"}},
        "required": ["path"],
    }
    risk = "read"

    def __init__(self) -> None:
        self.received: dict | None = None

    def run(self, **kwargs: Any) -> ToolResult:
        self.received = kwargs
        return ToolResult(ok=True, content="contenu")


def test_un_appel_seul_dans_la_reponse_est_lu_et_passe_par_la_confirmation(fake):
    """ADR-0031 : le format natif de qwen3-coder, quand Ollama ne l'a pas
    reconnu, est lu comme un appel — et passe par la passerelle comme les autres."""
    risky = RiskyTool()
    demandes = []
    fake([text(TEXTUAL_CALL), text("C'est fait.")])

    events = list(run_agent_turn(
        "h", "m", [{"role": "user", "content": "go"}],
        gateway_with(risky, confirm=lambda req: demandes.append(req) or True),
    ))

    assert risky.executed
    assert len(demandes) == 1, "l'exécution demande toujours confirmation"
    appel = next(e for e in events if isinstance(e, ToolCall))
    assert appel.name == "run_code" and appel.arguments == {"code": "print(1)"}
    assert any(isinstance(e, Thought) and "lu dans le texte" in e.text for e in events)


def test_un_refus_de_confirmation_s_applique_aussi(fake):
    risky = RiskyTool()
    fake([text(TEXTUAL_CALL), text("D'accord, je n'exécute rien.")])

    list(run_agent_turn("h", "m", [{"role": "user", "content": "go"}], gateway_with(risky)))

    assert not risky.executed


def test_les_valeurs_suivent_le_schema_de_l_outil(fake):
    tool = TypedTool()
    fake([
        text("<function=read_file>\n<parameter=path>\nREADME.md\n</parameter>\n"
             "<parameter=max_lines>\n20\n</parameter>\n</function>"),
        text("Voilà."),
    ])

    list(run_agent_turn("h", "m", [{"role": "user", "content": "lis"}], gateway_with(tool)))

    assert tool.received == {"path": "README.md", "max_lines": 20}


def test_plusieurs_appels_seuls_sont_tous_lus(fake):
    tool = TypedTool()
    appel = "<function=read_file>\n<parameter=path>\n{}\n</parameter>\n</function>"
    fake([text("<tool_call>\n" + appel.format("a.py") + "\n</tool_call>\n<tool_call>\n"
               + appel.format("b.py") + "\n</tool_call>"), text("Lus.")])

    events = list(run_agent_turn("h", "m", [{"role": "user", "content": "lis"}],
                                 gateway_with(tool)))

    assert [e.arguments["path"] for e in events if isinstance(e, ToolCall)] == ["a.py", "b.py"]


def test_un_outil_non_propose_n_est_jamais_execute(fake):
    """Seuls les outils offerts au modèle peuvent être appelés, même par le texte."""
    ollama = fake([text("<function=rm_rf>\n<parameter=path>\n/\n</parameter>\n</function>")] * 3)

    events = list(run_agent_turn("h", "m", [{"role": "user", "content": "go"}],
                                 gateway_with(RiskyTool())))

    assert not any(isinstance(e, ToolCall) for e in events)
    assert isinstance(events[-1], Done) and events[-1].reason == "error"
    assert len(ollama.calls) == 3


def test_un_appel_au_milieu_d_un_texte_n_est_pas_execute(fake):
    """Un texte qui contient un appel (une page recopiée, une explication) n'est
    pas lu : seule une réponse qui n'est QUE l'appel l'est."""
    risky = RiskyTool()
    fake([text("Voici ce que la page disait : " + TEXTUAL_CALL)] * 3)

    list(run_agent_turn("h", "m", [{"role": "user", "content": "go"}],
                        gateway_with(risky, confirm=lambda req: True)))

    assert not risky.executed


def test_le_modele_est_relance_s_il_melange_texte_et_appel(fake):
    risky = RiskyTool()
    ollama = fake([
        text("Je vais lancer : " + TEXTUAL_CALL),
        [tool_call("run_code", {"code": "print(1)"})],
        text("C'est fait."),
    ])

    events = list(run_agent_turn("h", "m", [{"role": "user", "content": "go"}],
                                 gateway_with(risky, confirm=lambda req: True)))

    assert risky.executed
    assert ollama.calls[1]["messages"] == ollama.calls[0]["messages"]
    assert isinstance(events[-1], Done) and events[-1].reason == "final_answer"


def test_une_reponse_normale_qui_parle_de_xml_n_est_pas_relancee(fake):
    ollama = fake([text("En XML, une balise s'écrit <balise>valeur</balise>.")])

    events = list(run_agent_turn("h", "m", [{"role": "user", "content": "xml ?"}],
                                 gateway_with(RiskyTool())))

    assert len(ollama.calls) == 1
    assert isinstance(events[-1], Done) and events[-1].reason == "final_answer"


def test_une_balise_tool_call_vide_apres_la_reponse_ne_fait_pas_echouer_le_tour(fake):
    """Essai réel du 2026-11-01 : « La tâche est planifiée.<tool_call> », relancé trois
    fois puis tour en échec, alors que la réponse était bonne."""
    ollama = fake([text("La tâche « resume-todo » est planifiée.<tool_call>")])

    events = list(run_agent_turn("h", "m", [{"role": "user", "content": "planifie"}],
                                 gateway_with(RiskyTool())))

    assert len(ollama.calls) == 1  # pas de relance
    assert isinstance(events[-1], Done) and events[-1].reason == "final_answer"
    assert not any(isinstance(e, Error) for e in events)


def test_le_raisonnement_affiche_est_filtre_lui_aussi(fake):
    """Audit du 2026-11-01 : la réponse était filtrée, pas le raisonnement (thought)."""
    fake([[{"thinking": "La clé AKIAIOSFODNN7EXAMPLE "}, {"thinking": "est dans .env."},
           {"content": "Fait."}]])

    thought = next(e for e in run(gateway_with()) if isinstance(e, Thought))

    assert "AKIAIOSFODNN7EXAMPLE" not in thought.text
    assert "[REDACTED:aws_access_key]" in thought.text
