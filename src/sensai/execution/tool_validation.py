"""
Validation of a tool call's arguments and of the result returned to the model.

Part of the tool gateway contract (docs/architecture/tool-contract.md).
Deliberately dependency-free: only the JSON Schema subset used by
`Tool.parameters` is supported (type, required, enum, properties,
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
    # bool is a subclass of int in Python: without this guard, `True` would
    # pass as a valid integer.
    if json_type in ("integer", "number") and isinstance(value, bool):
        return False
    expected = _TYPES.get(json_type)
    return True if expected is None else isinstance(value, expected)


def check_object(schema: dict[str, Any], value: Any, label: str = "arguments") -> str | None:
    """Check `value` against `schema`. Return the first problem, or None."""
    if not isinstance(value, dict):
        return f"{label} must be an object"

    for key in schema.get("required", []):
        if key not in value:
            return f"{label}: missing required field '{key}'"

    properties = schema.get("properties", {})
    if schema.get("additionalProperties") is False:
        extra = sorted(set(value) - set(properties))
        if extra:
            return f"{label}: unknown fields {extra}"

    for key, spec in properties.items():
        if key not in value:
            continue
        json_type = spec.get("type")
        types = [json_type] if isinstance(json_type, str) else (json_type or [])
        if types and not any(_is_type(value[key], t) for t in types):
            return f"{label}: '{key}' must be of type {'/'.join(types)}"
        if "enum" in spec and value[key] not in spec["enum"]:
            return f"{label}: '{key}' must be one of {spec['enum']}"
    return None


def check_arguments(schema: dict[str, Any], arguments: Any) -> str | None:
    """Arguments proposed by the model, against `Tool.parameters`."""
    return check_object(schema, arguments, "arguments")


def check_result(result: Any, output_schema: dict[str, Any] | None = None) -> str | None:
    """A tool's result, before it reaches the filters and then the model.

    What a tool returns is never trusted: a buggy tool or an external MCP
    server can return anything, and the model would read that output as a
    reliable observation.
    """
    if not isinstance(result, ToolResult):
        return f"the result is not a ToolResult ({type(result).__name__})"
    if not isinstance(result.ok, bool):
        return "ToolResult.ok must be a boolean"
    if not isinstance(result.content, str):
        return "ToolResult.content must be a string"
    if not isinstance(result.data, dict):
        return "ToolResult.data must be a dict"
    try:
        json.dumps(result.data)
    except (TypeError, ValueError):
        return "ToolResult.data is not JSON-serializable"
    if output_schema is not None and result.ok:
        return check_object(output_schema, result.data, "data")
    return None
