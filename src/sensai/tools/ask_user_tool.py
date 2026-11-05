"""
[Lot D] Poser une question à l'utilisateur — feature [X4] Questions & Forms (ADR-0046).

L'agent appelle `ask_user` quand il lui manque une information qu'il ne peut
pas trouver seul (un choix, un nom, une préférence). L'outil ne sait pas
comment on répond : il reçoit un `Asker`, fourni par l'interface.

- CLI : `terminal_asker` pose les questions une à une dans le terminal.
- Web : `sensai.web.questions.WebQuestionBroker` envoie un formulaire au
  navigateur et attend la réponse (même mécanique que la confirmation, ADR-0015).

Règles :
- Les champs viennent du modèle : ils sont validés ici (types, nombre, tailles)
  avant d'être montrés. Un formulaire invalide est un échec d'outil, que le
  modèle peut corriger.
- Pas de réponse (délai, onglet fermé, interruption) : l'outil échoue et le dit,
  l'agent ne doit pas inventer la réponse.
- Les réponses repartent au modèle comme résultat d'outil : la passerelle leur
  applique les mêmes filtres que toute sortie (EV2), un secret tapé par erreur
  est donc masqué.
"""
from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, ClassVar

from sensai.core.tools import ToolResult

MAX_FIELDS = 8
MAX_OPTIONS = 12
MAX_LABEL_CHARS = 200
MAX_ANSWER_CHARS = 2000
# Le temps laissé à l'utilisateur pour répondre. Sous le délai de l'outil
# (`timeout_s`), lui-même sous `tool_timeout_s` (120 s par défaut) : sinon la
# passerelle couperait l'outil avant qu'il ait pu dire « pas de réponse ».
ANSWER_TIMEOUT_S = 100.0
KINDS = ("text", "choice", "toggle")


@dataclass(frozen=True)
class Question:
    """Un formulaire validé, prêt à être montré."""

    title: str
    fields: tuple[dict[str, Any], ...]


# Renvoie les valeurs saisies (identifiant du champ -> valeur), ou None si
# l'utilisateur n'a pas répondu.
Asker = Callable[[Question], "dict[str, Any] | None"]


class FormError(ValueError):
    """Formulaire ou réponse invalide ; le message est destiné au modèle ou au client."""


def _text(value: Any, what: str, limit: int = MAX_LABEL_CHARS) -> str:
    if not isinstance(value, str) or not value.strip():
        raise FormError(f"{what} doit être un texte non vide")
    if len(value) > limit:
        raise FormError(f"{what} dépasse {limit} caractères")
    return value.strip()


def parse_question(title: Any, fields: Any) -> Question:
    """Valide le formulaire proposé par le modèle. Lève FormError."""
    clean_title = _text(title, "title")
    if not isinstance(fields, list) or not fields:
        raise FormError("fields doit être une liste non vide")
    if len(fields) > MAX_FIELDS:
        raise FormError(f"au plus {MAX_FIELDS} champs")
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for i, raw in enumerate(fields):
        if not isinstance(raw, dict):
            raise FormError(f"fields[{i}] doit être un objet")
        field_id = _text(raw.get("id"), f"fields[{i}].id", 64)
        if field_id in seen:
            raise FormError(f"identifiant de champ en double : {field_id}")
        seen.add(field_id)
        kind = raw.get("kind", "text")
        if kind not in KINDS:
            raise FormError(f"fields[{i}].kind doit valoir {', '.join(KINDS)}")
        field: dict[str, Any] = {"id": field_id, "kind": kind,
                                 "label": _text(raw.get("label"), f"fields[{i}].label")}
        if kind == "choice":
            options = raw.get("options")
            if not isinstance(options, list) or not 2 <= len(options) <= MAX_OPTIONS:
                raise FormError(f"fields[{i}].options : entre 2 et {MAX_OPTIONS} choix")
            field["options"] = [_text(o, f"fields[{i}].options") for o in options]
            if len(set(field["options"])) != len(field["options"]):
                raise FormError(f"fields[{i}].options : choix en double")
        elif kind == "text" and raw.get("placeholder") is not None:
            field["placeholder"] = _text(raw.get("placeholder"), f"fields[{i}].placeholder")
        out.append(field)
    return Question(clean_title, tuple(out))


