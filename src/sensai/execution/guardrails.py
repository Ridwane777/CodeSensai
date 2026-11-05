"""
[Lot B — Méric] Content & privacy guardrails — feature [EV2].

What is implemented here plugs into the tool gateway (docs/architecture/tool-contract.md):

- `check_input(tool_name, args) -> Decision`: input guard, masks secrets in the
  arguments the model wants to send to a tool.
- `filter_output(text) -> str`: output filter, masks secrets and personal data
  in what a tool returns before the model, the logs or the user see it.

- `filter_input(text, rules) -> (allowed, text_or_reason)`: input filter for the
  user's own prompt. Called by the CLI before anything reaches the model, the
  RAG search, the profile or the saved session (ADR-0027).
"""
from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .gateway import Decision
from .output_sanitizer import find_injection_markers, sanitize, strip_ansi, strip_invisible

# Ordered from the most specific to the most generic: once a token is replaced
# by a placeholder, a later pattern cannot match it again.
_SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "private_key",
        re.compile(
            r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(?:-----END [A-Z ]*PRIVATE KEY-----|\Z)",
            re.DOTALL,
        ),
    ),
    ("anthropic_key", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{16,}")),
    ("api_key", re.compile(r"\bsk-[A-Za-z0-9_-]{16,}")),
    ("aws_access_key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b")),
    ("slack_token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}")),
    ("bearer_token", re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{16,}")),
)

# `password = "hunter2hunter2"`, `API_KEY: abc...`: keep the name, hide the value.
_ASSIGNMENT = re.compile(
    r"(?i)\b([A-Za-z0-9_.-]*(?:api[_-]?key|secret|token|passw(?:or)?d|pwd)[A-Za-z0-9_.-]*)"
    r"(\s*[:=]\s*)(['\"]?)([^\s'\"]{8,})\3"
)


def _placeholder(kind: str) -> str:
    return f"[REDACTED:{kind}]"


def mask_secrets(text: str) -> str:
    """Replace credentials found in `text` by a `[REDACTED:<kind>]` placeholder."""
    for kind, pattern in _SECRET_PATTERNS:
        text = pattern.sub(_placeholder(kind), text)

    def hide_value(match: re.Match[str]) -> str:
        name, sep, quote, value = match.groups()
        if value.startswith("[REDACTED:"):
            return match.group(0)
        return f"{name}{sep}{quote}{_placeholder('secret')}{quote}"

    return _ASSIGNMENT.sub(hide_value, text)


_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_CARD_CANDIDATE = re.compile(r"\b\d(?:[ -]?\d){12,18}\b")


def _luhn_valid(digits: str) -> bool:
    """Luhn checksum: separates real card numbers from other long numbers."""
    total = 0
    for index, char in enumerate(reversed(digits)):
        n = int(char)
        if index % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


def mask_pii(text: str) -> str:
    """Replace email addresses and payment card numbers by placeholders."""

    def hide_card(match: re.Match[str]) -> str:
        digits = re.sub(r"\D", "", match.group(0))
        if 13 <= len(digits) <= 19 and _luhn_valid(digits):
            return _placeholder("card_number")
        return match.group(0)

    text = _CARD_CANDIDATE.sub(hide_card, text)
    return _EMAIL.sub(_placeholder("email"), text)


