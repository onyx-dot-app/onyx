import base64
import json
import re
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import pytest
from pydantic import BaseModel, JsonValue

from onyx.agents.tools import ToolInvocation
from onyx.chat.prompt_utils import build_system_prompt
from onyx.llm.cancellation import CancellationSignal
from onyx.llm.models import ToolResult
from onyx.tools.interface import Tool, parse_tool_arguments
from onyx.tools.models import CodeModeExposure, ToolCallException, ToolContext
from onyx.tools.tool_implementations.code_mode.code_mode_tool import with_code_mode
from onyx.tools.tool_implementations.code_mode.stubs import build_tool_stubs
from onyx.tools.tool_implementations.sandbox import artifact_operations
from onyx.tools.tool_implementations.sandbox.models import (
    ARTIFACT_CURSOR,
    ARTIFACTS_CHAT_TITLE_MAX_CHARS,
    ARTIFACTS_LIST_MAX_CHARS,
    ARTIFACTS_LIST_MAX_LIMIT,
    ARTIFACTS_MATERIALIZE_MAX_ITEMS,
    ARTIFACTS_NAME_MAX_CHARS,
    ARTIFACTS_PATH_MAX_CHARS,
    ARTIFACTS_QUERY_MAX_CHARS,
    PUBLISH_FILES_MAX_BYTES,
    PUBLISH_FILES_MAX_FILES,
    PUBLISH_FILES_MAX_TITLE_CHARS,
    ArtifactCursor,
    ArtifactList,
    ArtifactSort,
    LibraryListFilters,
    LibraryPrepareMaterializeArguments,
    ListedArtifact,
    ManageLibraryArguments,
    SortOrder,
    artifact_type,
    artifact_url,
    parse_artifact_url,
)
from onyx.tools.tool_implementations.sandbox.sandbox_tools import (
    ApplyPatchTool,
    ArtifactTool,
    EditTool,
    ExecCommandTool,
    LibraryCreateLibraryFileTool,
    LibraryListTool,
    LibraryManageLibraryTool,
    LibraryPrepareMaterializeTool,
    LibraryReplaceLibraryFileTool,
    WriteStdinTool,
    WriteTool,
    sandbox_tools_for_model,
)
from onyx.tools.tool_implementations.sandbox.spill import RESULT_MAX_CHARS
from onyx.tools.tool_implementations.sandbox.turn import SandboxTurn


def test_claude_models_get_the_artifact_tool_and_the_others_the_library_tools() -> None:
    claude = sandbox_tools_for_model(["claude-sonnet-4-5"])
    other = sandbox_tools_for_model(["gpt-5.1"])
    assert claude == (
        ExecCommandTool,
        WriteStdinTool,
        EditTool,
        WriteTool,
        ArtifactTool,
    )
    assert other == (
        ExecCommandTool,
        WriteStdinTool,
        ApplyPatchTool,
        LibraryCreateLibraryFileTool,
        LibraryListTool,
        LibraryPrepareMaterializeTool,
        LibraryReplaceLibraryFileTool,
        LibraryManageLibraryTool,
    )
    shared = {ExecCommandTool, WriteStdinTool}
    assert not (set(claude) - shared) & (set(other) - shared)


def test_code_mode_defers_the_artifact_tools_in_their_group() -> None:
    turn = MagicMock(spec=SandboxTurn)
    turn.vm_chat_files = []
    stubs = build_tool_stubs(
        [tool(turn) for tool in sandbox_tools_for_model(["gpt-5.1"])]
    )

    assert stubs.deferred_namespaces == {
        "library": LibraryListTool.CODE_MODE_NAMESPACE_DESCRIPTION
    }
    assert {
        name for name, function in stubs.functions.items() if function.deferred
    } == {
        "library__create_library_file",
        "library__list",
        "library__manage_library",
        "library__prepare_materialize",
        "library__replace_library_file",
    }
    assert "library__" not in stubs.listed_text
    assert "create_library_file" not in stubs.listed_text
    assert stubs.tool_index is not None
    # The program gets the result as a typed dict.
    materialize = stubs.functions["library__prepare_materialize"]
    assert "-> MaterializedItems" in materialize.stub
    assert any(
        "class MaterializedItem(TypedDict)" in declaration
        for declaration in materialize.declarations
    )


