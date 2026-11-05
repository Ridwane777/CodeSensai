"""
Validation des arguments d'un appel d'outil et du résultat renvoyé au modèle.

Fait partie du contrat de la passerelle d'outils (docs/architecture/tool-contract.md).
Volontairement sans dépendance : on ne gère que le sous-ensemble de JSON
Schema utilisé par `Tool.parameters` (type, required, enum, properties,
additionalProperties).
"""
from __future__ import annotations

import json
from typing import Any

from sensai.core.tools import ToolResult

_TYPES: dict[str, type | tuple[type, ...]] = {
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
    "array": list,
    "object": dict,
}


def _is_type(value: Any, json_type: str) -> bool:
    # bool est une sous-classe de int en Python : sans ce garde-fou, `True`
    # passerait pour un entier valide.
    if json_type in ("integer", "number") and isinstance(value, bool):
        return False
    expected = _TYPES.get(json_type)
    return True if expected is None else isinstance(value, expected)


def check_object(schema: dict[str, Any], value: Any, label: str = "arguments") -> str | None:
    """Vérifie `value` contre `schema`. Retourne le premier problème, ou None."""
    if not isinstance(value, dict):
        return f"{label} doit être un objet"

    for key in schema.get("required", []):
        if key not in value:
            return f"{label} : champ obligatoire manquant « {key} »"

    properties = schema.get("properties", {})
    if schema.get("additionalProperties") is False:
        extra = sorted(set(value) - set(properties))
        if extra:
            return f"{label} : champs inconnus {extra}"

    for key, spec in properties.items():
        if key not in value:
            continue
        json_type = spec.get("type")
        types = [json_type] if isinstance(json_type, str) else (json_type or [])
        if types and not any(_is_type(value[key], t) for t in types):
            return f"{label} : « {key} » doit être de type {'/'.join(types)}"
        if "enum" in spec and value[key] not in spec["enum"]:
            return f"{label} : « {key} » doit valoir l'une de {spec['enum']}"
    return None


def check_arguments(schema: dict[str, Any], arguments: Any) -> str | None:
    """Arguments proposés par le modèle, contre `Tool.parameters`."""
    return check_object(schema, arguments, "arguments")


def check_result(result: Any, output_schema: dict[str, Any] | None = None) -> str | None:
    """Résultat d'un outil, avant qu'il n'atteigne les filtres puis le modèle.

    On ne fait jamais confiance à ce qu'un outil renvoie : un outil buggé ou
    un serveur MCP externe peut renvoyer n'importe quoi, et le modèle lirait
    cette sortie comme une observation fiable.
    """
    if not isinstance(result, ToolResult):
        return f"le résultat n'est pas un ToolResult ({type(result).__name__})"
    if not isinstance(result.ok, bool):
        return "ToolResult.ok doit être un booléen"
    if not isinstance(result.content, str):
        return "ToolResult.content doit être une chaîne"
    if not isinstance(result.data, dict):
        return "ToolResult.data doit être un dict"
    try:
        json.dumps(result.data)
    except (TypeError, ValueError):
        return "ToolResult.data n'est pas sérialisable en JSON"
    if output_schema is not None and result.ok:
        return check_object(output_schema, result.data, "data")
    return None
