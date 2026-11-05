"""
[X5] Planifier une tâche depuis la conversation, en langage naturel (ADR-0052).

L'agent propose une tâche récurrente (« résume les TODO chaque matin ») ; elle
n'est enregistrée qu'avec l'accord explicite de l'utilisateur, qui voit le prompt
exact et la fréquence. Ensuite, c'est `sensai-schedule` (cron ou `loop`) qui
l'exécute, sans surveillance, avec sa politique habituelle (actions risquées
refusées).

Garde-fous, parce qu'une tâche planifiée rejoue son prompt chaque jour sans
personne devant l'écran — le pire cas pour une instruction cachée dans une page
web ou un fichier lu :
- risque `write` : la passerelle demande TOUJOURS l'accord (une préférence ne
  peut pas assouplir ce niveau, `tool_policy.LOOSENABLE`) ;
- jamais proposé à une tâche planifiée (`sensai-schedule` ne charge que
  `build_registry`) ni à un sous-agent (`delegate_tool.NEVER_DELEGATED`) ;
- le prompt est borné et ne peut pas lui-même demander de planifier.
"""
from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import Any, ClassVar

from sensai.core.tools import ToolResult
from sensai.knowledge.memory import ensure_private_dir
from sensai.scheduling.tasks import (
    TASKS_FILE,
    ScheduleStoreError,
    Task,
    TaskStore,
    format_interval,
    parse_interval,
    validate_task_id,
)

MAX_PROMPT_CHARS = 2000


def normalize_id(raw: str) -> str:
    """Un identifiant accepté par sensai-schedule (a-z, 0-9, « - », 40 caractères).
    Essai réel du 2026-11-01 : le modèle proposait « resume_todo », refusé."""
    text = unicodedata.normalize("NFKD", str(raw)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-")[:40].strip("-")


class ScheduleTaskTool:
    name = "schedule_task"
    description = (
        "Propose une tâche récurrente que l'agent exécutera seul, sans surveillance "
        "(ex. « chaque matin, résume les TODO »). Utilise-le seulement si l'utilisateur "
        "demande explicitement de planifier ou de répéter quelque chose. L'utilisateur "
        "doit accepter ; la tâche est ensuite lancée par sensai-schedule. "
        "every : 30m, 1h, 1d, 7d…"
    )
    # Écrit un état durable qui rejouera un prompt sans personne : accord toujours requis.
    risk = "write"
    parameters: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "id": {"type": "string",
                   "description": "Identifiant court : minuscules, chiffres et « - »."},
            "prompt": {"type": "string",
                       "description": "La consigne complète, compréhensible sans la conversation."},
            "every": {"type": "string", "description": "Fréquence : 30m, 1h, 1d, 7d…"},
        },
        "required": ["id", "prompt", "every"],
        "additionalProperties": False,
    }

    def __init__(self, data_dir: str | Path) -> None:
        self.store = TaskStore(Path(data_dir) / "schedule" / TASKS_FILE)

    def describe_call(self, **args: Any) -> str:
        """Ce que l'utilisateur approuve : la tâche telle qu'elle sera rejouée."""
        try:
            every = format_interval(parse_interval(str(args.get("every", ""))))
        except ValueError:
            every = str(args.get("every", ""))
        return (
            f"Planifier la tâche « {normalize_id(args.get('id', ''))} », toutes les {every}, "
            "exécutée "
            "SANS SURVEILLANCE par sensai-schedule (actions risquées refusées) :\n\n"
            f"{args.get('prompt', '')}"
        )

    def run(self, **kwargs: Any) -> ToolResult:
        prompt = str(kwargs.get("prompt") or "").strip()
        try:
            task_id = validate_task_id(normalize_id(kwargs.get("id") or ""))
            interval = parse_interval(str(kwargs.get("every") or ""))
            if not prompt:
                raise ValueError("Le prompt est vide.")
            if len(prompt) > MAX_PROMPT_CHARS:
                raise ValueError(f"Le prompt dépasse {MAX_PROMPT_CHARS} caractères.")
            if "schedule_task" in prompt or "/schedule" in prompt:
                raise ValueError("Une tâche planifiée ne peut pas en planifier d'autres.")
            ensure_private_dir(self.store.path.parent.parent)
            ensure_private_dir(self.store.path.parent)
            self.store.add(Task(id=task_id, prompt=prompt, interval_s=interval))
        except ScheduleStoreError as e:
            return ToolResult(ok=False, content=f"Fichier des tâches illisible : {e}")
        except ValueError as e:
            return ToolResult(ok=False, content=f"Tâche refusée : {e}")
        return ToolResult(
            ok=True,
            content=(f"Tâche « {task_id} » planifiée toutes les {format_interval(interval)}. "
                     "Elle tournera quand sensai-schedule loop (ou run-due par cron) tourne ; "
                     "dis-le à l'utilisateur."),
        )
