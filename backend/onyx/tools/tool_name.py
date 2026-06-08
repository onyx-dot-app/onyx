from __future__ import annotations

import re
from collections import defaultdict
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from onyx.tools.interface import Tool

# Bedrock rejects toolUse.name values that don't match [a-zA-Z0-9_-]+, and
# OpenAI imposes the same constraint on function names. User-supplied Tool.name
# and OpenAPI operationId can contain spaces, dots, etc.
_INVALID_TOOL_NAME_CHARS = re.compile(r"[^a-zA-Z0-9_-]")

# OpenAI caps function names at 64 characters; keep generated names within that.
_MAX_TOOL_NAME_LEN = 64


def sanitize_tool_name(name: str) -> str:
    return _INVALID_TOOL_NAME_CHARS.sub("_", name)


def _truncate_tool_name(name: str, reserve: int = 0) -> str:
    limit = _MAX_TOOL_NAME_LEN - reserve
    if limit <= 0:
        return name[:_MAX_TOOL_NAME_LEN]
    return name if len(name) <= limit else name[:limit]


def disambiguate_tool_names(tools: list["Tool"]) -> None:
    """Ensure the names presented to the LLM are unique across ``tools``.

    Several MCP servers expose tools with the same generic name (e.g. ``search``).
    When two such tools are attached to one assistant, the LLM receives duplicate
    function declarations; some providers (notably Gemini) reject the request with
    a ``Duplicate function declaration`` error, and even tolerant providers cannot
    reliably tell the tools apart.

    To fix this without churning every tool name, we rename only on collision and
    only rename MCP tools (built-in tools keep their stable, well-known names). A
    colliding MCP tool is renamed to ``<server>_<tool>`` (sanitized, truncated and
    de-duplicated). The override is applied to the tool object, so it flows through
    both the tool definition sent to the LLM and the name used to dispatch the
    resulting tool call, keeping the two in sync. The user-facing ``display_name``
    is left unchanged.
    """
    # Imported lazily to avoid a circular import at module load time.
    from onyx.tools.tool_implementations.mcp.mcp_tool import MCPTool

    name_counts: dict[str, int] = defaultdict(int)
    for tool in tools:
        name_counts[tool.name] += 1

    colliding_names = {name for name, count in name_counts.items() if count > 1}
    if not colliding_names:
        return

    used_names = {tool.name for tool in tools}
    for tool in tools:
        if tool.name not in colliding_names:
            continue
        # Keep non-MCP (built-in) tool names stable; rename MCP tools around them.
        if not isinstance(tool, MCPTool):
            continue

        prefixed = sanitize_tool_name(f"{tool.mcp_server.name}_{tool.name}")
        candidate = _truncate_tool_name(prefixed)
        suffix_num = 2
        while candidate in used_names:
            suffix = f"_{suffix_num}"
            candidate = _truncate_tool_name(prefixed, reserve=len(suffix)) + suffix
            suffix_num += 1

        tool.set_llm_name_override(candidate)
        used_names.add(candidate)
