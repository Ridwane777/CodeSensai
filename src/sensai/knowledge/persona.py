"""
[Workstream A — Fresnel] Agent personas — feature [A5], ADR-0042 and ADR-0043.

The agent's name, tone, role and scope are read from `config.json`
(`personas` section), never hard-coded: the same system becomes a legal
assistant or a math tutor without touching the code.

The active persona is just a label kept in memory by the CLI loop
(`cli.py`): switching persona never touches `History.turns`, so the
conversation context survives the switch, as the catalog requires.

ADR-0043 added three enhancements; only per-persona tool restriction remains
(`tools.disabled`). Keyword routing and adding a persona on the fly
(`/persona add`) were removed (ADR-0056, point 4): they served a
multi-purpose platform, not Camille's scenario.
"""
from __future__ import annotations

from dataclasses import dataclass, field

DEFAULT_PERSONA_ID = "assistant"
DEFAULT_PERSONA = {
    "id": DEFAULT_PERSONA_ID,
    "name": "CodeSensai",
    "role": "development assistant",
    "tone": "neutral and precise",
    "scope": "the current project",
}


@dataclass(frozen=True)
class Persona:
    id: str
    name: str
    role: str
    tone: str
    scope: str
    # Automatic routing (ADR-0043): if one of these words appears in the
    # question, and this persona is not already active, switch to it.
    # Tool restriction (ADR-0043): tool names removed on top of those already
    # disabled by the global config, while this persona is active.
    tools_disabled: frozenset[str] = field(default_factory=frozenset)

    def as_prompt(self) -> str:
        return (
            f"For this session, you are {self.name}. Your role: {self.role}. "
            f"Your tone: {self.tone}. Answer scope: {self.scope} — "
            "if a question falls outside it, say so instead of answering anyway."
        )


class PersonaError(ValueError):
    """Unknown persona or invalid configuration: the message says what to do."""


class PersonaStore:
    """The available profiles, read once at startup from `config.json`,
    and extendable during a session with `/persona add` (ADR-0043).

    Always at least one persona (`DEFAULT_PERSONA`): a project without a
    `personas` section in its config keeps working with nothing to configure.
    """

    def __init__(self, profiles: list[Persona], default_id: str):
        if not profiles:
            raise PersonaError("personas: at least one profile is required")
        self._profiles = {p.id: p for p in profiles}
        if default_id not in self._profiles:
            known = ", ".join(sorted(self._profiles)) or "none"
            raise PersonaError(f"personas: unknown default persona: {default_id} "
                                f"(known: {known})")
        self.default_id = default_id

    @classmethod
    def from_config(cls, data: dict | None) -> PersonaStore:
        """`data`: the value of `config.json["personas"]`, or None/absent.

        Any entry without the expected shape — `data` not a dict, a profile
        that is not a dict, a field that is missing, empty or not a string —
        raises PersonaError rather than a Python AttributeError/TypeError: a
        badly written config must stop with a clear message, never a CLI
        traceback.
        """
        if data is None:
            return cls([Persona(**DEFAULT_PERSONA)], DEFAULT_PERSONA_ID)
        if not isinstance(data, dict):
            raise PersonaError("personas: an object is expected (id/name/role/tone/scope)")
        profiles_raw = data.get("profiles")
        if not isinstance(profiles_raw, list) or not profiles_raw:
            raise PersonaError("personas.profiles: non-empty list expected")
        profiles = []
        seen_ids: set[str] = set()
        for i, raw in enumerate(profiles_raw):
            if not isinstance(raw, dict):
                raise PersonaError(f"personas.profiles[{i}]: an object is expected")
            missing = {"id", "name", "role", "tone", "scope"} - raw.keys()
            if missing:
                raise PersonaError(f"personas.profiles[{i}]: missing field(s): "
                                    f"{', '.join(sorted(missing))}")
            for field_name in ("id", "name", "role", "tone", "scope"):
                value = raw[field_name]
                if not isinstance(value, str) or not value.strip():
                    raise PersonaError(
                        f"personas.profiles[{i}].{field_name}: non-empty string expected"
                    )
            if raw["id"] in seen_ids:
                raise PersonaError(f"personas.profiles: duplicate id: {raw['id']}")
            seen_ids.add(raw["id"])
            if "keywords" in raw:
                # Keyword routing removed (ADR-0056, point 4): a key that no longer
                # does anything must not look active.
                raise PersonaError(f"personas.profiles[{i}].keywords: keyword routing "
                                   "was removed (ADR-0056); switch persona "
                                   "with /persona use or the web selector")
            tools_cfg = raw.get("tools") or {}
            disabled = tools_cfg.get("disabled", [])
            if not isinstance(disabled, list) or not all(isinstance(n, str) for n in disabled):
                raise PersonaError(
                    f"personas.profiles[{i}].tools.disabled: list of tool names expected"
                )
            profiles.append(Persona(
                id=raw["id"], name=raw["name"], role=raw["role"],
                tone=raw["tone"], scope=raw["scope"],
                tools_disabled=frozenset(disabled),
            ))
        default_id = data.get("default", profiles[0].id)
        if not isinstance(default_id, str):
            raise PersonaError("personas.default: a string is expected")
        return cls(profiles, default_id)

    def names(self) -> list[str]:
        return sorted(self._profiles)

    def get(self, persona_id: str) -> Persona:
        try:
            return self._profiles[persona_id]
        except KeyError:
            known = ", ".join(self.names())
            raise PersonaError(f"unknown persona: {persona_id} (known: {known})") from None

    def default(self) -> Persona:
        return self._profiles[self.default_id]


def handle_persona_command(
    line: str, store: PersonaStore, active_id: str
) -> tuple[str, str] | None:
    """`/persona`, `/persona list`, `/persona use <id>`.

    Returns `(displayed text, active id after the command)`, or None if `line`
    is not a `/persona` command (it then goes to the model as usual).
    """
    words = line.split(maxsplit=2)
    if not words or words[0] != "/persona":
        return None
    if len(words) == 1:
        active = store.get(active_id)
        return f"Active persona: {active.id} ({active.name}, {active.role}).", active_id
    if words[1] == "list":
        lines = []
        for name in store.names():
            p = store.get(name)
            marker = "*" if name == active_id else " "
            lines.append(f"{marker} {p.id} — {p.name}, {p.role}")
        return "\n".join(lines), active_id
    if words[1] == "use" and len(words) == 3:
        try:
            new_persona = store.get(words[2].strip())
        except PersonaError as e:
            return f"[Error] {e}", active_id
        return (f"Persona switched: {new_persona.id} ({new_persona.name}). "
                "The conversation history is kept."), new_persona.id
    return (
        "Usage: /persona | /persona list | /persona use <id>"
    ), active_id
