from __future__ import annotations

from copy import deepcopy
from typing import Any


def normalize_mcp_input_schema(
    schema: dict[str, Any] | None,
) -> dict[str, Any]:
    """Normalize MCP tool schemas for providers that require object parameters."""
    if not schema:
        return {"type": "object", "properties": {}}

    normalized = deepcopy(schema)
    schema_type = normalized.get("type")
    looks_like_object = schema_type == "object" or any(
        key in normalized for key in ("properties", "required", "additionalProperties")
    )

    if looks_like_object:
        normalized.setdefault("type", "object")
        normalized.setdefault("properties", {})
        return normalized

    # MCP tool arguments are sent as a JSON object on the wire. If an upstream
    # server publishes a non-object root schema, fall back to an empty object so
    # strict providers like Vertex/Gemini don't reject the entire toolset.
    return {"type": "object", "properties": {}}