@pytest.mark.parametrize(
    ("model", "group"), [("claude-sonnet-4-5", "artifact"), ("gpt-5.1", "library")]
)
def test_no_immediate_text_names_an_artifact_function_in_code_mode(
    model: str, group: str
) -> None:
    """Every artifact function is deferred in its family's group: only the
    deferred-groups note names the group, and no listed function, tool
    description or system prompt names a function of it."""
    turn = MagicMock(spec=SandboxTurn)
    turn.vm_chat_files = []
    tools: list[Tool] = [tool(turn) for tool in sandbox_tools_for_model([model])]
    artifact_functions = [
        tool for tool in tools if tool.code_mode_function_name.namespace == group
    ]
    assert artifact_functions
    assert all(
        tool.code_mode_exposure is CodeModeExposure.DEFERRED
        for tool in artifact_functions
    )
    offered, _ = with_code_mode(tools)
    # get_company_context reads the KV store.
    with patch("onyx.chat.prompt_utils.get_company_context", return_value=None):
        prompt = build_system_prompt("base", tools=offered, include_user_info=False)
    immediate = [prompt, *(tool.tool_definition().description for tool in offered)]
    assert any(f"\n  - {group}: " in text for text in immediate)
    for tool in artifact_functions:
        function = tool.code_mode_function_name
        for name in {
            tool.name,
            f"{function.namespace}__{function.name}",
            f"{function.namespace}.{function.name}",
        } - {group}:
            # A whole name: the note names the group, which the artifact
            # tool's name is.
            assert not any(
                re.search(rf"\b{re.escape(name)}\b", text) for text in immediate
            ), name


def test_the_deferred_note_says_what_the_library_group_is_for() -> None:
    turn = MagicMock(spec=SandboxTurn)
    turn.vm_chat_files = []
    offered, _ = with_code_mode(
        [tool(turn) for tool in sandbox_tools_for_model(["gpt-5.1"])]
    )
    [description] = [
        tool.tool_definition().description
        for tool in offered
        if tool.name == "execute_code"
    ]
    assert (
        f"\n  - library: {LibraryListTool.CODE_MODE_NAMESPACE_DESCRIPTION}\n"
        in description
    )


class _Listed(BaseModel):
    """The arguments of one get_user_published_files call."""

    query: str | None
    limit: int


def _run(
    monkeypatch: pytest.MonkeyPatch,
    arguments: dict[str, JsonValue],
    rows: list[tuple[ListedArtifact, ArtifactCursor]] | None = None,
) -> tuple[ToolResult, list[_Listed]]:
    """A library_list call whose database gives `rows` (None: the call
    must not open a session), and the database calls."""
    listed: list[_Listed] = []

    @contextmanager
    def session() -> Iterator[MagicMock]:
        assert rows is not None, "bad arguments must not reach the database"
        yield MagicMock()

    def published(
        _db_session: object,
        _user_id: object,
        *,
        query: str | None,
        limit: int,
        **_: object,
    ) -> list[tuple[ListedArtifact, ArtifactCursor]]:
        listed.append(_Listed(query=query, limit=limit))
        assert rows is not None
        return rows

    monkeypatch.setattr(artifact_operations, "get_session_with_current_tenant", session)
    monkeypatch.setattr(artifact_operations, "get_user_published_files", published)
    turn = MagicMock(spec=SandboxTurn)
    outcome = LibraryListTool(turn).run(
        ToolInvocation(
            call_id="list",
            arguments=arguments,
            cancellation=CancellationSignal(),
            update=lambda _progress: None,
        ),
        ToolContext(),
    )
    assert isinstance(outcome, ToolResult)
    turn.start_call.assert_not_called()
    return outcome, listed


