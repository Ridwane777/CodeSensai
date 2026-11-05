"""
Passerelle d'outils : le seul chemin par lequel l'agent exécute un outil.

Elle enveloppe le ToolRegistry (core/tools.py, ADR-0002) sans le modifier et
impose, pour CHAQUE outil, le même pipeline :

    outil connu -> activé -> arguments valides -> mode de permission
    -> garde-fous d'entrée [EV2] -> confirmation [A3] -> exécution
    -> résultat valide -> filtres de sortie [EV2] -> plafond de taille

Un outil n'implémente aucune de ces étapes : il déclare son risque et rend un
ToolResult. Voir docs/architecture/tool-contract.md et ADR-0006.

Les décisions de la passerelle reviennent au modèle sous forme de ToolResult
(ok=False, data={"error": <code>}) : un refus est une observation dont l'agent
peut tirer parti, jamais une exception qui plante la boucle.
"""
from __future__ import annotations

import contextvars
import json
import logging
import socket
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

import requests

from sensai.core.tools import Tool, ToolRegistry, ToolResult

from .output_sanitizer import find_injection_markers, sanitize
from .tool_policy import Mode, Risk, ToolPreferences, effective_mode, risk_of
from .tool_validation import check_arguments, check_result

log = logging.getLogger(__name__)

# Codes d'erreur renvoyés dans data["error"] : stables, testables, et lisibles
# par la boucle ReAct sans parser du texte.
UNKNOWN_TOOL = "unknown_tool"
DISABLED = "disabled"
INVALID_ARGUMENTS = "invalid_arguments"
DENIED_BY_POLICY = "denied_by_policy"
BLOCKED = "blocked"
REFUSED = "refused"
INVALID_RESULT = "invalid_result"
FILTER_FAILED = "filter_failed"
TIMEOUT = "timeout"
NETWORK_ERROR = "network_error"
TOOL_ERROR = "tool_error"

# Pannes réseau : le modèle peut raisonnablement réessayer plus tard ou
# changer de source, contrairement à un bug de l'outil. requests lève ses
# propres exceptions, qui ne dérivent pas toutes de ConnectionError.
_NETWORK_ERRORS = (
    ConnectionError,
    TimeoutError,
    socket.gaierror,
    requests.exceptions.ConnectionError,
    requests.exceptions.Timeout,
)

_TRUNCATION_MARKER = "\n[... sortie tronquée ...]"
_SUMMARY_LIMIT = 500


@dataclass(frozen=True)
class Decision:
    """Verdict d'un garde-fou d'entrée.

    `replacement`, s'il est donné sur une décision autorisée, remplace les
    arguments (ex. EV2 qui masque une clé d'API dans le code à exécuter).
    """

    allowed: bool
    reason: str = ""
    replacement: dict[str, Any] | None = None


@dataclass(frozen=True)
class ConfirmationRequest:
    """Ce que l'interface doit présenter à l'utilisateur avant une action.

    Décrit l'action, ne dit rien de COMMENT la montrer : console pour la CLI,
    bouton pour le web (ADR-0005, point 3).
    """

    tool: str
    risk: Risk
    summary: str
    arguments: dict[str, Any]
    timeout_s: float


InputGuard = Callable[[str, dict[str, Any]], Decision]
OutputFilter = Callable[[str], str]
Confirmer = Callable[[ConfirmationRequest], bool]


def deny_all(request: ConfirmationRequest) -> bool:
    """Confirmeur par défaut : refuse tout.

    Tant qu'aucune interface ne branche son propre confirmeur, une action qui
    demande confirmation n'a pas lieu. Mieux vaut un outil inutilisable qu'un
    code exécuté sans que personne n'ait dit oui.
    """
    return False


def _fail(code: str, content: str) -> ToolResult:
    return ToolResult(ok=False, content=content, data={"error": code})


def _apply_to_strings(value: Any, fn: OutputFilter) -> Any:
    """Applique `fn` à toutes les chaînes d'une structure JSON (pas aux clés)."""
    if isinstance(value, str):
        return fn(value)
    if isinstance(value, dict):
        return {k: _apply_to_strings(v, fn) for k, v in value.items()}
    if isinstance(value, list):
        return [_apply_to_strings(v, fn) for v in value]
    return value


