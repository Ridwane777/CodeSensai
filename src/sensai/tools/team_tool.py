"""
Équipe d'agents spécialisés qui se passent le travail — feature [A2]
Multi-Agent Orchestration (ADR-0038).

`team_task` enchaîne trois agents spécialisés (rôles définis dans
delegate_tool.ROLES) : l'explorateur rassemble le contexte, le développeur
produit la modification à partir de ce rapport, le relecteur la critique. Si
le relecteur répond « À CORRIGER », le travail revient une fois au développeur
avec la critique, puis repasse au relecteur. Chaque agent est un sous-agent de
DelegateTool : même passerelle, mêmes confirmations, seulement les outils de
son rôle, et pas de redélégation.

Toute la chaîne tient dans le délai d'un seul outil (la passerelle l'abandonne
au-delà) : chaque étape reçoit le temps qui reste, et la chaîne s'arrête en le
disant si le temps manque.
"""
from __future__ import annotations

import re
import time
import unicodedata
from collections.abc import Callable
from pathlib import PurePosixPath
from typing import Any, ClassVar

from sensai.core.tools import ToolResult
from sensai.tools.delegate_tool import (
    DELEGATION_TIMEOUT_S,
    MAX_DELEGATION_DEPTH,
    STOP_MARGIN_S,
    DelegateTool,
    _depth,
)

MAX_CORRECTIONS = 1
# En dessous, lancer une étape de plus ne servirait à rien : un seul appel au
# modèle en prend souvent autant (mesuré, 6 à 30 s par sous-agent).
MIN_STEP_S = 10.0
# Au-delà, le contenu d'un fichier écrit est tronqué dans la consigne du relecteur.
MAX_REVIEWED_CHARS = 12_000


# Un nom de fichier cité dans la tâche : « stats.py », « src/app/main.ts »…
_FILE_NAME = re.compile(r"(?<![\w/.-])([\w./-]*\w\.[A-Za-z0-9]{1,5})(?![\w/-])")


def named_files(task: str) -> set[str]:
    """Les fichiers que la tâche nomme, tels qu'écrits (sans « ./ »)."""
    return {m.removeprefix("./") for m in _FILE_NAME.findall(task)}


def misplaced(task: str, created: set[str]) -> list[tuple[str, str]]:
    """(fichier créé, fichier demandé) : un fichier CRÉÉ qui porte le nom d'un
    fichier cité par la tâche, mais ailleurs. Essai du 2026-11-01 : pour « ajoute
    mediane à stats.py », le développeur a créé src/sensai/stats.py, et le
    relecteur a validé ; l'agent a annoncé que stats.py était modifié."""
    out = []
    for path in sorted(created):
        clean = path.removeprefix("./")
        for name in named_files(task):
            if PurePosixPath(clean).name == PurePosixPath(name).name and clean != name:
                out.append((path, name))
    return out


def review_request(task: str, work: str, written: dict[str, str]) -> str:
    """La consigne du relecteur : la tâche, le compte rendu du développeur et
    surtout le contenu RÉELLEMENT écrit. Mesuré avec le vrai modèle : avec le seul compte
    rendu, le relecteur validait 6 fois sur 6 un travail faux, sans rien lire."""
    if written:
        files = "\n\n".join(
            f"### {path}\n```\n{content[:MAX_REVIEWED_CHARS]}\n```"
            for path, content in written.items()
        )
        evidence = f"Fichiers réellement écrits par le développeur (contenu exact) :\n{files}"
    else:
        evidence = "Le développeur n'a écrit aucun fichier."
    names = sorted(named_files(task))
    target = (f"\n\nFichiers que la tâche demande de modifier : {', '.join(names)}. Vérifie que "
              "ce sont bien eux qui ont été écrits, à ce chemin exact ; sinon, À CORRIGER."
              if names else "")
    return (
        f"Tâche : {task}\n\nCompte rendu du développeur (à ne pas croire sur parole) :\n"
        f"{work}\n\n{evidence}{target}\n\nJuge le code ci-dessus, pas le compte rendu : "
        "essaie-le mentalement sur quelques exemples, dont des cas limites."
    )


def verdict(review: str) -> str:
    """« validé », « à corriger » ou « illisible », d'après le début de la relecture."""
    head = unicodedata.normalize("NFKD", review.strip()[:40]).encode("ascii", "ignore")
    text = head.decode().upper().lstrip("*#> ")
    if text.startswith("VALIDE"):
        return "validé"
    if text.startswith("A CORRIGER"):
        return "à corriger"
    return "illisible"


