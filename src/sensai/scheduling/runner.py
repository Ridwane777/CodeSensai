"""
Exécution des tâches planifiées — feature [X5], ADR-0016.

Personne n'est devant l'écran quand une tâche tourne. Les garanties :

- tout appel d'outil passe par une ToolGateway dont le confirmeur est
  `deny_all` : un outil qui demande confirmation (écriture, exécution) est
  toujours refusé ; aucune préférence ne peut l'assouplir (tool_policy.py) ;
- une tâche qui plante n'empêche pas les suivantes ;
- une même tâche ne tourne jamais deux fois en même temps (fichier verrou) ;
- chaque exécution laisse un compte rendu JSON.
"""
from __future__ import annotations

import dataclasses
import json
import logging
import os
import shutil
import time
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sensai.core.agent import run_agent_turn
from sensai.core.events import Done, Error, Event, Token
from sensai.core.tools import ToolRegistry, ToolResult
from sensai.execution.gateway import ToolGateway, deny_all
from sensai.execution.guardrails import InputRules, check_input, filter_input, filter_output
from sensai.execution.tool_policy import ToolPreferences
from sensai.knowledge.memory import date_block
from sensai.registry import build_registry

from .tasks import Task, TaskStore, atomic_write, parse_time, utc_now, validate_task_id

log = logging.getLogger(__name__)

KEEP_RUNS = 50

OK = "ok"
ERROR = "error"
MAX_ITERATIONS = "max_iterations"
TIMEOUT = "timeout"
SKIPPED_LOCKED = "skipped_locked"
# Statuts qui comptent comme un échec pour le code de sortie de la commande.
FAILED_STATUSES = frozenset({ERROR, MAX_ITERATIONS, TIMEOUT})

UNATTENDED_NOTE = (
    "Cette tâche s'exécute sans surveillance : personne ne peut confirmer une action. "
    "Si un outil est refusé, ne le relance pas : n'insiste pas et n'en contourne pas le refus. "
    "Termine en indiquant clairement ce que tu n'as pas pu faire."
)

Agent = Callable[[str, str, list[dict], Any], Iterator[Event]]
GatewayFactory = Callable[[Task], Any]


def runs_path(base_dir: Path, task_id: str) -> Path:
    # Défense en profondeur : un identifiant ne doit jamais sortir du dossier.
    return base_dir / "runs" / validate_task_id(task_id)


def lock_path(base_dir: Path, task_id: str) -> Path:
    return base_dir / "locks" / f"{validate_task_id(task_id)}.lock"


def delete_runs(base_dir: Path, task_id: str) -> None:
    shutil.rmtree(runs_path(base_dir, task_id), ignore_errors=True)


def list_runs(base_dir: Path, task_id: str) -> list[dict]:
    """Comptes rendus d'une tâche, du plus récent au plus ancien. Les fichiers
    illisibles sont ignorés : un compte rendu abîmé ne doit rien bloquer."""
    folder = runs_path(base_dir, task_id)
    if not folder.is_dir():
        return []
    records = []
    for path in sorted(folder.glob("*.json"), reverse=True):
        try:
            records.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            log.warning("compte rendu illisible ignoré : %s", path)
    return records


def unattended_preferences(
    base: ToolPreferences, registry: ToolRegistry, allowed: list[str] | None
) -> ToolPreferences:
    """Préférences d'une exécution sans surveillance.

    `confirm_after_untrusted` est forcé : après la lecture d'un contenu non
    fiable, plus aucun outil non lecture ne part sans confirmation — donc,
    ici, plus aucun. Une liste `allowed` retire les autres outils de ce que le
    modèle voit. On ne touche pas à `modes` : de toute façon la politique
    ignore tout assouplissement pour WRITE et EXECUTE.
    """
    disabled = set(base.disabled)
    if allowed is not None:
        keep = set(allowed)
        disabled |= {d["name"] for d in registry.describe_all() if d["name"] not in keep}
    return dataclasses.replace(
        base, disabled=frozenset(disabled), confirm_after_untrusted=True
    )


def build_unattended_gateway(
    registry: ToolRegistry, base: ToolPreferences, allowed: list[str] | None = None
) -> ToolGateway:
    """Une passerelle neuve par exécution : l'état « contenu non fiable lu » ne
    déborde pas d'une tâche sur l'autre. `deny_all` est passé explicitement."""
    gateway = ToolGateway(
        registry,
        unattended_preferences(base, registry, allowed),
        confirm=deny_all,
        # Personne ne relit ce qu'un outil renvoie : les secrets sont masqués
        # avant le modèle et le compte rendu (EV4, OUT-15).
        input_guards=[check_input],
        output_filters=[filter_output],
    )
    gateway.reset_untrusted()
    return gateway


