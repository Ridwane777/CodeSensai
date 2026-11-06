"""
Point d'entrée du Base Loop : chatbot CLI, streaming, historique de session,
prompt système chargé depuis un fichier, gestion d'erreurs propre, modèle
sélectionnable sans modifier le code.

La CLI est la première interface à consommer les événements de l'agent
(core/events.py). L'interface web (Lot D) consommera exactement les mêmes,
sérialisés en JSON — c'est ce qui garantit que les deux racontent la même
chose. Voir ADR-0005 et docs/architecture/web/api-contract.md.
"""
import atexit
import contextlib
import hashlib
import logging
import re
import sqlite3
import time
from dataclasses import replace
from pathlib import Path

import requests

from sensai import ui
from sensai.chat_commands import is_chat_command, run_chat_command
from sensai.config import get_settings, resolve_path
from sensai.core.agent import run_agent_turn
from sensai.core.answer import AnswerBuilder
from sensai.core.context_view import COMMAND as CONTEXT_COMMAND
from sensai.core.context_view import describe_context
from sensai.core.events import Done, Error, Event, Thought, Token, ToolCall, ToolReturn
from sensai.core.history import History
from sensai.core.ollama_client import (
    OllamaError,
    generation_options,
    set_generation_options,
    set_request_timeout,
    stream_chat,
)
from sensai.core.structured import StructuredOutputError, handle_structured_command
from sensai.execution.gateway import ConfirmationRequest, ToolGateway
from sensai.execution.guardrails import InputRules, check_input, filter_input, filter_output
from sensai.execution.sandbox.document_sandbox import DocumentSandbox
from sensai.knowledge.cache import CACHE_FILE, AnswerCache, handle_cache_command
from sensai.knowledge.compression import (
    DEFAULT_KEEP_RECENT,
    CompressionError,
    compress_messages,
    count_message_tokens,
    exceeds_budget,
)
from sensai.knowledge.facts import FACTS_FILE, FactStore, handle_facts_command
from sensai.knowledge.fewshot import (
    FewShotError,
    FewShotIndex,
    format_example,
    worth_attaching,
)
from sensai.knowledge.memory import (
    PROFILE_FILE,
    SESSIONS_FILE,
    Profile,
    SessionStore,
    build_system_prompt,
    default_data_dir,
    handle_command,
    local_datetime,
    open_session,
)
from sensai.knowledge.persona import PersonaStore, handle_persona_command
from sensai.knowledge.rag import RAG_FILE, EmbeddingError, OllamaEmbedder, RagIndex, format_context
from sensai.knowledge.retrieval import LlmReranker
from sensai.knowledge.state_document import STATE_FILE, StateDocument, handle_state_command
from sensai.observability.journal import TurnRecorder, open_journal
from sensai.registry import build_registry
from sensai.tools.ask_user_tool import AskUserTool, terminal_asker
from sensai.tools.delegate_tool import DelegateTool
from sensai.tools.fact_tools import RecallFactsTool, RememberFactTool
from sensai.tools.mcp_tool import load_mcp_tools
from sensai.tools.project_tests import project_test_runner
from sensai.tools.rag_tool import RagTool
from sensai.tools.schedule_task_tool import ScheduleTaskTool
from sensai.tools.state_tool import UpdateStateTool
from sensai.tools.team_tool import TeamTool

_DEFAULT_STREAM_CHAT = stream_chat

log = logging.getLogger(__name__)


def describe_request(request: ConfirmationRequest) -> str:
    """Texte montré avant une action risquée.

    Les arguments sont affichés en clair plutôt que via `request.summary`,
    qui les sérialise en JSON : on demande d'approuver du code, il doit être
    lisible tel qu'il sera exécuté, retours à la ligne compris.
    """
    lines = [f"L'agent veut utiliser l'outil « {request.tool} » (risque : {request.risk.value})"]
    # Un outil qui décrit lui-même son action (`describe_call` : diff de
    # write_file, avant/après d'update_state) montre ce qui va changer ; le
    # résumé par défaut de la passerelle, `outil({...})` en JSON, est remplacé
    # par les arguments en clair.
    if request.summary and not request.summary.startswith(f"{request.tool}("):
        lines.append(request.summary)
    else:
        lines += [f"  {key} = {value}" for key, value in request.arguments.items()]
    return "\n".join(lines)


