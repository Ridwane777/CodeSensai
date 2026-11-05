"""
Niveaux de risque, modes de permission et préférences utilisateur des outils.

Fait partie du contrat de la passerelle d'outils (docs/architecture/tool-contract.md,
ADR-0006). Ce module ne décide rien tout seul : il répond à une seule
question — « pour cet outil, que doit faire la passerelle avant de l'exécuter :
laisser passer, demander, ou refuser ? ».
"""
from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class Risk(str, Enum):
    """Ce qu'un outil peut abîmer. Chaque outil en déclare un (attribut `risk`)."""

    READ = "read"  # lit, ne change rien (RAG, lecture de fichier autorisé)
    NETWORK = "network"  # sort sur Internet (recherche web)
    WRITE = "write"  # modifie le disque ou un état durable
    EXECUTE = "execute"  # exécute du code (sandbox) : le pire cas


class Mode(str, Enum):
    ALLOW = "allow"  # s'exécute sans demander
    ASK = "ask"  # demande une confirmation explicite (A3)
    DENY = "deny"  # n'est jamais exécuté


_STRICTNESS = {Mode.ALLOW: 0, Mode.ASK: 1, Mode.DENY: 2}

# Le critère A3 est « la sandbox ne part jamais sans confirmation explicite » :
# écrire et exécuter demandent donc par défaut.
DEFAULT_MODES: dict[Risk, Mode] = {
    Risk.READ: Mode.ALLOW,
    Risk.NETWORK: Mode.ALLOW,
    Risk.WRITE: Mode.ASK,
    Risk.EXECUTE: Mode.ASK,
}

# Seuls ces niveaux peuvent être assouplis par les préférences. Pour WRITE et
# EXECUTE une préférence ne peut que durcir : sinon un simple fichier de config
# (ou une injection de prompt qui arriverait à le modifier) désactiverait la
# confirmation que A3 promet.
LOOSENABLE = frozenset({Risk.READ, Risk.NETWORK})

_KNOWN_KEYS = {
    "disabled",
    "modes",
    "max_output_chars",
    "confirm_timeout_s",
    "tool_timeout_s",
    "confirm_after_untrusted",
}


def risk_of(tool: Any) -> Risk:
    """Risque déclaré par l'outil. Absent ou invalide => EXECUTE (échec fermé).

    Un outil qui oublie de déclarer son risque doit être traité comme le plus
    dangereux, pas comme inoffensif.
    """
    try:
        return Risk(getattr(tool, "risk", None))
    except (ValueError, TypeError):
        return Risk.EXECUTE


@dataclass(frozen=True)
class ToolPreferences:
    """Préférences de l'utilisateur sur l'usage des outils."""

    disabled: frozenset[str] = frozenset()
    modes: Mapping[str, Mode] = field(default_factory=dict)
    # Plafond de ce qui revient au modèle : un outil bavard ne doit pas
    # noyer le contexte (cf. [M2] Token Budgeting).
    max_output_chars: int = 20_000
    # Délai laissé à l'interface pour obtenir la réponse. Passé dans la demande
    # de confirmation ; dépassé => refus (exigence web HITL).
    confirm_timeout_s: float = 60.0
    # Plafond de durée d'un appel d'outil. Un outil peut déclarer un `timeout_s`
    # plus court ; jamais plus long : l'utilisateur garde le dernier mot.
    tool_timeout_s: float = 120.0
    # Once untrusted content (a web page, a document) has been read, any tool
    # that is not read-only asks for confirmation, even if its mode is "allow".
    # Limits what an injected instruction can do without the user noticing.
    confirm_after_untrusted: bool = False

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ToolPreferences:
        """Construit depuis un dict (ex. la clé "tools" de config.json).

        Lève ValueError sur toute clé ou valeur inconnue : une faute de frappe
        dans « modes » ne doit pas être ignorée en silence, elle laisserait
        croire qu'une restriction est active alors qu'elle ne l'est pas.
        """
        unknown = set(data) - _KNOWN_KEYS
        if unknown:
            raise ValueError(f"Préférences d'outils inconnues : {sorted(unknown)}")

        disabled = data.get("disabled", [])
        if not isinstance(disabled, (list, tuple, set, frozenset)) or not all(
            isinstance(n, str) for n in disabled
        ):
            raise ValueError("'disabled' doit être une liste de noms d'outils")

        raw_modes = data.get("modes", {})
        if not isinstance(raw_modes, Mapping):
            raise ValueError("'modes' doit associer un nom d'outil à un mode")
        modes = {}
        for tool_name, raw in raw_modes.items():
            try:
                modes[str(tool_name)] = Mode(raw)
            except ValueError:
                allowed = [m.value for m in Mode]
                raise ValueError(
                    f"Mode invalide pour {tool_name!r} : {raw!r} (attendu : {allowed})"
                ) from None

        max_chars = data.get("max_output_chars", cls.max_output_chars)
        if isinstance(max_chars, bool) or not isinstance(max_chars, int) or max_chars <= 0:
            raise ValueError("'max_output_chars' doit être un entier > 0")

        timeout = data.get("confirm_timeout_s", cls.confirm_timeout_s)
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or timeout <= 0:
            raise ValueError("'confirm_timeout_s' doit être un nombre > 0")

        tool_timeout = data.get("tool_timeout_s", cls.tool_timeout_s)
        if (
            isinstance(tool_timeout, bool)
            or not isinstance(tool_timeout, (int, float))
            or tool_timeout <= 0
        ):
            raise ValueError("'tool_timeout_s' doit être un nombre > 0")

        after_untrusted = data.get("confirm_after_untrusted", cls.confirm_after_untrusted)
        if not isinstance(after_untrusted, bool):
            raise ValueError("'confirm_after_untrusted' must be true or false")

        return cls(
            disabled=frozenset(disabled),
            modes=modes,
            max_output_chars=max_chars,
            confirm_timeout_s=float(timeout),
            tool_timeout_s=float(tool_timeout),
            confirm_after_untrusted=after_untrusted,
        )

    @classmethod
    def load(cls, path: str | Path) -> ToolPreferences:
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


def effective_mode(name: str, risk: Risk, prefs: ToolPreferences) -> Mode:
    """Mode appliqué à l'outil `name` : défaut du risque, ajusté par les préférences.

    Les préférences peuvent toujours durcir ; elles ne peuvent assouplir que
    les niveaux de LOOSENABLE.
    """
    default = DEFAULT_MODES[risk]
    wanted = prefs.modes.get(name)
    if wanted is None:
        return default
    if risk in LOOSENABLE or _STRICTNESS[wanted] >= _STRICTNESS[default]:
        return wanted
    return default