class _RecordingGateway:
    """Enveloppe la passerelle pour garder, par appel d'outil, le nom et l'issue
    (ok ou code d'erreur) — jamais les arguments, qui peuvent contenir des secrets."""

    def __init__(self, inner: Any) -> None:
        self.inner = inner
        self.calls: list[dict[str, Any]] = []

    def describe_all(self) -> list[dict[str, Any]]:
        return self.inner.describe_all()

    def call(self, name: str, /, **kwargs: Any) -> ToolResult:
        try:
            result = self.inner.call(name, **kwargs)
        except Exception:
            self.calls.append({"name": name, "ok": False, "error": "exception"})
            raise
        entry: dict[str, Any] = {"name": name, "ok": result.ok}
        if not result.ok:
            entry["error"] = result.data.get("error", "tool_error")
        self.calls.append(entry)
        return result


class Scheduler:
    def __init__(
        self,
        store: TaskStore,
        base_dir: Path,
        *,
        host: str = "",
        model: str = "",
        system_prompt: str = "",
        clock: Callable[[], datetime] = utc_now,
        monotonic: Callable[[], float] = time.monotonic,
        agent: Agent = run_agent_turn,
        gateway_factory: GatewayFactory | None = None,
        registry: ToolRegistry | None = None,
        preferences: ToolPreferences | None = None,
        keep_runs: int = KEEP_RUNS,
        input_rules: InputRules | None = None,
    ) -> None:
        self.store = store
        # Le filtre d'entrée du CLI et du web (EV2, ADR-0027) s'applique aussi au
        # prompt d'une tâche : il est rejoué sans personne devant l'écran.
        self.input_rules = input_rules
        self.base_dir = Path(base_dir)
        self.host = host
        self.model = model
        self.system_prompt = system_prompt
        self.clock = clock
        self.monotonic = monotonic
        self.agent = agent
        self.registry = registry
        self.preferences = preferences or ToolPreferences()
        self.keep_runs = keep_runs
        self.gateway_factory = gateway_factory or self._default_gateway

    def _default_gateway(self, task: Task) -> ToolGateway:
        if self.registry is None:
            self.registry = build_registry()
        return build_unattended_gateway(self.registry, self.preferences, task.tools)

    # -- quoi lancer ----------------------------------------------------------

    def due_tasks(self, now: datetime | None = None) -> list[Task]:
        now = now or self.clock()
        return [t for t in self.store.load() if t.is_due(now)]

    def run_due(self, now: datetime | None = None) -> list[dict]:
        """Une passe : joue chaque tâche échue, l'une après l'autre.

        Lève ScheduleStoreError si le fichier des tâches est cassé (rien n'est
        alors lancé). Toute autre panne est isolée à la tâche qui la cause.
        """
        records = []
        for task in self.due_tasks(now):
            try:
                records.append(self.run_task(task))
            except Exception as exc:  # une tâche cassée ne doit pas empêcher les suivantes
                log.exception("tâche %s : échec inattendu", task.id)
                records.append(self._salvage(task, exc))
        return records

    def _salvage(self, task: Task, exc: Exception) -> dict:
        """Dernier recours quand run_task lui-même a planté (disque plein, fichier
        des tâches devenu illisible...) : on note ce qu'on peut, sans relancer d'exception."""
        now = self.clock()
        record = self._record(task, now, now, ERROR, error=f"{type(exc).__name__}: {exc}")
        for action in (
            lambda: self._write_record(task.id, record, now),
            lambda: self.store.update(task.id, last_run_at=now.isoformat(), last_status=ERROR),
        ):
            try:
                action()
            except Exception:
                log.exception("tâche %s : impossible de noter l'échec", task.id)
        return record

    def loop(
        self,
        every_s: float,
        sleep: Callable[[float], None] = time.sleep,
        max_passes: int | None = None,
    ) -> None:
        """Appelle run_due toutes les `every_s` secondes (mode de secours quand
        on n'a ni cron ni systemd). `sleep` est injectable pour les tests."""
        passes = 0
        while max_passes is None or passes < max_passes:
            self.run_due()
            passes += 1
            if max_passes is not None and passes >= max_passes:
                break
            sleep(every_s)

    # -- une exécution ----------------------------------------------------------

    def run_task(self, task: Task) -> dict:
        """Joue `task` maintenant, échue ou non (c'est `run_due` qui filtre)."""
        started = self.clock()
        lock = self._acquire_lock(task, started)
        if lock is None:
            log.warning("tâche %s déjà en cours : exécution ignorée", task.id)
            record = self._record(
                task, started, started, SKIPPED_LOCKED, error="une exécution est déjà en cours"
            )
            self._write_record(task.id, record, started)
            return record
        try:
            try:
                record = self._execute(task, started)
            except Exception as exc:
                log.exception("tâche %s en échec", task.id)
                record = self._record(
                    task, started, self.clock(), ERROR, error=f"{type(exc).__name__}: {exc}"
                )
            self._write_record(task.id, record, started)
            self.store.update(
                task.id, last_run_at=started.isoformat(), last_status=record["status"]
            )
        finally:
            self._release_lock(lock)
        return record

    def _execute(self, task: Task, started: datetime) -> dict:
        gateway = _RecordingGateway(self.gateway_factory(task))
        # Une tâche ne doit pas hériter de la méfiance (ou de la confiance) d'une autre.
        reset = getattr(gateway.inner, "reset_untrusted", None)
        if callable(reset):
            reset()
        # La date du jour, calculée à chaque exécution : une boucle `loop` peut tourner
        # des jours (sans elle, le modèle se croyait en 2024, essai du 2026-11-01).
        system = f"{UNATTENDED_NOTE}\n\n{date_block()}\n\n{self.system_prompt}".strip()
        allowed, prompt = filter_input(task.prompt, self.input_rules)
        if not allowed:
            # Bloquée comme le serait le même texte tapé dans le chat : rien ne part au modèle.
            return self._record(task, started, self.clock(), ERROR,
                                error=f"Bloquée par le filtre d'entrée : {prompt}")
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ]
        answer: list[str] = []
        error: str | None = None
        reason = "final_answer"
        timed_out = False
        deadline = self.monotonic() + task.timeout_s

        events = self.agent(self.host, self.model, messages, gateway)
        try:
            for event in events:
                if isinstance(event, Token):
                    answer.append(event.text)
                elif isinstance(event, Error):
                    error = event.message
                elif isinstance(event, Done):
                    reason = event.reason
                    break
                # Le délai n'est vérifié qu'entre deux événements : un appel
                # bloqué dans le modèle ou dans un outil ne peut pas être
                # interrompu d'ici (ADR-0016).
                if self.monotonic() >= deadline:
                    timed_out = True
                    break
        finally:
            close = getattr(events, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    log.exception("tâche %s : fermeture du flux en échec", task.id)

        if timed_out:
            status, error = TIMEOUT, f"délai de {task.timeout_s} s dépassé"
        elif error is not None or reason == "error":
            status, error = ERROR, error or "l'agent a signalé une erreur"
        elif reason == "max_iterations":
            status, error = MAX_ITERATIONS, "nombre maximal d'étapes atteint sans réponse finale"
        else:
            status = OK
        return self._record(
            task,
            started,
            self.clock(),
            status,
            answer="".join(answer),
            tool_calls=gateway.calls,
            error=error,
        )

    # -- comptes rendus ----------------------------------------------------------

    @staticmethod
    def _record(
        task: Task,
        started: datetime,
        finished: datetime,
        status: str,
        *,
        answer: str = "",
        tool_calls: list[dict] | None = None,
        error: str | None = None,
    ) -> dict:
        return {
            "task_id": task.id,
            "started_at": started.isoformat(),
            "finished_at": finished.isoformat(),
            "status": status,
            "answer": answer,
            "tool_calls": tool_calls or [],
            "error": error,
        }

    def _write_record(self, task_id: str, record: dict, started: datetime) -> None:
        folder = runs_path(self.base_dir, task_id)
        stamp = started.astimezone(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        path = folder / f"{stamp}.json"
        n = 0
        while path.exists():  # horloge identique (tests, --force à la suite)
            n += 1
            path = folder / f"{stamp}_{n}.json"
        atomic_write(path, json.dumps(record, ensure_ascii=False, indent=2) + "\n")
        for old in sorted(folder.glob("*.json"))[: -self.keep_runs]:
            try:
                old.unlink()
            except OSError:
                log.warning("ancien compte rendu non supprimé : %s", old)

    # -- verrou ----------------------------------------------------------------

    def _acquire_lock(self, task: Task, now: datetime) -> Path | None:
        """Crée le verrou avec O_EXCL (atomique). Un verrou de plus de deux fois le
        délai de la tâche est jugé abandonné (processus tué) et repris.

        Simple et fondé sur le temps : deux processus qui reprennent le même
        verrou périmé au même instant peuvent se chevaucher (ADR-0016).
        """
        path = lock_path(self.base_dir, task.id)
        path.parent.mkdir(parents=True, exist_ok=True)
        for attempt in range(2):
            try:
                fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            except FileExistsError:
                if attempt == 0 and self._lock_is_stale(path, task, now):
                    log.warning("tâche %s : verrou périmé supprimé (%s)", task.id, path)
                    try:
                        path.unlink()
                    except FileNotFoundError:
                        pass
                    continue
                return None
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump({"pid": os.getpid(), "started_at": now.isoformat()}, f)
            return path
        return None

    @staticmethod
    def _lock_is_stale(path: Path, task: Task, now: datetime) -> bool:
        try:
            started = parse_time(json.loads(path.read_text(encoding="utf-8"))["started_at"])
        except (OSError, ValueError, KeyError, TypeError):
            # Verrou vide ou illisible (créé à l'instant par un autre processus ?) :
            # on se fie à la date du fichier.
            try:
                started = datetime.fromtimestamp(path.stat().st_mtime, UTC)
            except OSError:
                return False
        return now - started > timedelta(seconds=2 * task.timeout_s)

    @staticmethod
    def _release_lock(path: Path) -> None:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