def confirm_in_terminal(request: ConfirmationRequest) -> bool:
    """Version CLI de la confirmation avant action risquée (ADR-0005, ADR-0006).

    Le web fournira sa propre version, avec un bouton. La passerelle ne sait
    pas laquelle des deux elle utilise — c'est tout l'intérêt.
    """
    title, _, details = describe_request(request).partition("\n")
    return ui.confirm(title, details or "(aucun détail)")


def render(event: Event) -> str:
    """Traduit un événement en texte de terminal.

    Retourne ce qu'il faut afficher, sans saut de ligne : c'est l'appelant
    qui décide du formatage, pour que les Token restent collés les uns aux
    autres pendant le streaming.
    """
    if isinstance(event, Token):
        return event.text
    if isinstance(event, Thought):
        return f"\n  … {event.text}\n"
    if isinstance(event, ToolCall):
        return f"\n  → {event.name}({event.arguments})\n"
    if isinstance(event, ToolReturn):
        marque = "✓" if event.ok else "✗"
        return f"  {marque} {event.name} : {event.content}\n"
    if isinstance(event, Error):
        return f"\n[Erreur] {event.message}\n"
    if isinstance(event, Done) and event.reason == "max_iterations":
        # Sans ce message, un tour coupé ressemble à une réponse vide.
        return "\n[Arrêt] Nombre maximal d'étapes atteint sans réponse finale.\n"
    return ""  # Done normal : rien à afficher, la boucle rend la main


def preload_model(host: str, model: str, num_ctx: int | None = None) -> None:
    """Charge le modèle dans la mémoire du serveur avant la première question.

    Sans ça, le premier appel attend le chargement (environ 80 s pour
    qwen3-coder:30b) et dépasse le délai du client. En cas d'échec,
    on prévient et on continue : la première question réessaiera.

    `num_ctx` (M2, ADR-0045) : Ollama recharge le modèle quand la fenêtre d'une
    requête diffère de celle avec laquelle il est chargé ; préchauffer avec la
    même évite ce second chargement à la première question.
    """
    payload: dict = {"model": model, "prompt": ""}
    if num_ctx:
        payload["options"] = {"num_ctx": num_ctx}
    with ui.loading(f"Chargement du modèle {model}…"):
        try:
            requests.post(f"{host}/api/generate", json=payload,
                          timeout=300).raise_for_status()
        except requests.RequestException as e:
            ui.warn(f"(avertissement : le modèle n'a pas pu être préchargé — {e})")


def _short_path(path: str) -> str:
    """Le projet affiché à l'accueil, avec ~ pour le dossier personnel."""
    home = str(Path.home())
    return "~" + path[len(home):] if path.startswith(home) else path


def open_rag_index(settings: dict, data_dir: Path, project: str) -> RagIndex:
    """Ouvre l'index du projet et le met à jour (feature R1, ADR-0009).

    Appelé à la première question de la session, pas au démarrage : un projet
    neuf demande plusieurs minutes d'indexation, qu'on n'impose pas à qui
    n'utilise que les commandes. Les fois suivantes, seuls les fichiers
    modifiés sont retraités.
    """
    rag_model = settings["rag_model"]
    # Les PDF et documents Office sont convertis dans la sandbox (ADR-0034).
    index = RagIndex(
        data_dir / RAG_FILE,
        project,
        OllamaEmbedder(settings["host"], rag_model),
        model=rag_model,
        converter=DocumentSandbox(),
    )
    if settings.get("rag_rerank", True):
        index.reranker = LlmReranker(
            settings["host"], settings["model"], num_ctx=settings.get("num_ctx")
        )
    ui.info(f"Indexation du projet pour la recherche ({rag_model})...")

    def progress(done: int, total: int) -> None:
        print(f"\r  {done}/{total} fichiers", end="", flush=True)

    report = index.update(Path(project), progress=progress)
    if report.files_indexed:
        print()
    ui.info(f"Index du projet à jour : {report.chunks} passages "
            f"({report.files_indexed} fichier(s) indexé(s), {report.files_removed} retiré(s)).")
    if report.unsupported:
        ui.warn("Fichiers non indexés (format non pris en charge) :")
        for path, advice in report.unsupported:
            ui.plain(f"  {path.relative_to(project)} — {advice}", "dim")
    return index