def test_bad_list_arguments_are_tool_errors_without_the_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chat_id = "not-a-chat"
    bad_chat, _ = _run(monkeypatch, {"chat_id": chat_id})
    assert bad_chat.is_error
    assert bad_chat.content == f"No chat {chat_id} of yours"
    # A list result never spills, so its error cannot echo a long ID.
    long_chat, _ = _run(monkeypatch, {"chat_id": "x" * (ARTIFACTS_PATH_MAX_CHARS + 1)})
    assert long_chat.content == (
        "Invalid tool arguments: chat_id: String should have at most "
        f"{ARTIFACTS_PATH_MAX_CHARS} characters"
    )

    for cursor in ("%%%", "bm90IGpzb24=", str(uuid4())):
        bad_cursor, _ = _run(monkeypatch, {"cursor": cursor})
        assert bad_cursor.is_error
        assert bad_cursor.content.startswith("The cursor is not a next_cursor")

    # A cursor of another sort or order would skip or repeat files.
    name_cursor = ARTIFACT_CURSOR.validate_python(_key("name", "asc"))
    by_name = _cursor(name_cursor)
    other_arguments: list[dict[str, JsonValue]] = [
        {"cursor": by_name},
        {"cursor": by_name, "sort": "name"},
        {"cursor": by_name, "sort_order": "asc"},
    ]
    for arguments in other_arguments:
        other_sort, _ = _run(monkeypatch, arguments)
        assert other_sort.is_error
        assert other_sort.content == (
            "The cursor is from a list with sort name and sort_order asc; send "
            "those, or list again without the cursor"
        )

    long_query, _ = _run(monkeypatch, {"query": "x" * (ARTIFACTS_QUERY_MAX_CHARS + 1)})
    assert long_query.is_error
    assert long_query.content == (
        f"The query is longer than {ARTIFACTS_QUERY_MAX_CHARS} characters"
    )


def test_the_limit_is_clamped_and_a_blank_query_lists_every_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for limit, used in ((0, 1), (-3, 1), (500, ARTIFACTS_LIST_MAX_LIMIT), (7, 7)):
        _, [listed] = _run(monkeypatch, {"limit": limit, "query": "   "}, rows=[])
        assert listed == _Listed(query=None, limit=used)
    _, [listed] = _run(monkeypatch, {"query": "  q3 "}, rows=[])
    assert listed.query == "q3"


def _key(sort: ArtifactSort, sort_order: SortOrder) -> dict[str, object]:
    return {
        "sort": sort,
        "sort_order": sort_order,
        "key": {
            "created_at": datetime.now(timezone.utc),
            "modified_at": datetime.now(timezone.utc),
            "name": "2026-11-20.txt",
            "size": 7,
        }[sort],
        "artifact_id": uuid4(),
    }


def _cursor(cursor: ArtifactCursor) -> str:
    return base64.urlsafe_b64encode(ARTIFACT_CURSOR.dump_json(cursor)).decode()


@pytest.mark.parametrize("sort", ["created_at", "modified_at", "name", "size"])
def test_a_cursor_keeps_its_sort_keys_type(sort: ArtifactSort) -> None:
    """A name that reads as a date stays a name."""
    cursor = ARTIFACT_CURSOR.validate_python(_key(sort, "desc"))
    assert (
        ARTIFACT_CURSOR.validate_json(base64.urlsafe_b64decode(_cursor(cursor)))
        == cursor
    )


_LONG_ID = "x" * (ARTIFACTS_PATH_MAX_CHARS + 1)


@pytest.mark.parametrize(
    ("model", "arguments", "field"),
    [
        (
            LibraryPrepareMaterializeArguments,
            {"items": [{"file_id": _LONG_ID}]},
            "items.0.file_id",
        ),
        *(
            (
                LibraryPrepareMaterializeArguments,
                {"items": [{"file_id": "f", key: _LONG_ID}]},
                f"items.0.{key}",
            )
            for key in ("file_name", "relative_directory")
        ),
        (
            LibraryPrepareMaterializeArguments,
            {"items": [{"file_id": "f"}], "destination": {"directory": _LONG_ID}},
            "destination.directory",
        ),
        (
            ManageLibraryArguments,
            {
                "operations": [
                    {
                        "operation": "rename",
                        "target": {"file_id": "f"},
                        "new_name": _LONG_ID,
                    }
                ]
            },
            "operations.0.rename.new_name",
        ),
    ],
)
def test_text_that_a_result_echoes_is_refused_when_too_long(
    model: type[BaseModel], arguments: dict[str, JsonValue], field: str
) -> None:
    with pytest.raises(ToolCallException) as refused:
        parse_tool_arguments(model, arguments)
    assert refused.value.llm_facing_message == (
        f"Invalid tool arguments: {field}: String should have at most "
        f"{ARTIFACTS_PATH_MAX_CHARS} characters"
    )


