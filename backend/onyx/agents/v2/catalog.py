from __future__ import annotations

import json
import re
from collections import OrderedDict
from typing import Any

from jsonschema import Draft202012Validator, SchemaError

from onyx.agents.v2.models import RegisteredTool

CONTROL_TOOL_NAMES = frozenset({"discover_tools", "read_result", "finish_task"})
MAX_SCHEMA_CHARS = 8000
MAX_QUERY_CHARS = 512
BLOCKED_SCHEMA_BUDGET = "schema_exceeds_catalog_budget"
BLOCKED_INVALID_SCHEMA = "invalid_json_schema"
BLOCKED_EXTERNAL_REF = "schema_has_external_ref"
BLOCKED_DYNAMIC_REF = "schema_has_dynamic_ref"
BLOCKED_RECURSIVE_REF = "schema_has_recursive_ref"


class ToolCatalog:
    def __init__(
        self,
        tools: list[RegisteredTool],
        max_exposed_tools: int,
    ) -> None:
        if max_exposed_tools < 1:
            raise ValueError("max_exposed_tools must be at least 1")

        self._tools: OrderedDict[str, RegisteredTool] = OrderedDict()
        self._exposed: OrderedDict[str, RegisteredTool] = OrderedDict()
        self._blocked_schema_tools: dict[str, str] = {}
        self._max_exposed_tools = max_exposed_tools

        for tool in tools:
            self._add_tool(tool)

        pinned_tools = [
            tool
            for tool in self._tools.values()
            if tool.pinned and tool.name not in self._blocked_schema_tools
        ]
        if len(pinned_tools) > self._max_exposed_tools:
            raise ValueError("Pinned tools exceed max_exposed_tools")

        for tool in pinned_tools:
            self._exposed[tool.name] = tool

    def discover(self, query: str, limit: int = 3) -> list[dict[str, Any]]:
        if limit < 1:
            return []

        terms = _tokenize(query[:MAX_QUERY_CHARS])
        if not terms:
            return []

        ranked = sorted(
            (
                (self._score_tool(tool, terms), index, tool)
                for index, tool in enumerate(self._tools.values())
                if tool.name not in self._exposed
            ),
            key=lambda item: (-item[0], item[1], item[2].name),
        )

        selected = []
        for score, _, tool in ranked:
            if score <= 0 or len(selected) >= limit:
                break
            selected.append(tool)
            if tool.name not in self._blocked_schema_tools:
                self._expose(tool)

        return [
            {
                "name": tool.name,
                "description": tool.description,
                "exposed": tool.name in self._exposed,
                "blocked": tool.name in self._blocked_schema_tools,
                "blocked_reason": self._blocked_schema_tools.get(tool.name),
            }
            for tool in selected
        ]

    def definitions(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters,
                },
            }
            for tool in self._exposed.values()
        ]

    def get_exposed(self, name: str) -> RegisteredTool | None:
        return self._exposed.get(name)

    def summary(self) -> dict[str, Any]:
        pinned = [tool.name for tool in self._exposed.values() if tool.pinned]
        loaded = [tool.name for tool in self._exposed.values() if not tool.pinned]
        return {
            "total_tools": len(self._tools),
            "exposed_tools": len(self._exposed),
            "hidden_tools": len(self._tools) - len(self._exposed),
            "blocked_tools": len(self._blocked_schema_tools),
            "max_exposed_tools": self._max_exposed_tools,
            "pinned_tools": pinned,
            "loaded_tools": loaded,
            "control_tools": sorted(CONTROL_TOOL_NAMES),
        }

    def _add_tool(self, tool: RegisteredTool) -> None:
        if tool.name in CONTROL_TOOL_NAMES:
            raise ValueError(f"Tool name is reserved: {tool.name}")
        if tool.name in self._tools:
            raise ValueError(f"Duplicate tool name: {tool.name}")

        self._tools[tool.name] = tool
        blocked_reason = _blocked_schema_reason(tool.parameters)
        if blocked_reason is not None:
            self._blocked_schema_tools[tool.name] = blocked_reason

    def _expose(self, tool: RegisteredTool) -> None:
        if tool.name in self._exposed:
            return
        if tool.name in self._blocked_schema_tools:
            return

        while len(self._exposed) >= self._max_exposed_tools:
            evicted = self._evict_nonpinned()
            if evicted:
                continue
            raise ValueError("No non-pinned exposed tools can be evicted")

        self._exposed[tool.name] = tool

    def _evict_nonpinned(self) -> bool:
        for name, tool in list(self._exposed.items()):
            if not tool.pinned:
                del self._exposed[name]
                return True
        return False

    @staticmethod
    def _score_tool(tool: RegisteredTool, terms: set[str]) -> int:
        name_terms = _tokenize(tool.name)
        description_terms = _tokenize(tool.description)
        return (
            6 * len(terms & name_terms)
            + 2 * len(terms & description_terms)
            + sum(1 for term in terms if len(term) >= 3 and term in tool.name.lower())
        )


def _tokenize(text: str) -> set[str]:
    tokens: set[str] = set()
    for token in re.findall(r"[a-z0-9_]+", text.lower()):
        if not token:
            continue
        tokens.add(token)
        if len(token) > 3 and token.endswith("s"):
            tokens.add(token[:-1])
    return tokens


def _blocked_schema_reason(parameters: dict[str, Any]) -> str | None:
    try:
        Draft202012Validator.check_schema(parameters)
    except SchemaError:
        return BLOCKED_INVALID_SCHEMA

    ref_reason = _blocked_ref_reason(parameters)
    if ref_reason is not None:
        return ref_reason

    if _json_len(parameters) > MAX_SCHEMA_CHARS:
        return BLOCKED_SCHEMA_BUDGET

    return None


def _blocked_ref_reason(value: Any) -> str | None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "$ref" and isinstance(item, str) and not item.startswith("#"):
                return BLOCKED_EXTERNAL_REF
            if key == "$dynamicRef":
                return BLOCKED_DYNAMIC_REF
            if key == "$recursiveRef":
                return BLOCKED_RECURSIVE_REF

            reason = _blocked_ref_reason(item)
            if reason is not None:
                return reason

    if isinstance(value, list):
        for item in value:
            reason = _blocked_ref_reason(item)
            if reason is not None:
                return reason

    return None


def _json_len(value: Any) -> int:
    return len(json.dumps(value, sort_keys=True, default=str))