class _TimedOut(Exception):
    """Le délai est dépassé avant la fin de l'appel."""


def _run_bounded(fn: Callable[[], Any], timeout_s: float) -> Any:
    """Exécute `fn` dans un thread et attend au plus `timeout_s` secondes.

    Un thread Python ne peut pas être tué : après un délai dépassé le travail
    peut continuer en arrière-plan. C'est pourquoi le thread est « daemon »
    (il n'empêche pas le programme de se terminer) et pourquoi un outil qui
    modifie l'état doit aussi borner lui-même sa durée (la sandbox tue son
    conteneur). Une exception levée par `fn` est relancée chez l'appelant.
    """
    box: dict[str, Any] = {}

    def target() -> None:
        try:
            box["value"] = fn()
        # Relancée chez l'appelant : rien n'est avalé ici.
        except BaseException as exc:
            box["error"] = exc

    # Le thread reçoit une copie du contexte de l'appelant : sans elle, une
    # ContextVar (la profondeur de délégation de delegate_task, A2) repartirait
    # de sa valeur par défaut à chaque outil, et le garde-fou ne bornerait rien.
    ctx = contextvars.copy_context()
    thread = threading.Thread(target=ctx.run, args=(target,), daemon=True)
    thread.start()
    thread.join(timeout_s)
    if thread.is_alive():
        raise _TimedOut
    if "error" in box:
        raise box["error"]
    return box["value"]


