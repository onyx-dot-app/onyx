from __future__ import annotations

import pytest

from onyx.agents.v2.catalog import ToolCatalog
from onyx.agents.v2.models import ExecutionContext, RegisteredTool, ToolOutput


def _execute(_: dict, __: ExecutionContext) -> ToolOutput:
    return ToolOutput(content="ok")


def _tool(
    name: str,
    description: str = "search company documents",
    *,
    pinned: bool = False,
    parameters: dict | None = None,
) -> RegisteredTool:
    return RegisteredTool(
        name=name,
        description=description,
        parameters=parameters or {"type": "object", "properties": {}},
        execute=_execute,
        pinned=pinned,
    )


def test_pinned_tools_are_initially_exposed() -> None:
    catalog = ToolCatalog(
        tools=[
            _tool("internal_search", pinned=True),
            _tool("send_email", "send an email message"),
        ],
        max_exposed_tools=2,
    )

    assert catalog.get_exposed("internal_search") is not None
    assert catalog.get_exposed("send_email") is None
    assert [definition["function"]["name"] for definition in catalog.definitions()] == [
        "internal_search"
    ]


def test_discover_exposes_only_lexical_matches_without_llm() -> None:
    catalog = ToolCatalog(
        tools=[
            _tool("internal_search", pinned=True),
            _tool("calendar_lookup", "find calendar events"),
            _tool("jira_search", "search tickets and issues"),
        ],
        max_exposed_tools=3,
    )

    matches = catalog.discover("ticket issue follow up", limit=2)

    assert [match["name"] for match in matches] == ["jira_search"]
    assert catalog.get_exposed("jira_search") is not None
    assert catalog.get_exposed("calendar_lookup") is None


def test_nonpinned_exposure_is_evicted_before_pinned_tools() -> None:
    catalog = ToolCatalog(
        tools=[
            _tool("internal_search", pinned=True),
            _tool("calendar_lookup", "find calendar events"),
            _tool("jira_search", "search tickets and issues"),
        ],
        max_exposed_tools=2,
    )

    catalog.discover("calendar events", limit=1)
    catalog.discover("tickets issues", limit=1)

    assert catalog.get_exposed("internal_search") is not None
    assert catalog.get_exposed("calendar_lookup") is None
    assert catalog.get_exposed("jira_search") is not None


def test_rejects_reserved_and_duplicate_names() -> None:
    with pytest.raises(ValueError, match="reserved"):
        ToolCatalog([_tool("finish_task")], max_exposed_tools=1)

    with pytest.raises(ValueError, match="Duplicate"):
        ToolCatalog([_tool("internal_search"), _tool("internal_search")], 2)


def test_get_exposed_rejects_unloaded_tools_even_when_registered() -> None:
    catalog = ToolCatalog(
        [_tool("internal_search", pinned=True), _tool("open_url")],
        max_exposed_tools=2,
    )

    assert catalog.get_exposed("open_url") is None


def test_oversized_schemas_are_blocked_not_truncated() -> None:
    huge_schema = {
        "type": "object",
        "properties": {
            f"field_{index}": {"type": "string", "description": "x" * 1000}
            for index in range(30)
        },
    }
    catalog = ToolCatalog(
        [_tool("large_tool", "large tool", pinned=True, parameters=huge_schema)],
        max_exposed_tools=1,
    )

    matches = catalog.discover("large", limit=1)

    assert catalog.definitions() == []
    assert catalog.get_exposed("large_tool") is None
    assert matches == [
        {
            "name": "large_tool",
            "description": "large tool",
            "exposed": False,
            "blocked": True,
            "blocked_reason": "schema_exceeds_catalog_budget",
        }
    ]


def test_pinned_remote_ref_schema_is_not_exposed() -> None:
    catalog = ToolCatalog(
        [
            _tool(
                "remote_tool",
                "remote ref tool",
                pinned=True,
                parameters={"$ref": "https://example.com/schema.json"},
            )
        ],
        max_exposed_tools=1,
    )

    assert catalog.definitions() == []
    assert catalog.get_exposed("remote_tool") is None
    assert catalog.summary()["blocked_tools"] == 1


def test_discovered_remote_ref_schema_is_reported_but_not_exposed() -> None:
    catalog = ToolCatalog(
        [
            _tool(
                "remote_search",
                "search remote system",
                parameters={
                    "type": "object",
                    "properties": {
                        "payload": {"$ref": "file:///tmp/schema.json"},
                    },
                },
            )
        ],
        max_exposed_tools=1,
    )

    matches = catalog.discover("remote search", limit=1)

    assert matches == [
        {
            "name": "remote_search",
            "description": "search remote system",
            "exposed": False,
            "blocked": True,
            "blocked_reason": "schema_has_external_ref",
        }
    ]
    assert catalog.definitions() == []
    assert catalog.get_exposed("remote_search") is None


def test_dynamic_and_recursive_refs_are_blocked() -> None:
    dynamic_catalog = ToolCatalog(
        [
            _tool(
                "dynamic_search",
                "dynamic search",
                parameters={"type": "object", "$dynamicRef": "#/$defs/item"},
            )
        ],
        max_exposed_tools=1,
    )
    recursive_catalog = ToolCatalog(
        [
            _tool(
                "recursive_search",
                "recursive search",
                parameters={"type": "object", "$recursiveRef": "#"},
            )
        ],
        max_exposed_tools=1,
    )

    assert dynamic_catalog.discover("dynamic", limit=1)[0]["blocked_reason"] == (
        "schema_has_dynamic_ref"
    )
    assert dynamic_catalog.get_exposed("dynamic_search") is None
    assert recursive_catalog.discover("recursive", limit=1)[0]["blocked_reason"] == (
        "schema_has_recursive_ref"
    )
    assert recursive_catalog.get_exposed("recursive_search") is None


def test_local_refs_are_valid_and_exposed_without_schema_changes() -> None:
    schema = {
        "type": "object",
        "properties": {"query": {"$ref": "#/$defs/query"}},
        "$defs": {"query": {"type": "string"}},
    }
    catalog = ToolCatalog(
        [
            _tool(
                "local_search", "search with local ref", pinned=True, parameters=schema
            )
        ],
        max_exposed_tools=1,
    )

    definition = catalog.definitions()[0]

    assert catalog.get_exposed("local_search") is not None
    assert definition["function"]["parameters"] == schema


def test_summary_does_not_dump_hidden_schemas() -> None:
    catalog = ToolCatalog(
        [_tool("internal_search", pinned=True), _tool("open_url")],
        max_exposed_tools=1,
    )

    assert catalog.summary() == {
        "total_tools": 2,
        "exposed_tools": 1,
        "hidden_tools": 1,
        "blocked_tools": 0,
        "max_exposed_tools": 1,
        "pinned_tools": ["internal_search"],
        "loaded_tools": [],
        "control_tools": ["discover_tools", "finish_task", "read_result"],
    }
