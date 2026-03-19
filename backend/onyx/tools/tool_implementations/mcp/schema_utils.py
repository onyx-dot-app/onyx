from __future__ import annotations

from copy import deepcopy
from typing import Any

from onyx.utils.logger import setup_logger

logger = setup_logger()


def normalize_mcp_input_schema(
    schema: dict[str, Any] | None,
    *,
    tool_name: str | None = None,
) -> dict[str, Any]:
    """Normalize MCP tool schemas for providers that require object parameters."""
    if not schema:
        return {"type": "object", "properties": {}}

    normalized = deepcopy(schema)
    schema_type = normalized.get("type")
    looks_like_object = any(
        key in normalized for key in ("properties", "required", "additionalProperties")
    )

    if looks_like_object:
        if schema_type != "object":
            logger.warning(
                "MCP tool schema for %s had root type %r but object-like fields; normalizing to object schema",
                tool_name or "<unknown>",
                schema_type,
            )
            normalized["type"] = "object"
        else:
            normalized.setdefault("type", "object")
        normalized.setdefault("properties", {})
        return normalized

    # MCP tool arguments are sent as a JSON object on the wire. If an upstream
    # server publishes a non-object root schema, fall back to an empty object so
    # strict providers like Vertex/Gemini don't reject the entire toolset.
    logger.warning(
        "MCP tool schema for %s had non-object root type %r; falling back to empty object schema",
        tool_name or "<unknown>",
        schema_type,
    )
    return {"type": "object", "properties": {}}