class ToolGateway:
    def __init__(
        self,
        registry: ToolRegistry,
        preferences: ToolPreferences | None = None,
        confirm: Confirmer = deny_all,
        input_guards: Sequence[InputGuard] = (),
        output_filters: Sequence[OutputFilter] = (),
    ) -> None:
        self.registry = registry
        self.preferences = preferences or ToolPreferences()
        self.confirm = confirm
        self.input_guards = list(input_guards)
        self.output_filters = list(output_filters)
        # True once a tool that reads from outside the agent has answered. Used
        # by `confirm_after_untrusted`; one gateway per conversation.
        self._untrusted_seen = False

    def reset_untrusted(self) -> None:
        """Forget that untrusted content was read (call it when a conversation starts)."""
        self._untrusted_seen = False

    # -- ce que le modèle voit --------------------------------------------

    def describe_all(self) -> list[dict[str, Any]]:
        """Outils proposés au modèle : ni désactivés, ni refusés par la politique.

        Ne pas annoncer un outil qui sera de toute façon refusé évite que le
        modèle le choisisse, échoue, puis insiste.
        """
        return [d for d in self.registry.describe_all() if self._offered(d["name"])]

    def _offered(self, name: str) -> bool:
        tool = self.registry.get(name)
        if tool is None or name in self.preferences.disabled:
            return False
        return self._mode(name, tool) is not Mode.DENY

    def _mode(self, name: str, tool: Tool) -> Mode:
        risk = risk_of(tool)
        mode = effective_mode(name, risk, self.preferences)
        wanted = self.preferences.modes.get(name)
        if wanted is not None and wanted is not mode:
            log.warning("préférence %r=%s ignorée pour un outil %s", name, wanted.value, risk.value)
        return mode

    # -- le pipeline --------------------------------------------------------

    # `name` est positionnel uniquement (le `/`), comme dans ToolRegistry.call :
    # sans ça, un outil dont un paramètre s'appelle `name` ferait lever une
    # TypeError à l'agent avant même d'entrer dans le pipeline.
    def call(self, name: str, /, **kwargs: Any) -> ToolResult:
        """Même signature que ToolRegistry.call : l'agent peut passer de l'un à l'autre."""
        started = time.monotonic()
        result, mode = self._pipeline(name, kwargs)
        # On journalise le nom, le mode et l'issue — jamais les arguments ni la
        # sortie : ils peuvent contenir exactement ce qu'EV2 doit protéger.
        log.info(
            "tool=%s mode=%s ok=%s error=%s ms=%d",
            name,
            mode,
            result.ok,
            result.data.get("error", "-"),
            (time.monotonic() - started) * 1000,
        )
        return result

    def _pipeline(self, name: str, args: dict[str, Any]) -> tuple[ToolResult, str]:
        tool = self.registry.get(name)
        if tool is None:
            return _fail(UNKNOWN_TOOL, f"Outil inconnu : {name}"), "-"
        if name in self.preferences.disabled:
            return _fail(DISABLED, f"L'outil {name} est désactivé."), "-"

        problem = check_arguments(tool.parameters, args)
        if problem:
            return _fail(INVALID_ARGUMENTS, f"Arguments invalides pour {name} : {problem}"), "-"

        mode = self._mode(name, tool)
        if mode is Mode.DENY:
            return _fail(DENIED_BY_POLICY, f"L'outil {name} n'est pas autorisé."), mode.value

        # After reading untrusted content, anything that can act or send data
        # out asks first: an injected instruction then needs the user's yes.
        if (
            mode is Mode.ALLOW
            and self._untrusted_seen
            and self.preferences.confirm_after_untrusted
            and risk_of(tool) is not Risk.READ
        ):
            mode = Mode.ASK

        # Les garde-fous passent AVANT la confirmation : l'utilisateur ne doit
        # pas valider une action qui sera bloquée, ni voir des arguments non
        # masqués dans la demande.
        args, blocked = self._run_guards(name, tool, args)
        if blocked is not None:
            return blocked, mode.value

        if mode is Mode.ASK and not self._confirmed(name, tool, args):
            return (
                _fail(
                    REFUSED,
                    f"L'utilisateur a refusé l'exécution de {name}. "
                    "Ne la relance pas telle quelle : propose une alternative ou demande-lui.",
                ),
                mode.value,
            )

        result = self._execute(name, tool, args)
        checked = self._check_output(tool, result)
        if checked.ok and risk_of(tool) in (Risk.READ, Risk.NETWORK):
            self._untrusted_seen = True
        return checked, mode.value

    def _execute(self, name: str, tool: Tool, args: dict[str, Any]) -> Any:
        """Exécute l'outil sous délai et classe ses échecs.

        On appelle `tool.run` ici plutôt que `registry.call` : le registre
        transforme toute exception en texte sans code, alors que le modèle a
        besoin de distinguer « réessaie plus tard » (réseau, délai) de « ton
        appel est faux » (bug de l'outil). Le résultat passe ensuite par la
        validation et les filtres comme n'importe quel autre.
        """
        limit = self.preferences.tool_timeout_s
        declared = getattr(tool, "timeout_s", None)
        if isinstance(declared, (int, float)) and not isinstance(declared, bool) and declared > 0:
            limit = min(limit, float(declared))
        try:
            return _run_bounded(lambda: tool.run(**args), limit)
        except _TimedOut:
            log.warning("outil %s sans réponse après %ss", name, limit)
            return _fail(
                TIMEOUT,
                f"L'outil {name} n'a pas répondu en {limit:g} s. Son résultat est inconnu : "
                "l'action a pu aboutir. Vérifie avant de réessayer.",
            )
        except _NETWORK_ERRORS as exc:
            return _fail(
                NETWORK_ERROR,
                f"Erreur réseau dans l'outil {name} : {exc}. "
                "Réessaie plus tard ou utilise une autre source.",
            )
        except Exception as exc:  # garde-fou : un outil qui plante ne plante pas l'agent
            log.exception("outil %s en échec", name)
            return _fail(TOOL_ERROR, f"Erreur dans l'outil {name} : {exc}")

    def _run_guards(
        self, name: str, tool: Tool, args: dict[str, Any]
    ) -> tuple[dict[str, Any], ToolResult | None]:
        for guard in self.input_guards:
            try:
                decision = guard(name, args)
            # Un garde-fou en panne bloque l'appel : il ne le laisse pas passer.
            except Exception:
                log.exception("garde-fou d'entrée en échec pour %s", name)
                return args, _fail(BLOCKED, f"Appel de {name} bloqué (garde-fou en échec).")
            # Un garde-fou qui ne rend pas une Decision (None, bool...) est un
            # garde-fou cassé : on bloque, on ne devine pas son intention.
            if not isinstance(decision, Decision):
                log.error("garde-fou d'entrée invalide pour %s : %r", name, type(decision))
                return args, _fail(BLOCKED, f"Appel de {name} bloqué (garde-fou invalide).")
            if not decision.allowed:
                reason = decision.reason or "refusé par un garde-fou"
                return args, _fail(BLOCKED, f"Appel de {name} bloqué : {reason}")
            if decision.replacement is not None:
                # Les arguments réécrits sont revalidés : un garde-fou ne doit
                # pas pouvoir contourner le schéma que l'outil a déclaré.
                problem = check_arguments(tool.parameters, decision.replacement)
                if problem:
                    return args, _fail(
                        BLOCKED, f"Appel de {name} bloqué (réécriture invalide : {problem})"
                    )
                args = decision.replacement
        return args, None

    def _confirmed(self, name: str, tool: Tool, args: dict[str, Any]) -> bool:
        request = ConfirmationRequest(
            tool=name,
            risk=risk_of(tool),
            summary=self._summary(name, tool, args),
            arguments=args,
            timeout_s=self.preferences.confirm_timeout_s,
        )
        try:
            # Le délai est imposé ici et pas seulement transmis : un confirmeur
            # qui n'a jamais de réponse (onglet fermé, utilisateur parti) ne doit
            # pas figer l'agent. Pas de réponse à temps = refus.
            return _run_bounded(lambda: self.confirm(request), request.timeout_s) is True
        except _TimedOut:
            log.warning("confirmation de %s sans réponse en %ss : refus", name, request.timeout_s)
            return False
        # Interface plantée = refus.
        except Exception:
            log.exception("confirmation en échec pour %s : traité comme un refus", name)
            return False

    @staticmethod
    def _summary(name: str, tool: Tool, args: dict[str, Any]) -> str:
        """Le plan montré à l'utilisateur : `describe_call` de l'outil, sinon un défaut."""
        describe = getattr(tool, "describe_call", None)
        if callable(describe):
            try:
                return str(describe(**args))
            except Exception:
                log.exception("describe_call en échec pour %s", name)
        text = f"{name}({json.dumps(args, ensure_ascii=False, default=str)})"
        return text if len(text) <= _SUMMARY_LIMIT else text[:_SUMMARY_LIMIT] + "…"

    @staticmethod
    def _log_injection_markers(name: str, content: str, data: dict[str, Any]) -> None:
        """Log which heuristics matched, never the text itself (it may hold secrets)."""
        found = set(find_injection_markers(content))
        _apply_to_strings(data, lambda text: found.update(find_injection_markers(text)) or text)
        if found:
            log.warning("output of %s looks like an injection attempt: %s", name, sorted(found))

    def _check_output(self, tool: Tool, result: Any) -> ToolResult:
        problem = check_result(result, getattr(tool, "output_schema", None))
        if problem:
            return _fail(INVALID_RESULT, f"Résultat de {tool.name} rejeté : {problem}")

        # Deterministic cleaning comes first and does not depend on EV2: hidden
        # characters must not reach the filters either, they could hide a
        # secret from a pattern.
        content, data = sanitize(result.content), _apply_to_strings(result.data, sanitize)
        if content != result.content or data != result.data:
            log.warning("output of %s was cleaned (hidden characters or ANSI sequences)", tool.name)
        self._log_injection_markers(tool.name, content, data)
        try:
            for fn in self.output_filters:
                content = fn(content)
                data = _apply_to_strings(data, fn)
        except Exception:
            # On ne renvoie surtout pas la sortie brute : c'est justement ce
            # que le filtre devait nettoyer.
            log.exception("filtre de sortie en échec pour %s", tool.name)
            return _fail(FILTER_FAILED, f"Sortie de {tool.name} retenue (filtre en échec).")

        # Le plafond vient APRÈS les filtres : couper avant pourrait laisser un
        # secret coupé en deux, que le filtre ne reconnaîtrait plus.
        limit = self.preferences.max_output_chars
        if len(content) > limit:
            content = content[:limit] + _TRUNCATION_MARKER
        if len(json.dumps(data, ensure_ascii=False)) > limit:
            data = {"truncated": True, **({"error": data["error"]} if "error" in data else {})}
        return ToolResult(ok=result.ok, content=content, data=data)