class TeamTool:
    name = "team_task"
    description = (
        "Confie une modification de code à une équipe de trois agents spécialisés qui se "
        "passent le travail : un explorateur lit le code concerné, un développeur fait la "
        "modification, un relecteur la vérifie (et la renvoie au développeur s'il trouve "
        "un défaut). Utilise-le pour écrire ou corriger du code quand une vérification "
        "compte, ou quand l'utilisateur demande l'équipe. Pas pour une simple question."
    )
    # Le développeur peut écrire et exécuter : même raisonnement que delegate_task.
    risk = "execute"
    timeout_s = DELEGATION_TIMEOUT_S
    parameters: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "task": {
                "type": "string",
                "description": (
                    "La tâche complète, formulée pour être comprise sans la conversation "
                    "en cours (fichiers concernés, résultat attendu)."
                ),
            },
        },
        "required": ["task"],
        "additionalProperties": False,
    }

    def __init__(
        self,
        delegate: DelegateTool,
        notify: Callable[[str], None] | None = None,
        on_handoff: Callable[[str], None] | None = None,
        test_runner: Callable[[], tuple[bool, str]] | None = None,
    ):
        self.delegate = delegate
        # Les tests du projet, s'il en a (ADR-0056, point 3) : ils remplacent le
        # verdict du relecteur, qui validait des travaux faux lors des essais.
        self.test_runner = test_runner
        # Affiche chaque passage de relais pendant le travail (le terminal, en CLI).
        self.notify = notify or (lambda message: None)
        # Le même relais, sous forme structurée : le rôle qui prend la main
        # (le web en fait un événement `agent_handoff`, X1).
        self.on_handoff = on_handoff or (lambda role: None)

    def describe_call(self, **args: Any) -> str:
        task = args.get("task", "")
        return f"Confier à l'équipe (explorateur → développeur → relecteur) : {task}"

    def run(self, **kwargs) -> ToolResult:
        task = (kwargs.get("task") or "").strip()
        if not task:
            return ToolResult(ok=False, content="La tâche est vide.")
        if _depth.get() >= MAX_DELEGATION_DEPTH:
            return ToolResult(ok=False, content="Un sous-agent ne lance pas d'équipe.")

        deadline = time.monotonic() + self.timeout_s - STOP_MARGIN_S
        path: list[str] = []
        steps: list[tuple[str, str]] = []
        written: dict[str, str] = {}
        created: set[str] = set()

        def record(name: str, args: dict, result: ToolResult) -> None:
            if name == "write_file" and result.ok and "path" in args:
                written[str(args["path"])] = str(args.get("content", ""))
                if str(result.content).startswith("Created"):
                    created.add(str(args["path"]))

        def step(role: str, consigne: str) -> ToolResult | None:
            if deadline - time.monotonic() < MIN_STEP_S:
                return None
            if path:
                self.notify(f"relais : {path[-1]} → {role}")
            else:
                self.notify(f"équipe : {role} au travail")
            path.append(role)
            self.on_handoff(role)
            result = self.delegate.delegate(consigne, role=role, deadline=deadline, on_call=record)
            steps.append((role, result.content))
            return result

        def stopped(at: str) -> ToolResult:
            return self._report(path, steps, f"arrêtée faute de temps avant {at}", ok=False)

        report = step("explorateur", f"Tâche de l'équipe : {task}\n\nRassemble le contexte utile.")
        if report is None:
            return stopped("l'explorateur")
        context = report.content if report.ok else "(l'explorateur n'a rien pu rapporter)"

        work = step(
            "developpeur",
            f"Tâche : {task}\n\nRapport de l'explorateur :\n{context}\n\nFais la modification.",
        )
        if work is None:
            return stopped("le développeur")

        state = "illisible"
        wrong: list[tuple[str, str]] = []
        for attempt in range(MAX_CORRECTIONS + 1):
            wrong = misplaced(task, created)
            if self.test_runner is not None and not written:
                # Les tests d'un projet inchangé passent : ils ne prouvent rien. Essai
                # du 2026-11-06 : écriture refusée, et pourtant « validé ».
                critique = ("À CORRIGER. Aucun fichier n'a été modifié : lis les fichiers "
                            "concernés, puis fais la modification avec write_file.")
                state = "à corriger"
            elif wrong:
                # Contrôle mécanique, avant toute relecture : un fichier écrit au
                # mauvais endroit n'a pas à être jugé, il est renvoyé tel quel.
                critique = "À CORRIGER. " + " ; ".join(
                    f"tu as créé {made} au lieu de modifier {asked} : lis {asked}, puis "
                    f"réécris-le avec write_file (overwrite à true)" for made, asked in wrong)
                state = "à corriger"
            elif self.test_runner is not None:
                self.notify("équipe : tests du projet")
                passed, output = self.test_runner()
                steps.append(("tests du projet", output or "(aucune sortie)"))
                state = "validé" if passed else "à corriger"
                critique = f"À CORRIGER. Les tests du projet échouent :\n{output}"
            else:
                review = step("relecteur", review_request(task, work.content, written))
                if review is None:
                    return stopped("le relecteur")
                state = verdict(review.content) if review.ok else "illisible"
                critique = review.content
            if state != "à corriger" or attempt == MAX_CORRECTIONS:
                break
            created.clear()
            work = step(
                "developpeur",
                f"Tâche : {task}\n\nTon travail précédent :\n{work.content}\n\n"
                f"Critique :\n{critique}\n\nCorrige ces défauts.",
            )
            if work is None:
                return stopped("la correction du développeur")
        wrong = misplaced(task, created)
        if wrong:
            state = "à corriger"
        judge = "des tests du projet" if self.test_runner is not None else "du relecteur"
        end = f"verdict {judge} : {state}"
        if self.test_runner is not None and not written:
            state = "à corriger"
            end = "verdict : à corriger — aucun fichier modifié, les tests n'ont pas été lancés"
        if wrong:
            end = ("verdict : à corriger — fichier écrit au mauvais endroit : " + ", ".join(
                f"{made} (la tâche demandait {asked}, qui n'a pas été modifié)"
                for made, asked in wrong))
        if state != "validé":
            # La chaîne a fait son travail : c'est un résultat, pas une panne. Mesuré
            # avec le vrai modèle : rendu comme un échec, l'agent principal relançait l'équipe
            # (3 fois, 190 s) au lieu de transmettre les remarques.
            end += " ; ne relance pas l'équipe, transmets ces remarques à l'utilisateur"
        return self._report(path, steps, end, ok=True)

    @staticmethod
    def _report(path: list[str], steps: list[tuple[str, str]], end: str, ok: bool) -> ToolResult:
        lines = [f"Chemin : {' → '.join(path) or '(aucun agent lancé)'} ; {end}."]
        lines += [f"\n## {role}\n{content}" for role, content in steps]
        return ToolResult(ok=ok, content="\n".join(lines))