def test_list_filters_take_extensions_in_any_form_and_times_in_utc() -> None:
    filters = LibraryListFilters.model_validate(
        {
            "include_file_types": [".XLSX", " csv "],
            "exclude_file_types": ["Png"],
            "created_after": "2026-11-20",
            "modified_before": "2026-11-20T10:00:00+02:00",
        }
    )
    assert filters.include_file_types == ["xlsx", "csv"]
    assert filters.exclude_file_types == ["png"]
    assert filters.created_after == datetime(2026, 11, 20, tzinfo=timezone.utc)
    assert filters.modified_before == datetime(2026, 11, 20, 8, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("created_after", "0001-01-01T00:00:00+05:00"),
        ("modified_before", "9999-12-31T23:00:00-05:00"),
    ],
)
def test_a_filter_time_outside_the_utc_range_names_its_field(
    monkeypatch: pytest.MonkeyPatch, field: str, value: str
) -> None:
    result, _ = _run(monkeypatch, {"filters": {field: value}})
    assert result.is_error
    assert result.content.startswith(f"Invalid tool arguments: filters.{field}: ")


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("photo.JPG", "image"),
        ("chart.svg", "image"),
        ("data.csv", "sheet"),
        ("book.xlsm", "sheet"),
        ("deck.pptx", "slides"),
        ("talk.key", "slides"),
        ("report.pdf", "report"),
        ("notes.md", "report"),
        ("page.html", "report"),
        ("data.json", "other"),
        ("Makefile", "other"),
        ("archive.tar.gz", "other"),
    ],
)
def test_the_artifact_type_comes_from_the_extension(name: str, expected: str) -> None:
    assert artifact_type(name) == expected


def _entry(index: int) -> tuple[ListedArtifact, ArtifactCursor]:
    """An entry with every text at its longest, all of it characters that
    JSON escapes."""
    return (
        ListedArtifact(
            library_file_id=uuid4(),
            file_id=str(uuid4()),
            version_number=index,
            file_name='"' * ARTIFACTS_NAME_MAX_CHARS,
            title='"' * PUBLISH_FILES_MAX_TITLE_CHARS,
            artifact_type="slides",
            mime_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
            file_size_bytes=PUBLISH_FILES_MAX_BYTES,
            created_at=datetime.now(timezone.utc),
            modified_at=datetime.now(timezone.utc),
            chat_id=uuid4(),
            chat_title='"' * ARTIFACTS_CHAT_TITLE_MAX_CHARS,
            path="\\" * ARTIFACTS_PATH_MAX_CHARS,
            url=artifact_url(uuid4(), PUBLISH_FILES_MAX_BYTES),
        ),
        ARTIFACT_CURSOR.validate_python(_key("name", "desc")),
    )


@pytest.mark.parametrize(("name", "file"), [("README", ".csv"), (".csv", "README")])
def test_a_new_version_keeps_the_type_by_the_lists_last_dot_rule(
    name: str, file: str
) -> None:
    """The list reads a file's type from the text after the last dot, so a
    version that adds or drops that text is refused."""
    artifact = _entry(1)[0].model_copy(update={"file_name": name})

    with pytest.raises(ToolCallException, match="is not a file of the type of"):
        artifact_operations.check_same_type(artifact, f"/workspace/{file}")


def test_a_full_page_never_spills(monkeypatch: pytest.MonkeyPatch) -> None:
    assert ARTIFACTS_LIST_MAX_CHARS < RESULT_MAX_CHARS
    rows = [_entry(index) for index in range(ARTIFACTS_LIST_MAX_LIMIT + 1)]
    result, _ = _run(
        monkeypatch,
        {"limit": ARTIFACTS_LIST_MAX_LIMIT, "sort": "name"},
        rows=rows,
    )

    assert len(result.content) <= ARTIFACTS_LIST_MAX_CHARS
    page = ArtifactList.model_validate_json(result.content)
    # The page drops its last entries to fit; the cursor starts after the
    # last one shown.
    shown = len(page.files)
    assert 0 < shown < ARTIFACTS_LIST_MAX_LIMIT
    assert page.files == [artifact for artifact, _ in rows[:shown]]
    assert page.next_cursor == _cursor(rows[shown - 1][1])


