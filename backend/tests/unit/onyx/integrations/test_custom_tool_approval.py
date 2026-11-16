from typing import Any
from unittest.mock import MagicMock

from onyx.db.enums import GatedAppKind
from onyx.tools.models import ToolApprovalScope
from onyx.tools.tool_implementations.custom.custom_tool import (
    CustomTool,
    build_custom_tools_from_openapi_schema_and_headers,
)
from onyx.tools.tool_implementations.custom.openapi_parsing import MethodSpec

SCOPE = ToolApprovalScope(
    app_kind=GatedAppKind.MCP_SERVER, target_id=1, action_id="createThing"
)

SPEC: dict[str, Any] = {
    "openapi": "3.0.0",
    "info": {"title": "T", "description": "T", "version": "1"},
    "servers": [{"url": "https://things.example.com"}],
    "paths": {
        "/things": {
            "get": {"operationId": "listThings", "summary": "List"},
            "post": {"operationId": "createThing", "summary": "Create"},
        }
    },
}


def _method_spec() -> MethodSpec:
    return MethodSpec(
        name="createThing",
        raw_name="createThing",
        summary="Create",
        path="/things",
        method="post",
        spec={},
    )


def test_custom_tool_approval_is_in_approval_required() -> None:
    tool = CustomTool(
        id=1,
        method_spec=_method_spec(),
        base_url="https://things.example.com",
        approval=SCOPE,
    )
    assert tool.approval == SCOPE
    assert tool.bind(MagicMock()).approval_required == frozenset({tool.name})


def test_custom_tool_without_approval_runs_without_a_question() -> None:
    tool = CustomTool(
        id=1, method_spec=_method_spec(), base_url="https://things.example.com"
    )
    assert tool.approval is None
    assert tool.bind(MagicMock()).approval_required == frozenset()


def test_builder_gives_each_operation_its_approval() -> None:
    tools = build_custom_tools_from_openapi_schema_and_headers(
        tool_id=4,
        openapi_schema=SPEC,
        approval_for=lambda key: SCOPE if key == "createThing" else None,
    )
    approvals = {tool.display_name: tool.approval for tool in tools}
    assert approvals == {"listThings": None, "createThing": SCOPE}


def test_builder_without_approval_for_sets_none() -> None:
    tools = build_custom_tools_from_openapi_schema_and_headers(
        tool_id=4, openapi_schema=SPEC
    )
    assert all(tool.approval is None for tool in tools)
