"""Classify an MCP streamable-HTTP request into a gate verdict input.

Every tool invocation is a JSON-RPC ``tools/call`` carrying the exact tool
name, so the gate parses the body (precedent:
``external_apps/matching/graphql_parsing.py``) rather than guessing from the
URL. Protocol plumbing passes ungated; anything else on a matched MCP host is
UNCLASSIFIABLE and fails closed — credential injection covers the whole host,
so an unrecognized request must never forward with credentials.
"""

from __future__ import annotations

import json
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict

_TOOL_CALL_METHOD = "tools/call"

# Non-invocation JSON-RPC methods that operate the MCP session. Kept as an
# explicit allowlist (plus the notifications/* prefix) so an unknown method
# fails closed rather than riding through with injected credentials.
_PLUMBING_METHODS = frozenset(
    {
        "initialize",
        "ping",
        "tools/list",
        "resources/list",
        "resources/read",
        "resources/templates/list",
        "resources/subscribe",
        "resources/unsubscribe",
        "prompts/list",
        "prompts/get",
        "completion/complete",
        "logging/setLevel",
    }
)
_NOTIFICATION_PREFIX = "notifications/"


class McpRpcKind(str, Enum):
    PLUMBING = "PLUMBING"  # forward ungated (creds injected)
    TOOL_CALL = "TOOL_CALL"  # gate per tool name
    UNCLASSIFIABLE = "UNCLASSIFIABLE"  # fail closed — deny


class McpRpcClassification(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: McpRpcKind
    # Tool names of every `tools/call` in the (possibly batched) body, in order.
    tool_names: tuple[str, ...] = ()


_PLUMBING = McpRpcClassification(kind=McpRpcKind.PLUMBING)
_UNCLASSIFIABLE = McpRpcClassification(kind=McpRpcKind.UNCLASSIFIABLE)


def classify_mcp_request(http_method: str, body: bytes | None) -> McpRpcClassification:
    """Classify one intercepted request to a matched craft MCP host.

    Bodyless ``GET`` (SSE stream) and ``DELETE`` (session termination) are the
    only non-POST plumbing; any other verb, or a body on those, is
    ``UNCLASSIFIABLE``. A POST body is parsed as a single JSON-RPC message or a
    batched array:

    * every message a recognized plumbing method → ``PLUMBING``;
    * any message a well-formed ``tools/call`` (string ``params.name``) →
      ``TOOL_CALL`` over all such names;
    * anything else (unknown method, malformed body, a ``tools/call`` missing its
      name) → ``UNCLASSIFIABLE``.
    """
    method = (http_method or "").upper()
    if method in ("GET", "DELETE"):
        return _PLUMBING if not body else _UNCLASSIFIABLE
    if method != "POST":
        return _UNCLASSIFIABLE

    messages = _parse_messages(body)
    if messages is None:
        return _UNCLASSIFIABLE

    tool_names: list[str] = []
    for message in messages:
        method = message.get("method")
        if not isinstance(method, str):
            return _UNCLASSIFIABLE
        if method == _TOOL_CALL_METHOD:
            name = _tool_name(message)
            if name is None:
                return _UNCLASSIFIABLE
            tool_names.append(name)
        elif not _is_plumbing(method):
            return _UNCLASSIFIABLE

    if tool_names:
        return McpRpcClassification(
            kind=McpRpcKind.TOOL_CALL, tool_names=tuple(tool_names)
        )
    return _PLUMBING


def _parse_messages(body: bytes | None) -> list[dict[str, Any]] | None:
    """The JSON-RPC message dicts in ``body``, or ``None`` if it isn't a
    JSON object / array of objects. An empty batch is ``None`` (nothing to
    classify → fail closed)."""
    if not body:
        return None
    try:
        payload = json.loads(body)
    except (ValueError, TypeError, RecursionError):
        # RecursionError: a deeply-nested body must fail closed, not crash the
        # evaluator into the gate's fail-open path.
        return None
    if isinstance(payload, dict):
        return [payload]
    if isinstance(payload, list):
        if not payload or not all(isinstance(item, dict) for item in payload):
            return None
        return payload
    return None


def _is_plumbing(method: str) -> bool:
    return method in _PLUMBING_METHODS or method.startswith(_NOTIFICATION_PREFIX)


def _tool_name(message: dict[str, Any]) -> str | None:
    params = message.get("params")
    if not isinstance(params, dict):
        return None
    name = params.get("name")
    return name if isinstance(name, str) and name else None
