import json
from typing import Any

from fastmcp.tools import ToolResult
from mcp.types import TextContent


def tool_payload(result: ToolResult) -> dict[str, Any]:
    """Parse the single JSON text block a search tool returns."""
    assert result.structured_content is None
    (block,) = result.content
    assert isinstance(block, TextContent)
    payload = json.loads(block.text)
    assert isinstance(payload, dict)
    return payload