def _mask_strings(value: Any) -> Any:
    """Apply `mask_secrets` to every string of a JSON-like structure (not to keys)."""
    if isinstance(value, str):
        return mask_secrets(value)
    if isinstance(value, dict):
        return {k: _mask_strings(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_mask_strings(v) for v in value]
    return value


def check_input(tool_name: str, args: dict[str, Any]) -> Decision:
    """Input guard for the gateway: a credential must not travel to a tool.

    The call is allowed with the credential masked, rather than blocked: the
    request is usually fine, only the secret must not leave. The gateway
    validates the rewritten arguments against the tool's schema again, and the
    user confirms the masked version, so they never see the secret either.
    """
    masked = _mask_strings(args)
    if masked == args:
        return Decision(allowed=True)
    return Decision(allowed=True, reason="credentials masked", replacement=masked)


@dataclass(frozen=True)
class InputRule:
    name: str
    pattern: re.Pattern[str]
    why: str  # shown to the user: it says what to change, never echoes the prompt


def _rule(name: str, pattern: str, why: str) -> InputRule:
    return InputRule(name, re.compile(pattern, re.IGNORECASE | re.DOTALL), why)


# Deliberately narrow: each rule needs an unmistakable verb + object pair, in
# English and French. A broad list would block legitimate security work, and a
# keyword list is bypassable anyway (EV4); this one removes the obvious cases
# and logs which rule fired. The false positives we know of are in ADR-0027.
_DEFAULT_RULES: tuple[InputRule, ...] = (
    _rule(
        "prompt_override_fr",
        r"\b(?:ignore[rz]?|oublie[rz]?|abandonne[rz]?|d[ée]sob[ée]is(?:sez)?)\b"
        r"(?:.{0,40}\b(?:instructions?|consignes?|r[èe]gles?|directives?)\b"
        r".{0,25}\b(?:pr[ée]c[ée]dentes?|ant[ée]rieures?|ci-dessus|syst[èe]me)\b"
        r"|.{0,25}\b(?:toutes?|tes|vos)\b.{0,15}\b(?:instructions?|consignes?|r[èe]gles?)\b)",
        "tentative d'écraser les consignes de l'agent",
    ),
    _rule(
        "reveal_prompt_fr",
        r"\b(?:r[ée]v[èe]le[rz]?|affiche[rz]?|montre[rz]?|donne[rz]?|r[ée]p[èe]te[rz]?|recopie[rz]?)"
        r"\b.{0,30}\b(?:prompt syst[èe]me|tes instructions|ton prompt|tes consignes)\b",
        "demande de révéler le prompt système",
    ),
    _rule(
        "jailbreak_persona",
        r"\bdo anything now\b|\byou are now (?:DAN|unrestricted|unfiltered|jailbroken)\b"
        r"|\b(?:jailbreak|developer|mode d[ée]veloppeur)\s+mode\b",
        "persona de contournement connue (jailbreak)",
    ),
    _rule(
        "malware_request",
        r"\b(?:write|create|build|make|code|develop|[ée]cri[st]|cr[ée]e[rz]?|fais|g[ée]n[èe]re[rz]?"
        r"|programme[rz]?|d[ée]veloppe[rz]?)\b(?:(?!detect|scanner|analy|d[ée]tecteur|d[ée]tection).){0,40}"
        r"\b(?:ransomware|keylogger|botnet|spyware|rootkit|malware|trojan|cheval de troie"
        r"|virus informatique|computer virus)\b"
        r"(?!.{0,20}\b(?:detect|scanner|analy|d[ée]tecteur|d[ée]tection|signature))",
        "demande de création d'un logiciel malveillant",
    ),
    _rule(
        "credential_theft",
        r"\b(?:steal|exfiltrate|harvest|vole[rz]?|exfiltre[rz]?)\b.{0,40}"
        r"\b(?:passwords?|credentials?|cookies|mots? de passe|identifiants)\b",
        "demande de vol d'identifiants",
    ),
)
# Judged on the sanitized text (below), so these English markers also catch
# "ign\u200bore previous instructions" and fullwidth letters.
_BLOCKING_MARKERS = frozenset({"override_instructions", "reveal_prompt"})
_MARKER_WHY = {
    "override_instructions": "tentative d'écraser les consignes de l'agent",
    "reveal_prompt": "demande de révéler le prompt système",
}


@dataclass(frozen=True)
class InputRules:
    """Rules added by the user on top of the defaults.

    They can only add: the default rules cannot be turned off from a config
    file (same principle as the tool modes, ADR-0006). This is also how the
    "out-of-scope" part of EV2 is configured: a project that must not discuss
    salaries adds a pattern for it.
    """

    extra: tuple[InputRule, ...] = ()

    @classmethod
    def from_config(cls, raw: Sequence[Mapping[str, Any]] | None) -> InputRules:
        """Build from the `input_blocklist` list of config.json.

        Each entry is `{"name": ..., "pattern": <regex>, "why": ...}`. A bad
        entry raises ValueError: a typo must not leave the user thinking a topic
        is blocked when it is not.
        """
        if raw is None:
            return cls()
        if not isinstance(raw, (list, tuple)):
            raise ValueError("'input_blocklist' doit être une liste de règles")
        rules = []
        for index, entry in enumerate(raw):
            if not isinstance(entry, Mapping) or not isinstance(entry.get("pattern"), str):
                raise ValueError(f"input_blocklist[{index}] : « pattern » (texte) est obligatoire")
            unknown = set(entry) - {"name", "pattern", "why"}
            if unknown:
                raise ValueError(f"input_blocklist[{index}] : clés inconnues {sorted(unknown)}")
            try:
                rules.append(
                    _rule(
                        str(entry.get("name") or f"custom_{index}"),
                        entry["pattern"],
                        str(entry.get("why") or "sujet interdit par la configuration"),
                    )
                )
            except re.error as exc:
                raise ValueError(f"input_blocklist[{index}] : expression invalide ({exc})") from exc
        return cls(extra=tuple(rules))


def find_input_violation(text: str, rules: InputRules | None = None) -> tuple[str, str] | None:
    """First rule (name, why) that `text` breaks, or None. Works on the sanitized text."""
    seen = sanitize(text)
    for rule in (*_DEFAULT_RULES, *(rules.extra if rules else ())):
        if rule.pattern.search(seen):
            return rule.name, rule.why
    for marker in find_injection_markers(seen):
        if marker in _BLOCKING_MARKERS:
            return marker, _MARKER_WHY[marker]
    return None


def filter_input(text: str, rules: InputRules | None = None) -> tuple[bool, str]:
    """Input filter for the user's prompt. Returns `(allowed, text_or_reason)`.

    - Blocked: `(False, reason)`. The reason names the rule and what to change;
      it never repeats the prompt.
    - Allowed: `(True, cleaned)`. `cleaned` is the prompt without hidden
      characters or ANSI sequences, and with credentials masked, so a key
      pasted into the chat reaches neither the model, the saved session nor
      the profile. Emails and card numbers are NOT masked here: the user typed
      them on purpose, and masking would break requests like "write a regex
      for foo@bar.com". They are still masked in what tools return.

    The rules are matched on the fully normalized text, but the text returned
    is only stripped (no NFKC): the user's code must come back unchanged.
    """
    violation = find_input_violation(text, rules)
    if violation is not None:
        name, why = violation
        return False, f"règle « {name} » : {why}. Reformule ta demande."
    return True, mask_secrets(strip_invisible(strip_ansi(text)))


def filter_output(text: str) -> str:
    """Output filter for the gateway: no credential and no personal data survives."""
    return mask_pii(mask_secrets(text))


_KEY_BEGIN = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")
_KEY_END = re.compile(r"-----END [A-Z ]*PRIVATE KEY-----")


class StreamRedactor:
    """`filter_output` appliqué à la réponse du modèle pendant son streaming.

    Un secret peut
    arriver coupé en plusieurs morceaux (« AKIA » puis « IOSF… ») : le texte est
    donc retenu jusqu'à la fin de la ligne, puis filtré d'un bloc. Aucun motif de
    `filter_output` ne déborde d'une ligne, sauf la clé privée, suivie à part.
    Le prix : la réponse s'affiche ligne par ligne au lieu de mot par mot.
    """

    def __init__(self) -> None:
        self._pending = ""
        self._in_key = False

    def feed(self, text: str) -> str:
        """Le texte sûr à afficher maintenant (les lignes complètes)."""
        self._pending += text
        out = []
        while "\n" in self._pending:
            line, self._pending = self._pending.split("\n", 1)
            shown = self._line(line)
            if shown is not None:
                out.append(shown + "\n")
        return "".join(out)

    def flush(self) -> str:
        """La fin du texte, à la fin de la réponse ou avant un appel d'outil."""
        line, self._pending = self._pending, ""
        return (self._line(line) or "") if line else ""

    def _line(self, line: str) -> str | None:
        """La ligne filtrée ; None pour une ligne du corps d'une clé, retirée en entier."""
        if self._in_key:
            # Corps de la clé : rien n'est montré, jusqu'à la ligne de fin comprise.
            if _KEY_END.search(line):
                self._in_key = False
            return None
        if _KEY_BEGIN.search(line) and not _KEY_END.search(line):
            self._in_key = True
            return line[:_KEY_BEGIN.search(line).start()] + "[REDACTED:private_key]"
        return filter_output(line)