# The links that both the backend parser and the web's parseArtifactLink
# read: each with its artifact and version, or null for one they refuse.
_ARTIFACT_LINKS = json.loads(
    (Path(__file__).parent / "artifact_links.json").read_text()
)


@pytest.mark.parametrize("web_domain", ["https://x.test", "https://x.test/"])
def test_an_artifact_url_round_trips(
    monkeypatch: pytest.MonkeyPatch, web_domain: str
) -> None:
    monkeypatch.setattr(
        "onyx.tools.tool_implementations.sandbox.models.WEB_DOMAIN", web_domain
    )
    artifact_id = uuid4()
    url = artifact_url(artifact_id, 3)
    assert url == f"https://x.test/app/artifacts/{artifact_id}/v3"
    assert parse_artifact_url(url) == (artifact_id, 3)


@pytest.mark.parametrize(
    "example", _ARTIFACT_LINKS, ids=lambda example: example["link"]
)
def test_an_artifact_link_names_the_artifact_and_maybe_a_version(
    example: dict[str, str | int | None],
) -> None:
    if example["artifact_id"] is None:
        with pytest.raises(ValueError):
            parse_artifact_url(str(example["link"]))
    else:
        assert parse_artifact_url(str(example["link"])) == (
            UUID(str(example["artifact_id"])),
            example["version"],
        )


# Its results are never spilled, and each echoes the paths that it took.
_LONG_PATH = "a/" * ARTIFACTS_PATH_MAX_CHARS


@pytest.mark.parametrize(
    ("arguments", "error"),
    [
        (
            {"file_path": "a.md", "out_dir": "x"},
            "Invalid tool arguments: Action publish does not take out_dir; it takes file_path, "
            "file_paths, force, title, url",
        ),
        (
            {"action": "list", "url": "x"},
            "Invalid tool arguments: Action list does not take url; it takes after, limit, query, scope, type",
        ),
        (
            {
                "file_path": "a.md",
                "url": "/app/artifacts/5b1f6e2a-7c3d-4e8f-9a0b-1c2d3e4f5a6b",
            },
            "Pass the url from your last result, which names the version you "
            "saw, or force:true",
        ),
        (
            {
                "file_paths": ["a.md"],
                "url": "/app/artifacts/5b1f6e2a-7c3d-4e8f-9a0b-1c2d3e4f5a6b/v1",
            },
            "title and url go with file_path",
        ),
        ({"file_path": "a.md", "force": True}, "force goes with url"),
        ({}, "publish takes file_path or file_paths"),
        (
            {"file_path": "a.md", "file_paths": ["b.md"]},
            "publish takes file_path or file_paths",
        ),
        ({"file_paths": ["a.md"], "title": "A"}, "title and url go with file_path"),
        ({"file_paths": []}, "publish takes file_path or file_paths"),
        (
            {"file_paths": ["a.md"] * (PUBLISH_FILES_MAX_FILES + 1)},
            f"publish takes at most {PUBLISH_FILES_MAX_FILES} file_paths",
        ),
        ({"action": "read", "out_dir": "x"}, "read takes url, path or paths"),
        (
            {
                "action": "read",
                "paths": ["f"] * (ARTIFACTS_MATERIALIZE_MAX_ITEMS + 1),
                "out_dir": "x",
            },
            f"read copies at most {ARTIFACTS_MATERIALIZE_MAX_ITEMS} files; pass "
            "fewer paths",
        ),
        (
            {"action": "read", "path": "f"},
            "read copies published files into the VM: pass out_dir, the "
            "directory for the copies",
        ),
        (
            {"action": "read", "url": "report.pdf", "out_dir": "x"},
            "'report.pdf' is not an artifact url",
        ),
        ({"action": "delete"}, "Invalid tool arguments: delete takes url"),
        (
            {
                "action": "rename",
                "url": "/app/artifacts/5b1f6e2a-7c3d-4e8f-9a0b-1c2d3e4f5a6b",
            },
            "Invalid tool arguments: rename takes url and name",
        ),
        ({"action": "open"}, None),
        ({"icon": "x"}, None),
        *(
            (
                arguments,
                f"Invalid tool arguments: {field}: String should have at "
                f"most {ARTIFACTS_PATH_MAX_CHARS} characters",
            )
            for arguments, field in (
                ({"file_path": _LONG_PATH}, "file_path"),
                ({"file_paths": ["a.md", _LONG_PATH]}, "file_paths.1"),
                ({"action": "read", "url": _LONG_PATH, "out_dir": "x"}, "url"),
                ({"action": "read", "path": _LONG_PATH, "out_dir": "x"}, "path"),
                ({"action": "read", "paths": [_LONG_PATH], "out_dir": "x"}, "paths.0"),
                ({"action": "read", "path": "f", "out_dir": _LONG_PATH}, "out_dir"),
                ({"action": "rename", "url": "u", "name": _LONG_PATH}, "name"),
            )
        ),
    ],
)
def test_the_artifact_tool_refuses_arguments_that_do_not_fit_the_action(
    arguments: dict[str, JsonValue], error: str | None
) -> None:
    """Refused calls never start the VM. An unknown action or argument is a
    validation error."""
    turn = MagicMock(spec=SandboxTurn)
    outcome = ArtifactTool(turn).run(
        ToolInvocation(
            call_id="artifact",
            arguments=arguments,
            cancellation=CancellationSignal(),
            update=lambda _progress: None,
        ),
        ToolContext(),
    )
    assert isinstance(outcome, ToolResult)
    assert outcome.is_error
    if error is not None:
        assert outcome.content == error
    turn.start_call.assert_not_called()


