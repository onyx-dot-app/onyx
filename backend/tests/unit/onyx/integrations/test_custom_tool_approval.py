from typing import Any
from unittest.mock import MagicMock

from onyx.db.enums import GatedAppKind
from onyx.tools.models import DynamicSchemaInfo, ToolApprovalScope
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


def test_builder_keeps_the_action_key_of_the_operation_that_a_rendered_path_keeps() -> (
    None
):
    spec: dict[str, Any] = {
        **SPEC,
        "paths": {
            "/messages/MESSAGE_ID": {
                "get": {"operationId": "readCurrent", "summary": "Current"}
            },
            "/messages/1": {"get": {"operationId": "readFirst", "summary": "First"}},
        },
    }

    tools = build_custom_tools_from_openapi_schema_and_headers(
        tool_id=4,
        openapi_schema=spec,
        dynamic_schema_info=DynamicSchemaInfo(chat_session_id=None, message_id=1),
        approval_for=lambda key: SCOPE.model_copy(update={"action_id": key}),
    )

    assert [(t.display_name, t.action_key) for t in tools] == [
        ("readFirst", "readFirst")
    ]
    assert tools[0].approval is not None
    assert tools[0].approval.action_id == "readFirst"