def check_answers(question: Question, values: Any) -> dict[str, Any]:
    """Vérifie les valeurs reçues contre le formulaire. Lève FormError.

    Chaque champ doit avoir une valeur du bon type : un texte (non vide), un des
    choix proposés, ou un booléen. Rien d'autre n'est accepté.
    """
    if not isinstance(values, dict):
        raise FormError("les réponses doivent être un objet")
    expected = {f["id"]: f for f in question.fields}
    unknown = set(values) - set(expected)
    if unknown:
        raise FormError(f"champ inconnu : {sorted(unknown)[0]}")
    clean: dict[str, Any] = {}
    for field_id, field in expected.items():
        if field_id not in values:
            raise FormError(f"réponse manquante : {field_id}")
        value = values[field_id]
        if field["kind"] == "toggle":
            if not isinstance(value, bool):
                raise FormError(f"{field_id} doit être vrai ou faux")
        elif field["kind"] == "choice":
            if value not in field["options"]:
                raise FormError(f"{field_id} : choix inconnu")
        else:
            value = _text(value, field_id, MAX_ANSWER_CHARS)
        clean[field_id] = value
    return clean


class AskUserTool:
    name = "ask_user"
    description = (
        "Pose une question à l'utilisateur sous forme de petit formulaire et attend sa "
        "réponse. Utilise-le seulement quand il te manque une information que tu ne peux "
        "ni trouver dans le projet ni déduire (un choix entre plusieurs options, un nom, "
        "une préférence). Une question courte, au plus quelques champs. Si l'outil échoue "
        "faute de réponse, n'invente pas la réponse : dis ce qui manque."
    )
    # Ne touche à rien : seule une personne est sollicitée.
    risk = "read"
    timeout_s = ANSWER_TIMEOUT_S + 10.0
    parameters: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "La question, en une phrase."},
            "fields": {
                "type": "array",
                "description": (
                    "Les informations demandées. kind : text (réponse libre), choice "
                    "(un choix parmi options), toggle (oui / non)."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "kind": {"type": "string", "enum": list(KINDS)},
                        "label": {"type": "string"},
                        "options": {"type": "array", "items": {"type": "string"}},
                        "placeholder": {"type": "string"},
                    },
                    "required": ["id", "label"],
                },
            },
        },
        "required": ["title", "fields"],
        "additionalProperties": False,
    }

    def __init__(self, asker: Asker | None) -> None:
        self.asker = asker

    def describe_call(self, **args: Any) -> str:
        return f"Demander à l'utilisateur : {args.get('title', '')}"

    def run(self, **kwargs: Any) -> ToolResult:
        if self.asker is None:
            return ToolResult(ok=False, content="Aucune personne ne peut répondre ici "
                                                "(exécution sans interface).")
        try:
            question = parse_question(kwargs.get("title"), kwargs.get("fields"))
        except FormError as e:
            return ToolResult(ok=False, content=f"Formulaire invalide : {e}.")
        values = self.asker(question)
        if values is None:
            return ToolResult(ok=False, content="L'utilisateur n'a pas répondu : ne suppose "
                                                "pas la réponse, dis ce qui te manque.")
        return ToolResult(ok=True, content="Réponses de l'utilisateur : "
                                           + json.dumps(values, ensure_ascii=False))


def terminal_asker(read: Callable[[str], str] = input,
                   show: Callable[[str], None] = print) -> Asker:
    """Le `Asker` du CLI : une question par ligne. Ctrl+D ou Ctrl+C : pas de réponse."""

    def ask(question: Question) -> dict[str, Any] | None:
        show(f"\n? {question.title}")
        values: dict[str, Any] = {}
        try:
            for field in question.fields:
                if field["kind"] == "choice":
                    for n, option in enumerate(field["options"], 1):
                        show(f"  {n}. {option}")
                    while True:
                        raw = read(f"  {field['label']} (numéro) : ").strip()
                        if raw.isdigit() and 1 <= int(raw) <= len(field["options"]):
                            values[field["id"]] = field["options"][int(raw) - 1]
                            break
                elif field["kind"] == "toggle":
                    raw = read(f"  {field['label']} (o/n) : ").strip().lower()
                    values[field["id"]] = raw in ("o", "oui", "y", "yes")
                else:
                    while not (raw := read(f"  {field['label']} : ").strip()):
                        pass
                    values[field["id"]] = raw[:MAX_ANSWER_CHARS]
        except (EOFError, KeyboardInterrupt):
            return None
        return values

    return ask