@pytest.mark.parametrize(
    ("arguments", "error"),
    [
        ({}, "give exactly one of file and files"),
        ({"file": "a.md", "files": ["b.md"]}, "give exactly one of file and files"),
        ({"files": ["a.md"], "title": "A"}, "title goes with file"),
        ({"files": []}, None),
        ({"path": "a.md"}, None),
    ],
)
def test_create_file_takes_one_file_or_several_without_starting_the_vm(
    arguments: dict[str, JsonValue], error: str | None
) -> None:
    turn = MagicMock(spec=SandboxTurn)
    outcome = LibraryCreateLibraryFileTool(turn).run(
        ToolInvocation(
            call_id="create",
            arguments=arguments,
            cancellation=CancellationSignal(),
            update=lambda _progress: None,
        ),
        ToolContext(),
    )
    assert isinstance(outcome, ToolResult)
    assert outcome.is_error
    if error is not None:
        assert error in outcome.content
    turn.start_call.assert_not_called()


@pytest.mark.parametrize(
    ("tool", "arguments"),
    [
        (ArtifactTool, {"file_path": "a.md"}),
        (ArtifactTool, {"action": "list"}),
        (ArtifactTool, {"action": "delete", "url": "not a url"}),
        (ArtifactTool, {"action": "delete", "icon": "x"}),
        # The call refuses the argument, so the hook does not ask.
        (
            ArtifactTool,
            {
                "action": "delete",
                "url": "/app/artifacts/5b1f6e2a-7c3d-4e8f-9a0b-1c2d3e4f5a6b",
                "out_dir": "x",
            },
        ),
        (LibraryManageLibraryTool, {"operations": []}),
        (LibraryManageLibraryTool, {"operations": [{"operation": "move"}]}),
    ],
)
def test_a_call_that_does_not_delete_asks_nothing_and_reads_no_database(
    monkeypatch: pytest.MonkeyPatch,
    tool: type[ArtifactTool] | type[LibraryManageLibraryTool],
    arguments: dict[str, JsonValue],
) -> None:
    """The approval hook runs before every call of a gated tool, so a call
    that deletes nothing costs only its argument parse."""

    def no_lookup(*_args: object) -> None:
        raise AssertionError("the hook must not look anything up")

    monkeypatch.setattr(artifact_operations, "delete_approval_details", no_lookup)
    assert tool(MagicMock(spec=SandboxTurn)).approval_details(arguments) is None
