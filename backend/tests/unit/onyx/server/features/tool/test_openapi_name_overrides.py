"""An OpenAPI tool's name and description come from its schema.

The stored `Tool.name` and `Tool.description` are only overrides: empty ones
fall back to the schema's `info`, and the raw values are returned as
`name_override` and `description_override`.
"""

from typing import Any

from onyx.db.models import Tool
from onyx.server.features.tool.models import ToolSnapshot

_SCHEMA: dict[str, Any] = {
    "openapi": "3.0.0",
    "info": {
        "title": "Tasks API",
        "version": "1.0.0",
        "description": "Create and list tasks.",
    },
    "paths": {},
}


def _tool(
    *,
    name: str = "",
    description: str | None = None,
    openapi_schema: dict[str, Any] | None = _SCHEMA,
    mcp_server_id: int | None = None,
) -> Tool:
    # Column defaults apply on insert, so a transient row sets them itself.
    return Tool(
        id=1,
        name=name,
        description=description,
        openapi_schema=openapi_schema,
        mcp_server_id=mcp_server_id,
        in_code_tool_id=None,
        passthrough_auth=False,
        enabled=True,
    )


def test_empty_overrides_fall_back_to_the_schema() -> None:
    snapshot = ToolSnapshot.from_model(_tool())

    assert snapshot.name == "Tasks API"
    assert snapshot.display_name == "Tasks API"
    assert snapshot.description == "Create and list tasks."
    assert snapshot.name_override is None
    assert snapshot.description_override is None


def test_set_overrides_win_over_the_schema() -> None:
    snapshot = ToolSnapshot.from_model(
        _tool(name="My Tasks", description="Team task tracker.")
    )

    assert snapshot.name == "My Tasks"
    assert snapshot.description == "Team task tracker."
    assert snapshot.name_override == "My Tasks"
    assert snapshot.description_override == "Team task tracker."


def test_an_override_equal_to_the_schema_is_still_an_override() -> None:
    snapshot = ToolSnapshot.from_model(_tool(name="Tasks API"))

    assert snapshot.name == "Tasks API"
    assert snapshot.name_override == "Tasks API"


def test_a_schema_without_info_leaves_the_stored_values() -> None:
    snapshot = ToolSnapshot.from_model(
        _tool(openapi_schema={"openapi": "3.0.0", "paths": {}})
    )

    assert snapshot.name == ""
    assert snapshot.description == ""


def test_mcp_tools_do_not_fall_back_to_a_schema() -> None:
    snapshot = ToolSnapshot.from_model(_tool(mcp_server_id=7))

    assert snapshot.name == ""
    assert snapshot.description == ""
