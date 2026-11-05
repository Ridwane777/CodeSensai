"""
[Lot C — Ridwane] Outils de la mémoire structurée — feature [M3], ADR-0030.

`save_fact` (risque `write`) : retenir un fait, après confirmation.
`recall_facts` (risque `read`) : retrouver des faits, sans confirmation.
L'agent n'a aucun outil pour effacer : c'est réservé à la commande `/facts`.
"""
from __future__ import annotations

import sqlite3
from typing import Any, ClassVar

from sensai.core.tools import ToolResult
from sensai.knowledge.facts import MODES, FactError, FactStore


def _fail(message: str) -> ToolResult:
    # Contrat Tool : jamais d'exception, l'agent doit pouvoir corriger son appel.
    return ToolResult(ok=False, content=message, data={"error": "invalid_fact"})


class RememberFactTool:
    name = "save_fact"
    risk = "write"
    # Une phrase courte et le nom save_fact : avec une description longue ou le
    # nom remember_fact, qwen3-coder écrivait l'appel en texte au lieu de
    # l'appeler (4/12 contre 8/12 appels structurés, mesuré le 2026-10-17).
    # La façon de s'en servir est dans le prompt système (facts.py).
    description = "Enregistre un fait durable sur le projet : entité, attribut, valeur."
    parameters: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "entity": {"type": "string"},
            "attribute": {"type": "string"},
            "value": {"type": "string"},
            "mode": {"type": "string", "enum": list(MODES)},
        },
        "required": ["entity", "attribute", "value"],
    }

    def __init__(self, store: FactStore) -> None:
        self.store = store

    def describe_call(self, **args: Any) -> str:
        try:
            return self.store.preview(args.get("entity"), args.get("attribute"),
                                      args.get("value"), args.get("mode", "replace"))
        except FactError as e:
            return f"Retenir un fait — sera refusé : {e}"

    def run(self, **kwargs: Any) -> ToolResult:
        try:
            result = self.store.remember(kwargs.get("entity"), kwargs.get("attribute"),
                                         kwargs.get("value"), kwargs.get("mode", "replace"))
        except FactError as e:
            return _fail(str(e))
        except (sqlite3.Error, OSError) as e:
            return ToolResult(ok=False, content=f"Mémoire indisponible : {e}",
                              data={"error": "storage"})
        messages = {
            "created": "Fait retenu.",
            "added": "Valeur ajoutée.",
            "updated": f"Fait mis à jour (ancienne valeur : {', '.join(result['old_values'])}).",
            "unchanged": "Ce fait était déjà connu : rien n'a changé.",
        }
        content = messages[result["change"]]
        if result["others"]:
            # Pour que le modèle repère un doublon (« version redis » à côté de
            # « utilise_redis ») et reprenne le bon nom la fois suivante.
            content += (
                f" Autres attributs connus de {kwargs.get('entity')} : "
                + ", ".join(f"{n} ({', '.join(v)})" for n, v in result["others"])
                + ". Si l'un désigne la même chose, utilise son nom avec mode replace."
            )
        return ToolResult(ok=True, content=content, data=result)


class RecallFactsTool:
    name = "recall_facts"
    risk = "read"
    description = "Cherche des faits enregistrés sur le projet, par entité, attribut ou valeur."
    parameters: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "entity": {"type": "string"},
            "attribute": {"type": "string"},
            "value": {"type": "string"},
        },
        "required": [],
    }

    def __init__(self, store: FactStore) -> None:
        self.store = store

    def run(self, **kwargs: Any) -> ToolResult:
        try:
            facts = self.store.recall(kwargs.get("entity"), kwargs.get("attribute"),
                                      kwargs.get("value"))
        except FactError as e:
            return _fail(str(e))
        except (sqlite3.Error, OSError) as e:
            return ToolResult(ok=False, content=f"Mémoire indisponible : {e}",
                              data={"error": "storage"})
        note = ""
        if not facts and kwargs.get("entity") and (kwargs.get("attribute") or kwargs.get("value")):
            # Le modèle devine souvent un autre nom d'attribut que celui enregistré
            # (essai réel du 2026-10-17) : on lui montre tout ce qu'on sait de l'entité.
            try:
                facts = self.store.recall(kwargs.get("entity"))
            except (FactError, sqlite3.Error, OSError):
                facts = []
            if facts:
                wanted = kwargs.get("attribute") or kwargs.get("value")
                note = (f"Rien d'enregistré exactement pour « {wanted} » ; "
                        "voici tout ce qui est connu. ")
        if not facts:
            return ToolResult(ok=True, content="Aucun fait enregistré pour cette recherche.",
                              data={"facts": []})
        lines = [f"- {f['entity']} — {f['attribute']} : {f['value']} (au {f['updated_at'][:10]})"
                 for f in facts]
        return ToolResult(ok=True, content=note + "Faits trouvés :\n" + "\n".join(lines),
                          data={"facts": facts})