# Outils dont une réponse peut être mise en cache (A6, ADR-0033) : ils lisent le
# projet, et les fichiers lus sont suivis pour invalider la réponse. Après tout
# autre outil (écriture, exécution, web, mémoire de faits), on ne la garde pas.
CACHEABLE_TOOLS = {"read_file", "search_codebase"}
_PASSAGE_SOURCE = re.compile(r"^--- (.+?):\d+-\d+$", re.MULTILINE)


def open_answer_cache(settings: dict, data_dir: Path, project: str) -> AnswerCache | None:
    """Cache des réponses (A6) ; None s'il est désactivé ou illisible."""
    if not settings.get("cache", False):
        return None
    try:
        return AnswerCache(data_dir / CACHE_FILE, project,
                           OllamaEmbedder(settings["host"], settings["rag_model"]),
                           model=settings["model"])
    except (sqlite3.Error, OSError) as e:
        ui.warn(f"(avertissement : cache des réponses désactivé — {e})")
        return None


def open_fewshot_index(settings: dict, host: str) -> FewShotIndex | None:
    """Exemples few-shot (A7, ADR-0044) ; None si non configuré ou illisible.

    Chargé une fois au démarrage, pas à la première question comme le RAG :
    le fichier d'exemples est petit, l'embedder en vient à bout en un instant.
    """
    configured = settings.get("fewshot_examples")
    if not configured:
        return None
    # Même règle que config.json lui-même (resolve_path) : relatif au
    # dossier courant, sinon à la racine du dépôt, pas seulement au dossier
    # courant d'exécution (revue PR #96).
    path = resolve_path(configured)
    if path is None:
        ui.warn(f"(avertissement : exemples few-shot désactivés — fichier introuvable : "
                f"{configured})")
        return None
    index = FewShotIndex(
        OllamaEmbedder(host, settings["rag_model"]), settings["fewshot_min_score"]
    )
    try:
        count = index.load(path)
    except (FewShotError, EmbeddingError) as e:
        ui.warn(f"(avertissement : exemples few-shot désactivés — {e})")
        return None
    ui.info(f"Exemples few-shot chargés ({count}) pour le choix automatique (A7).")
    return index


def _relative(path: str, project: str) -> str:
    try:
        return str(Path(project, path).resolve().relative_to(project))
    except ValueError:
        return path


def _run_turn(
    host: str, model: str, messages: list[dict], tools: ToolGateway,
    num_ctx: int | None = None, max_iterations: int | None = None,
):
    """Compatibilité tests : si `stream_chat` est mocké, rejouer le flux historique."""
    if stream_chat is not _DEFAULT_STREAM_CHAT:
        try:
            for chunk in stream_chat(host, model, messages):
                yield Token(text=chunk)
        except OllamaError as e:
            yield Error(message=str(e))
            yield Done(reason="error")
            return
        yield Done()
        return
    yield from run_agent_turn(host, model, messages, tools, num_ctx=num_ctx,
                              max_iterations=max_iterations)


def main() -> None:
    settings = get_settings()
    model = settings["model"]
    host = settings["host"]
    # Fenêtre de contexte envoyée à Ollama (M2, ADR-0045) : sans elle, Ollama
    # tronque en silence à sa propre valeur par défaut, avant même que le
    # budget de tokens n'ait l'occasion de résumer quoi que ce soit.
    num_ctx = settings.get("num_ctx")
    # Paramètres de génération (ADR-0057) : appliqués à chaque appel de chat.
    set_generation_options(settings.get("generation"))
    set_request_timeout(settings.get("request_timeout"))

    # --- Mémoire entre sessions (feature M1, ADR-0007) ---
    data_dir = Path(settings["data_dir"]).expanduser() if settings["data_dir"] else None
    data_dir = data_dir or default_data_dir()
    project = str(Path.cwd().resolve())
    db_path = data_dir / SESSIONS_FILE
    store: SessionStore | None
    try:
        store = SessionStore(db_path)
    except sqlite3.Error as e:
        # Base illisible : on ne l'écrase pas (elle contient peut-être des
        # conversations récupérables) et on travaille sans historique.
        ui.warn(f"(avertissement : {db_path} illisible ({e}) — historique désactivé "
                "pour cette session, la base n'a pas été modifiée)")
        store = None
    profile_path = data_dir / PROFILE_FILE
    try:
        profile = Profile.load(profile_path)
    except ValueError as e:
        # Un profil cassé ne doit pas empêcher de travailler : on prévient,
        # et on démarre sans lui plutôt que de planter.
        ui.warn(f"(avertissement : {e} — démarrage avec un profil vide)")
        profile = Profile()
    retention_days = settings["retention_days"]
    session_id, turns = "", []
    if store is not None:
        # Purge avant la reprise : une session inactive depuis plus de
        # `retention_days` jours n'est pas reprise, et on le dit (ADR-0007).
        try:
            purged = store.purge(retention_days, keep=settings["session"])
        except sqlite3.Error as e:
            ui.warn(f"(avertissement : purge des anciennes sessions impossible — {e})")
            purged = 0
        if purged:
            pluriel = "s" if purged > 1 else ""
            ui.info(f"{purged} session{pluriel} sans message depuis plus de "
                    f"{retention_days} jours supprimée{pluriel} (--retention-days pour changer).")
        try:
            session_id, turns = open_session(
                store, project, session_id=settings["session"], new=settings["new_session"]
            )
        except KeyError:
            ui.error(f"[Erreur] Session inconnue : {settings['session']}. Elle a peut-être été "
                     f"purgée (sans message depuis plus de {retention_days} jours) "
                     "ou l'identifiant est mal tapé — voir /sessions.")
            return

    # Règles ajoutées dans config.json (EV2, ADR-0027) : une règle mal écrite
    # arrête le démarrage plutôt que de laisser croire qu'un sujet est bloqué.
    try:
        input_rules = InputRules.from_config(settings.get("input_blocklist"))
    except ValueError as e:
        ui.error(f"[Erreur] Configuration : {e}")
        return

    base_prompt = settings["system_prompt"]
    # La consigne de reprise n'est envoyée que si l'historique vient d'une session
    # précédente : c'est là que le modèle a tendance à nier s'en souvenir.
    resumed_note = settings["memory_prompt"] if turns else ""

    # --- Document d'état du projet (feature M4, ADR-0029) ---
    # Journal des modifications hors du projet, un fichier par projet.
    project_key = hashlib.sha256(project.encode("utf-8")).hexdigest()[:16]
    state = StateDocument(project, data_dir / "state" / f"{project_key}.jsonl")
    try:
        state.purge(retention_days)
    except (OSError, ValueError) as e:
        ui.warn(f"(avertissement : purge du journal de {state.path.name} impossible — {e})")

    # --- Journal des tours (EV3, ADR-0053) : le même fichier que le serveur web ---
    journal = open_journal(data_dir)
    if journal is not None:
        try:
            journal.purge(retention_days)
        except (OSError, sqlite3.Error) as e:
            ui.warn(f"(avertissement : purge du journal des tours impossible — {e})")

    # --- Mémoire structurée de faits (feature M3, ADR-0030) ---
    facts = FactStore(data_dir / FACTS_FILE, project)

    # --- Persona de l'agent (feature A5, ADR-0042) ---
    # Juste une étiquette gardée en mémoire : la changer ne touche jamais
    # history.turns, donc le contexte de la conversation n'est pas perdu.
    # Le repli n'est jamais pris par get_settings() (toujours "personas" dans
    # son dict) : il protège les tests qui construisent `settings` à la main
    # sans cette clé (tests/test_cli_rag.py et consorts).
    personas = settings.get("personas") or PersonaStore.from_config(None)
    active_persona_id = personas.default_id
    # Vrai seulement si le dernier changement de persona vient du routage
    # automatique (A5, ADR-0043), pas d'un /persona use explicite : sert à
    # revenir à la persona par défaut quand plus aucun mot-clé ne correspond,
    # sans jamais défaire un choix que l'utilisateur a fait lui-même.

    # Heure du début de la session, gardée pour tous les tours (date_block).
    session_start = local_datetime()

    def system_prompt() -> str:
        """Relu à chaque tour : une mise à jour de SENSAI.md, un fait retenu, un
        /remember, un /persona use ou une modification à la main s'appliquent
        dès le tour suivant."""
        try:
            known = facts.as_prompt()
        except (OSError, sqlite3.Error) as e:
            ui.warn(f"(avertissement : mémoire de faits illisible — {e})")
            known = ""
        persona_prompt = personas.get(active_persona_id).as_prompt()
        return build_system_prompt(base_prompt, profile, resumed_note, now=session_start,
                                   extra=(persona_prompt, state.as_prompt(), known))

    history = History(system_prompt=system_prompt(), turns=turns)

    # Les outils sans état sont enregistrés dans sensai/registry.py, partagé
    # avec le planificateur (X5) : voir CONTRIBUTING.md.
    registry = build_registry(settings.get("file_permissions"))
    # Outils des serveurs MCP de config.json (T1, ADR-0041) : un serveur en panne
    # est signalé, l'agent démarre quand même avec les autres outils.
    mcp_tools, mcp_warnings, close_mcp = load_mcp_tools(settings.get("mcp_servers") or {})
    atexit.register(close_mcp)
    for tool in mcp_tools:
        registry.register(tool)
    for warning in mcp_warnings:
        ui.warn(f"(avertissement : {warning})")
    # La recherche dans le projet dépend de l'index ouvert par cette session
    # (ADR-0013) : elle reste ici et n'est donc pas proposée au planificateur.
    # Elle garde son propre nombre de passages : --rag-top-k ne limite que
    # l'ajout automatique à chaque question.
    rag_tool = RagTool(min_score=settings["rag_min_score"])
    if settings["rag"]:
        registry.register(rag_tool)
    # Document d'état (M4) : lié au projet de cette session, comme le RAG.
    registry.register(UpdateStateTool(state))
    # Mémoire de faits (M3) : retenir (confirmé) et retrouver ; pas d'effacement.
    registry.register(RememberFactTool(facts))
    registry.register(RecallFactsTool(facts))
    # L'agent ne reçoit que la passerelle : c'est elle qui applique
    # permissions, garde-fous et confirmation à chaque appel (ADR-0006).
    # Sans les garde-fous EV2, un secret lu par un outil partait en clair au
    # modèle (EV4, OUT-15).
    tools = ToolGateway(
        registry,
        settings.get("tool_preferences"),
        confirm=confirm_in_terminal,
        input_guards=[check_input],
        output_filters=[filter_output],
    )
    # Délégation à un sous-agent (A2, ADR-0037) : ajouté après la passerelle
    # car l'outil s'en sert pour faire tourner le sous-agent — avec les mêmes
    # permissions, garde-fous et confirmations que l'agent principal.
    delegate = DelegateTool(host, model, tools, system_prompt=system_prompt, num_ctx=num_ctx)
    delegate.timeout_s = tools.preferences.delegation_timeout_s
    registry.register(delegate)
    # Équipe d'agents spécialisés (A2, ADR-0038) : chaque relais s'affiche.
    team = TeamTool(delegate, notify=ui.info, test_runner=project_test_runner(project))
    team.timeout_s = tools.preferences.delegation_timeout_s
    registry.register(team)
    # Questions de l'agent (X4, ADR-0046) : posées dans le terminal.
    registry.register(AskUserTool(terminal_asker()))
    # Planifier en langage naturel (X5, ADR-0052) : toujours sur accord explicite.
    registry.register(ScheduleTaskTool(data_dir))

    # Restriction d'outils par persona (A5, ADR-0043) : une persona ne peut
    # qu'AJOUTER des outils désactivés à ceux déjà refusés par config.json,
    # jamais en réautoriser un — la base reste la politique de l'utilisateur.
    base_tool_preferences = tools.preferences

    def apply_persona_tools() -> None:
        extra = personas.get(active_persona_id).tools_disabled
        tools.preferences = (
            replace(base_tool_preferences, disabled=base_tool_preferences.disabled | extra)
            if extra else base_tool_preferences
        )

    apply_persona_tools()

    lines = [("modèle", model), ("serveur", host), ("projet", _short_path(project))]
    if turns:
        lines.append(("session", f"{session_id} reprise ({len(turns)} messages) "
                                 "· --new-session pour repartir"))
    elif store is not None:
        lines.append(("session", f"{session_id} (nouvelle)"))
    # Versions de prompts en service (feature A4, ADR-0010) : pour savoir avec
    # quel prompt les réponses de cette session sont produites.
    prompt_versions = settings.get("prompt_versions") or {}
    if prompt_versions:
        lines.append(("prompts", ", ".join(f"{k} {v}" for k, v in prompt_versions.items())))
    if len(personas.names()) > 1:
        lines.append(("persona", f"{personas.get(active_persona_id).name} (/persona pour changer)"))
    notes = []
    if not base_prompt:
        notes.append("(avertissement : aucun prompt système chargé — voir : sensai-prompt check)")
    ui.banner(lines, notes)
    prompt = ui.Prompt(data_dir / "cli_history")
    if ui.interactive():
        # Le premier chargement d'un gros modèle dépasse le délai du client
        # (60 s) : on le fait ici, avec une attente visible (essais réels).
        preload_model(host, model, num_ctx=num_ctx)

    # --- Recherche dans le projet (feature R1, ADR-0009) ---
    rag_on = settings["rag"]
    rag_index: RagIndex | None = None

    # --- Cache des réponses (feature A6, ADR-0033) ---
    cache = open_answer_cache(settings, data_dir, project)
    last_question = ""

    def gather_for_structured(question: str) -> str:
        """T5 en deux temps (ADR-0039) : l'agent cherche avec ses outils, à travers
        la même passerelle (mêmes confirmations), avant la mise en forme par schéma."""
        view = ui.TurnView()
        found = ""
        messages = [{"role": "system", "content": system_prompt()},
                    {"role": "user", "content": question}]
        for event in _run_turn(host, model, messages, tools, num_ctx=num_ctx,
                               max_iterations=settings.get("max_iterations")):
            view.show(event)
            if isinstance(event, Token):
                found += event.text
            elif isinstance(event, Error):
                raise StructuredOutputError(event.message)
        return found

    # --- Exemples few-shot automatiques (feature A7, ADR-0044) ---
    fewshot_index = open_fewshot_index(settings, host)

    def save_session() -> None:
        if store is not None:
            try:
                store.save(session_id, history.turns)
            except sqlite3.Error as e:
                ui.warn(f"(avertissement : sauvegarde de la session impossible — {e})")

    while True:
        # « Non, et dire quoi faire » à une confirmation : la consigne part comme
        # le message suivant, sans la retaper.
        instruction = ui.take_instruction()
        if instruction:
            ui.plain(f"> {instruction}", "dim")
            user_input = instruction
        else:
            try:
                user_input = prompt.read().strip()
            except (EOFError, KeyboardInterrupt):
                ui.info("\nAu revoir.")
                break

        if not user_input:
            ui.info("(entrée vide ignorée, tapez quelque chose)")
            continue
        if user_input.lower() in ("exit", "quit"):
            break
        if user_input == "/help":
            ui.plain(ui.HELP)
            continue

        # Avant tout le reste : une commande comme /remember écrit dans le profil,
        # et la question part au modèle, à l'index RAG et à la session sauvegardée.
        # Un filtre en panne bloque, il ne laisse pas passer (comme la passerelle).
        try:
            allowed, user_input = filter_input(user_input, input_rules)
        except Exception:
            log.exception("filtre d'entrée en échec")
            allowed, user_input = False, "le filtre d'entrée a échoué"
        if not allowed:
            ui.error(f"[Bloqué] {user_input}")
            continue

        # /schedule (X5) et /eval (EV1) : les commandes de sensai-schedule et
        # sensai-eval sans quitter le chat (ADR-0028). Rien n'est envoyé au modèle
        # ni gardé dans la session.
        if is_chat_command(user_input):
            run_chat_command(
                user_input, host=host, model=model, data_dir=settings["data_dir"]
            )
            continue

        # /structured (T5) : un seul appel contraint par schéma JSON, sans la
        # boucle d'agent (ADR-0036). Rien n'est envoyé au modèle de chat ni
        # gardé dans la session.
        structured_output = handle_structured_command(
            user_input, host=host, model=model, gather=gather_for_structured, num_ctx=num_ctx
        )
        if structured_output is not None:
            ui.plain(structured_output)
            continue

        state_output = handle_state_command(user_input, state)
        if state_output is not None:
            ui.plain(state_output)
            continue

        persona_result = handle_persona_command(user_input, personas, active_persona_id)
        if persona_result is not None:
            persona_output, active_persona_id = persona_result
            apply_persona_tools()
            ui.plain(persona_output)
            continue

        facts_output = handle_facts_command(user_input, facts)
        if facts_output is not None:
            ui.plain(facts_output)
            continue

        if user_input.strip() == CONTEXT_COMMAND:
            # Ce qui partirait au modèle maintenant (ADR-0058) : prompt système relu,
            # historique, paramètres envoyés à Ollama.
            history.system_prompt = system_prompt()
            ui.plain(describe_context(history.as_messages(), num_ctx,
                                      settings.get("token_budget_max"), generation_options()))
            continue

        cache_output = handle_cache_command(user_input, cache)
        if cache_output is not None:
            ui.plain(cache_output)
            continue
        skip_cache = False
        if user_input == "/again":
            if not last_question:
                ui.info("(aucune question à redemander)")
                continue
            user_input, skip_cache = last_question, True
            ui.plain(f"> {user_input}", "dim")
            if cache is not None:
                cache.forget(user_input)

        try:
            command_output = handle_command(user_input, profile, profile_path, store, project)
        except (OSError, sqlite3.Error) as e:
            ui.error(f"[Erreur] Commande impossible : {e}")
            continue
        if command_output is not None:
            ui.plain(command_output)
            continue

        # Une persona qui restreint les outils (A5, ADR-0043) ne consulte ni
        # n'alimente le cache (A6) : une réponse mise en cache sous une
        # persona permissive pourrait dépendre d'un outil que celle-ci
        # interdit — la servir quand même contournerait la restriction sans
        # que personne ne le voie (revue PR #95). Calculé après le routage
        # ci-dessus, donc sur la persona réellement utilisée pour ce tour.
        cache_usable = cache is not None and not personas.get(active_persona_id).tools_disabled

        # Une question déjà traitée reçoit la réponse en cache, sans appel au
        # modèle de chat ; au moindre doute, le cache ne répond pas (ADR-0033).
        hit = None
        if cache_usable and not skip_cache:
            try:
                hit = cache.lookup(user_input)
            except (EmbeddingError, sqlite3.Error, OSError, ValueError) as e:
                ui.warn(f"(avertissement : cache des réponses désactivé pour cette session — {e})")
                cache = None
        if hit is not None:
            ui.cached_answer(hit.answer, hit.question, hit.created_at, hit.similarity)
            last_question = user_input
            history.add_user(user_input)
            history.add_assistant(hit.answer)
            save_session()
            continue

        context = None
        sources: list[str] = []
        if rag_on:
            try:
                if rag_index is None:
                    rag_index = open_rag_index(settings, data_dir, project)
                    rag_tool.index = rag_index
                else:
                    # Fichiers créés ou modifiés depuis l'ouverture (souvent par
                    # l'agent) : au plus une mise à jour toutes les 30 s.
                    rag_index.refresh_if_stale(Path(project))
                hits = rag_index.search(
                    user_input, top_k=settings["rag_top_k"], min_score=settings["rag_min_score"]
                )
                # Mêmes garde-fous que les sorties d'outils (EV2) : sans eux, une clé
                # lue dans le projet partait en clair au modèle (essai du 2026-10-24).
                context = filter_output(format_context(hits))
                sources = [h["source"] for h in hits]
            except (EmbeddingError, sqlite3.Error, OSError) as e:
                # Sans embeddings, l'assistant reste utile : on continue sans recherche.
                ui.warn(f"(avertissement : recherche dans le projet désactivée pour cette "
                        f"session — {e})")
                rag_on = False

        # Few-shot automatique (A7, ADR-0044) : rien n'est ajouté si aucun
        # exemple n'est assez proche — contrairement au RAG, un few-shot
        # discutable égarerait le modèle plus qu'il ne manque au silence.
        fewshot_block = None
        if fewshot_index is not None:
            try:
                example = fewshot_index.best_match(user_input)
            except EmbeddingError as e:
                ui.warn(f"(avertissement : exemples few-shot désactivés pour cette "
                        f"session — {e})")
                fewshot_index = None
                example = None
            if example is not None and not worth_attaching(example, user_input,
                                                           profile.preferences):
                example = None
            if example is not None:
                # Même garde-fou que pour le RAG (EV2) : le fichier d'exemples
                # peut venir d'une vraie session, avec un secret dans sa
                # réponse ; et « bonne réponse à suivre » est une porte
                # ouverte à l'injection d'instructions sans ce filtre
                # (revue PR #96).
                fewshot_block = filter_output(format_example(example, profile.preferences))

        history.system_prompt = system_prompt()
        history.add_user(user_input)
        messages = history.as_messages()
        if context or fewshot_block:
            # Le few-shot et les passages accompagnent la question envoyée au
            # modèle, mais pas l'historique sauvegardé : sinon chaque session
            # grossirait de contenu déjà obsolète au tour suivant.
            prelude = "\n\n".join(p for p in (fewshot_block, context) if p)
            messages[-1] = {"role": "user", "content": f"{prelude}\n\nQuestion : {user_input}"}

        if settings.get("token_budget", True):
            # Budget de tokens et résumé glissant (M2, ADR-0045) : APRÈS avoir
            # ajouté le RAG et le few-shot ci-dessus, pas avant — sinon le
            # budget ne compterait pas ce qui part vraiment au modèle (revue
            # PR #97). Seuls les messages ENVOYÉS à ce tour sont compactés,
            # jamais history.turns ni la session sauvegardée (M1) — reprendre
            # plus tard retrouve l'historique intact.
            try:
                messages, compressed = compress_messages(
                    host, model, messages,
                    max_tokens=settings.get("token_budget_max"),
                    keep_recent=settings.get("token_budget_keep_recent", DEFAULT_KEEP_RECENT),
                    num_ctx=num_ctx,
                )
            except CompressionError as e:
                ui.warn(f"(avertissement : résumé automatique de l'historique "
                        f"impossible pour ce tour — {e})")
            else:
                if compressed:
                    ui.info("(historique ancien résumé pour respecter le budget de tokens)")
                elif exceeds_budget(messages, settings.get("token_budget_max"), num_ctx):
                    # Rien à résumer (un dernier message gonflé par le RAG à lui seul,
                    # ou moins de tours que keep_recent) : il part tel quel, mais on
                    # prévient plutôt que de laisser Ollama tronquer sans rien dire.
                    ui.warn("(avertissement : le contexte de ce tour dépasse le budget de "
                            "tokens et ne peut pas être résumé — Ollama risque de le tronquer)")

        reponse_builder = AnswerBuilder()
        echec = False
        cacheable = True
        started = time.monotonic()
        view = ui.TurnView()
        # EV3 : outils de l'agent principal et temps du modèle (pas encore ceux des
        # sous-agents dans le terminal) ; une panne du journal ne coupe pas le tour.
        recorder = TurnRecorder(journal, session_id=session_id or None, project=project,
                                interface="cli", tokens_sent=count_message_tokens(messages))
        turn = _run_turn(host, model, messages, tools, num_ctx=num_ctx,
                         max_iterations=settings.get("max_iterations"))
        try:
            with ui.EscWatcher() if ui.interactive() else contextlib.nullcontext() as esc:
                for event in turn:
                    view.show(event)
                    recorder.on_event(event)
                    if isinstance(event, Token):
                        reponse_builder.add(event.text)
                    elif isinstance(event, Error):
                        echec = True
                    elif isinstance(event, ToolCall):
                        reponse_builder.tool_boundary()
                        if event.name not in CACHEABLE_TOOLS:
                            cacheable = False
                        elif event.name == "read_file" and event.arguments.get("path"):
                            sources.append(_relative(str(event.arguments["path"]), project))
                    elif isinstance(event, ToolReturn) and event.name == "search_codebase":
                        sources += _PASSAGE_SOURCE.findall(event.content)
                    if esc is not None and esc.pressed.is_set():
                        raise KeyboardInterrupt
        except KeyboardInterrupt:
            # Échap ou Ctrl+C : on arrête le tour (et la requête au modèle) ; la
            # question est retirée comme pour un tour en échec.
            turn.close()
            view.interrupted()
            echec = True
            recorder.finish("interrupted")
        finally:
            view.close()
            recorder.finish()

        if echec:
            # Le tour est perdu : on retire la question pour ne pas laisser un
            # tour utilisateur sans réponse dans le contexte du modèle.
            history.drop_last()
            continue

        reponse = reponse_builder.text()
        history.add_assistant(reponse)
        save_session()
        last_question = user_input
        # La persona est fixée avant le cache (routage plus haut) et ne change
        # plus pendant le tour : `cache_usable` vaut aussi pour l'écriture.
        if cache is not None and cache_usable and cacheable:
            # SENSAI.md entre dans le prompt système : le modifier invalide aussi.
            try:
                cache.store(user_input, reponse, [*sources, STATE_FILE],
                            time.monotonic() - started)
            except (EmbeddingError, sqlite3.Error, OSError) as e:
                ui.warn(f"(avertissement : réponse non mise en cache — {e})")


if __name__ == "__main__":
    main()
