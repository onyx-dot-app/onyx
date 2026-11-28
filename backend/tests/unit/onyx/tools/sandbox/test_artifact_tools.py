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
from pydantic import BaseModel, JsonValue, ValidationError

from onyx.agents.tools import ToolInvocation
from onyx.chat.prompt_utils import build_system_prompt
from onyx.context.search.models import ChunkIndexRequest, InferenceChunk
from onyx.file_store.models import ArtifactText
from onyx.llm.cancellation import AgentCancelled, CancellationSignal
from onyx.llm.model_capabilities import ToolFamily
from onyx.llm.models import ToolResult
from onyx.tools.interface import Tool, parse_tool_arguments
from onyx.tools.models import CodeModeExposure, ToolCallException, ToolContext
from onyx.tools.tool_implementations.code_mode.code_mode_tool import with_code_mode
from onyx.tools.tool_implementations.code_mode.shapes import (
    CODE_MODE_SHAPES,
    OPENAI_CODE_MODE,
)
from onyx.tools.tool_implementations.code_mode.stubs import build_tool_stubs
from onyx.tools.tool_implementations.sandbox import artifact_operations
from onyx.tools.tool_implementations.sandbox.models import (
    ARTIFACT_CURSOR,
    ARTIFACT_RESULT_MAX_CHARS,
    ARTIFACTS_CHAT_TITLE_MAX_CHARS,
    ARTIFACTS_LIST_MAX_LIMIT,
    ARTIFACTS_MATERIALIZE_MAX_ITEMS,
    ARTIFACTS_NAME_MAX_CHARS,
    ARTIFACTS_PATH_MAX_CHARS,
    LIBRARY_SEARCH_CHUNKS_PER_QUERY,
    LIBRARY_SEARCH_MAX_SNIPPETS,
    LIBRARY_SEARCH_MAX_TOP_K,
    LIBRARY_SEARCH_SNIPPET_MAX_CHARS,
    PUBLISH_FILES_MAX_BYTES,
    PUBLISH_FILES_MAX_FILES,
    PUBLISH_FILES_MAX_TITLE_CHARS,
    ArtifactCursor,
    ArtifactList,
    ArtifactsFound,
    ArtifactSort,
    ArtifactsRead,
    FindItem,
    LibraryCreateLibraryFileArguments,
    LibraryFindArguments,
    LibraryListArguments,
    LibraryListFilters,
    LibraryPrepareMaterializeArguments,
    LibraryReadArguments,
    LibraryReplaceLibraryFileArguments,
    LibrarySearchArguments,
    LibrarySearchCursor,
    LibrarySearchResult,
    ListedArtifact,
    ManageLibraryArguments,
    ReadItem,
    SortOrder,
    artifact_type,
    artifact_url,
    parse_artifact_url,
)
from onyx.tools.tool_implementations.sandbox.sandbox_tools import (
    SANDBOX_TOOLS,
    ApplyPatchTool,
    ArtifactTool,
    EditTool,
    ExecCommandTool,
    LibraryCreateLibraryFileTool,
    LibraryFindTool,
    LibraryListTool,
    LibraryManageLibraryTool,
    LibraryPrepareMaterializeTool,
    LibraryReadTool,
    LibraryReplaceLibraryFileTool,
    LibrarySearchTool,
    WriteStdinTool,
    WriteTool,
)
from onyx.tools.tool_implementations.sandbox.shapes import (
    SHELL_SHAPES,
    ArtifactArguments,
)
from onyx.tools.tool_implementations.sandbox.spill import RESULT_MAX_CHARS
from onyx.tools.tool_implementations.sandbox.turn import SandboxTurn


def _mock_turn(family: ToolFamily) -> MagicMock:
    """A sandbox turn of the family's shell shape, without chat files."""
    turn = MagicMock(spec=SandboxTurn)
    turn.shell = SHELL_SHAPES[family]
    turn.vm_chat_files = []
    return turn


def test_claude_models_get_the_artifact_tool_and_the_others_the_library_tools() -> None:
    claude = SANDBOX_TOOLS[ToolFamily.CLAUDE].tools
    other = SANDBOX_TOOLS[ToolFamily.OPENAI].tools
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
        LibraryReadTool,
        LibraryFindTool,
        LibraryReplaceLibraryFileTool,
        LibraryManageLibraryTool,
        LibrarySearchTool,
    )
    shared = {ExecCommandTool, WriteStdinTool}
    assert not (set(claude) - shared) & (set(other) - shared)


def test_code_mode_defers_the_artifact_tools_in_their_group() -> None:
    turn = _mock_turn(ToolFamily.OPENAI)
    stubs = build_tool_stubs(
        OPENAI_CODE_MODE,
        [tool(turn) for tool in SANDBOX_TOOLS[ToolFamily.OPENAI].tools],
    )

    assert stubs.deferred_namespaces == {
        "library": LibraryListTool.CODE_MODE_NAMESPACE_DESCRIPTION
    }
    assert not stubs.has_deferred_functions_without_namespace
    assert {
        name for name, function in stubs.functions.items() if function.deferred
    } == {
        "library__create_library_file",
        "library__find",
        "library__list",
        "library__manage_library",
        "library__prepare_materialize",
        "library__read",
        "library__replace_library_file",
        "library__search",
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
    ("family", "group"),
    [(ToolFamily.CLAUDE, "artifact"), (ToolFamily.OPENAI, "library")],
)
def test_no_immediate_text_names_an_artifact_function_in_code_mode(
    family: ToolFamily, group: str
) -> None:
    """Every artifact function is deferred in its family's group: only the
    deferred-groups note names the group, and no listed function, tool
    description or system prompt names a function of it."""
    turn = _mock_turn(family)
    tools: list[Tool] = [tool(turn) for tool in SANDBOX_TOOLS[family].tools]
    artifact_functions = [
        tool for tool in tools if tool.code_mode_function_name.namespace == group
    ]
    assert artifact_functions
    assert all(
        tool.code_mode_exposure is CodeModeExposure.DEFERRED
        for tool in artifact_functions
    )
    offered, _ = with_code_mode(tools, CODE_MODE_SHAPES[family])
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
    turn = _mock_turn(ToolFamily.OPENAI)
    offered, _ = with_code_mode(
        [tool(turn) for tool in SANDBOX_TOOLS[ToolFamily.OPENAI].tools],
        OPENAI_CODE_MODE,
    )
    [description] = [
        tool.tool_definition().description
        for tool in offered
        if tool.name == OPENAI_CODE_MODE.run_name
    ]
    assert (
        f"\n  - library: {LibraryListTool.CODE_MODE_NAMESPACE_DESCRIPTION}\n"
        in description
    )


class _Listed(BaseModel):
    """The arguments of one get_user_published_files call."""

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
        limit: int,
        **_: object,
    ) -> list[tuple[ListedArtifact, ArtifactCursor]]:
        listed.append(_Listed(limit=limit))
        assert rows is not None
        return rows

    monkeypatch.setattr(artifact_operations, "get_session_with_current_tenant", session)
    monkeypatch.setattr(artifact_operations, "get_user_published_files", published)
    turn = _mock_turn(ToolFamily.OPENAI)
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
    assert bad_chat.content.startswith(
        "Invalid tool arguments: chat_id: Input should be a valid UUID"
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

    # Search finds files by text; the list has no query.
    query, _ = _run(monkeypatch, {"query": "q3"})
    assert query.is_error
    assert "query" in query.content


def test_the_limit_is_clamped(monkeypatch: pytest.MonkeyPatch) -> None:
    for limit, used in ((0, 1), (-3, 1), (500, ARTIFACTS_LIST_MAX_LIMIT), (7, 7)):
        _, [listed] = _run(monkeypatch, {"limit": limit}, rows=[])
        assert listed == _Listed(limit=used)


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
        *(
            (ManageLibraryArguments, {"operations": [operation]}, field)
            for operation, field in (
                (
                    {
                        "operation": "restore_version",
                        "library_file_id": str(uuid4()),
                        "version_number": 1,
                        "file_name": _LONG_ID,
                    },
                    "operations.0.restore_version.file_name",
                ),
                (
                    {
                        "operation": "update",
                        "library_file_id": str(uuid4()),
                        "file_uri": {"file_id": "f"},
                        "file_name": _LONG_ID,
                    },
                    "operations.0.update.file_name",
                ),
                (
                    {
                        "operation": "update",
                        "library_file_id": str(uuid4()),
                        "file_uri": {"file_id": _LONG_ID},
                    },
                    "operations.0.update.file_uri.file_id",
                ),
            )
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
    assert ARTIFACT_RESULT_MAX_CHARS < RESULT_MAX_CHARS
    rows = [_entry(index) for index in range(ARTIFACTS_LIST_MAX_LIMIT + 1)]
    result, _ = _run(
        monkeypatch,
        {"limit": ARTIFACTS_LIST_MAX_LIMIT, "sort": "name"},
        rows=rows,
    )

    assert len(result.content) <= ARTIFACT_RESULT_MAX_CHARS
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
            "Invalid tool arguments: Action publish does not take out_dir; it "
            "takes description, file_path, file_paths, force, label, path, title, url",
        ),
        (
            {
                "path": "f",
                "url": "/app/artifacts/5b1f6e2a-7c3d-4e8f-9a0b-1c2d3e4f5a6b/v1",
                "title": "A",
            },
            "Invalid tool arguments: path goes with url, without file_path, "
            "file_paths or title",
        ),
        (
            {"path": "f"},
            "Invalid tool arguments: path goes with url, without file_path, "
            "file_paths or title",
        ),
        (
            {
                "action": "restore",
                "url": "/app/artifacts/5b1f6e2a-7c3d-4e8f-9a0b-1c2d3e4f5a6b",
            },
            "Invalid tool arguments: restore takes the url of the version to restore, ending in /v<N>",
        ),
        (
            {
                "action": "rename",
                "url": "/app/artifacts/5b1f6e2a-7c3d-4e8f-9a0b-1c2d3e4f5a6b",
            },
            "Invalid tool arguments: rename takes url and name",
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
            "Invalid tool arguments: Pass the url from your last result, which names the version you "
            "saw, or force:true",
        ),
        (
            {
                "file_paths": ["a.md"],
                "url": "/app/artifacts/5b1f6e2a-7c3d-4e8f-9a0b-1c2d3e4f5a6b/v1",
            },
            "Invalid tool arguments: title and url go with file_path",
        ),
        (
            {"file_path": "a.md", "force": True},
            "Invalid tool arguments: force and label go with url",
        ),
        (
            {"file_path": "a.md", "label": "why"},
            "Invalid tool arguments: force and label go with url",
        ),
        ({}, "Invalid tool arguments: publish takes file_path or file_paths"),
        (
            {"file_path": "a.md", "file_paths": ["b.md"]},
            "Invalid tool arguments: publish takes file_path or file_paths",
        ),
        (
            {"file_paths": ["a.md"], "title": "A"},
            "Invalid tool arguments: title and url go with file_path",
        ),
        (
            {"file_paths": []},
            "Invalid tool arguments: publish takes file_path or file_paths",
        ),
        (
            {"file_paths": ["a.md"] * (PUBLISH_FILES_MAX_FILES + 1)},
            "Invalid tool arguments: file_paths: List should have at most "
            f"{PUBLISH_FILES_MAX_FILES} items after validation, not "
            f"{PUBLISH_FILES_MAX_FILES + 1}",
        ),
        (
            {"action": "read", "out_dir": "x"},
            "Invalid tool arguments: read takes url, path or paths",
        ),
        *(
            (
                {"action": "read", "paths": ["f", "g"], "offset": 10, **query},
                "Invalid tool arguments: offset pages one file; read one file "
                "at a time to page",
            )
            for query in ({}, {"query": "q"})
        ),
        (
            {
                "action": "read",
                "paths": ["f"] * (ARTIFACTS_MATERIALIZE_MAX_ITEMS + 1),
                "out_dir": "x",
            },
            f"Invalid tool arguments: read copies at most {ARTIFACTS_MATERIALIZE_MAX_ITEMS} files; pass "
            "fewer paths",
        ),
        (
            {"action": "read", "path": "f", "out_dir": "x", "query": "q"},
            "Invalid tool arguments: out_dir copies files; query, offset and limit go with a read of "
            "their text, without out_dir",
        ),
        (
            {"action": "read", "url": "report.pdf", "out_dir": "x"},
            "Invalid tool arguments: 'report.pdf' is not an artifact url",
        ),
        ({"action": "delete"}, "Invalid tool arguments: delete takes url"),
        ({"action": "restore"}, "Invalid tool arguments: restore takes url"),
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
    turn = _mock_turn(ToolFamily.CLAUDE)
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
    turn = _mock_turn(ToolFamily.OPENAI)
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

    monkeypatch.setattr(
        artifact_operations, "get_session_with_current_tenant", no_lookup
    )
    assert tool(_mock_turn(ToolFamily.CLAUDE)).approval_details(arguments) is None


@pytest.mark.parametrize(
    ("model", "item", "error"),
    [
        (ReadItem, {"mode": "pages", "start_page": 3, "end_page": 2}, "end_page"),
        (FindItem, {"pattern": "a", "start_line": 9, "end_line": 4}, "end_line"),
        (FindItem, {"pattern": "a", "start_page": 2, "end_page": 1}, "end_page"),
    ],
)
def test_a_reversed_range_is_refused(
    model: type[ReadItem] | type[FindItem], item: dict[str, JsonValue], error: str
) -> None:
    with pytest.raises(ValidationError, match=f"{error} comes before"):
        model.model_validate({"file_id": "f"} | item)


def _published_texts(
    monkeypatch: pytest.MonkeyPatch,
    texts: dict[str, tuple[ListedArtifact, ArtifactText]],
) -> None:
    """Published files by file ID with their text; any other ID is missing."""

    @contextmanager
    def session() -> Iterator[MagicMock]:
        yield MagicMock()

    def published(
        _db_session: object,
        _user_id: object,
        *,
        file_id: str | None = None,
        **_: object,
    ) -> ListedArtifact | None:
        found = texts.get(file_id or "")
        return None if found is None else found[0]

    def text(file_id: str, _name: str, _size: int) -> ArtifactText:
        return texts[file_id][1]

    monkeypatch.setattr(artifact_operations, "get_session_with_current_tenant", session)
    monkeypatch.setattr(artifact_operations, "get_user_published_file", published)
    monkeypatch.setattr(artifact_operations, "get_or_extract_artifact_text", text)


def _text_file(file_id: str, chat_title: str = "chat") -> ListedArtifact:
    return ListedArtifact(
        library_file_id=uuid4(),
        file_id=file_id,
        version_number=1,
        file_name="n" * (ARTIFACTS_NAME_MAX_CHARS * 10) + ".txt",
        title=None,
        artifact_type="other",
        mime_type="text/plain",
        file_size_bytes=100,
        created_at=datetime.now(timezone.utc),
        modified_at=datetime.now(timezone.utc),
        chat_id=uuid4(),
        chat_title=chat_title,
        path="p/" * ARTIFACTS_PATH_MAX_CHARS + "f.txt",
        url=artifact_url(uuid4(), 1),
    )


_TEXT = ArtifactText(pages=["alpha\nbeta\nalpha\n"], paged=False, truncated=False)


def test_a_long_chat_title_leaves_room_for_the_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A read or find shows each file as a list page does, so a chat title
    over the result limit still leaves its text in the result."""
    chat_title = "t" * (ARTIFACT_RESULT_MAX_CHARS + 1)
    file = _text_file("f", chat_title=chat_title)
    _published_texts(monkeypatch, {"f": (file, _TEXT)})
    user_id = uuid4()

    read = artifact_operations.read(
        user_id, LibraryReadArguments.model_validate({"read": [{"file_id": "f"}]})
    )
    found = artifact_operations.find(
        user_id,
        LibraryFindArguments.model_validate(
            {"find": [{"file_id": "f", "pattern": "alpha"}]}
        ),
    )

    for result in (read, found):
        assert len(result.model_dump_json()) <= ARTIFACT_RESULT_MAX_CHARS
        shown = result.items[0].file
        assert shown.chat_title == chat_title[:ARTIFACTS_CHAT_TITLE_MAX_CHARS]
        assert len(shown.file_name) == ARTIFACTS_NAME_MAX_CHARS
        assert len(shown.path) == ARTIFACTS_PATH_MAX_CHARS
    assert isinstance(read, ArtifactsRead) and "beta" in read.items[0].text
    assert isinstance(found, ArtifactsFound)
    assert [match.line for match in found.items[0].matches] == [1, 3]


def test_a_call_reports_every_refused_file_at_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    empty = ArtifactText(pages=[" \n"], paged=False, truncated=False)
    _published_texts(monkeypatch, {"empty": (_text_file("empty"), empty)})

    with pytest.raises(ToolCallException) as error:
        artifact_operations.read(
            uuid4(),
            LibraryReadArguments.model_validate(
                {"read": [{"file_id": "missing"}, {"file_id": "empty"}]}
            ),
        )

    assert "No published file missing" in error.value.llm_facing_message
    assert "has no text" in error.value.llm_facing_message


def test_a_read_or_find_splits_one_file_into_lines_at_a_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Each file's lines are split, used and dropped before the next file's."""
    _published_texts(
        monkeypatch, {"a": (_text_file("a"), _TEXT), "b": (_text_file("b"), _TEXT)}
    )
    steps: list[str] = []
    for name, step in (
        ("artifact_lines", artifact_operations.artifact_lines),
        ("read_lines", artifact_operations.read_lines),
        ("find_lines", artifact_operations.find_lines),
    ):
        monkeypatch.setattr(
            artifact_operations,
            name,
            lambda *args, _name=name, _step=step, **kwargs: (
                steps.append(_name) or _step(*args, **kwargs)
            ),
        )
    user_id = uuid4()

    artifact_operations.read(
        user_id,
        LibraryReadArguments.model_validate(
            {"read": [{"file_id": "a"}, {"file_id": "b"}]}
        ),
    )
    artifact_operations.find(
        user_id,
        LibraryFindArguments.model_validate(
            {
                "find": [
                    {"file_id": "a", "pattern": "beta"},
                    {"file_id": "b", "pattern": "beta"},
                ]
            }
        ),
    )

    assert (
        steps
        == ["artifact_lines", "read_lines"] * 2
        + [
            "artifact_lines",
            "find_lines",
        ]
        * 2
    )


def test_a_snippet_is_the_highlight_or_the_text_around_the_first_query_word() -> None:
    snippet = artifact_operations.search_snippet
    assert (
        snippet(["", "the <hi>river</hi>\n bend"], "unused", ["river"])
        == "the river bend"
    )
    # Without highlights, the text starts at the word before the lead.
    filler = " ".join(f"word{index}" for index in range(30))
    text = f"{filler} the Otter swims"
    shown = snippet([], text, ["missing", "otter"])
    assert shown.startswith("…") and shown.endswith("the Otter swims")
    assert text.endswith(shown[1:])
    assert len(shown) - len("… the Otter swims") <= 60 + len("word29")
    # A word near the start, or no word at all, keeps the start.
    assert snippet([], "Otter first", ["otter"]) == "Otter first"
    assert snippet([], "  a  b\n\nc ", []) == "a b c"
    long = snippet([], "x" * 1_000, ["x"])
    assert len(long) == LIBRARY_SEARCH_SNIPPET_MAX_CHARS and long.endswith("…")


def test_a_snippet_keeps_a_match_that_has_no_space_near_it() -> None:
    """In text with few spaces, such as minified JSON, the snippet starts
    inside the lead rather than at a word so far back that the cut drops
    the match."""
    snippet = artifact_operations.search_snippet
    record = json.dumps({"id": 1, "tags": ["a", "b"]}, separators=(",", ":"))
    for text in (
        f'[{",".join([record] * 40)},"otter"]',
        f'intro [{",".join([record] * 40)},"otter"]',
    ):
        shown = snippet([], text, ["otter"])
        assert "otter" in shown, shown
        assert len(shown) <= LIBRARY_SEARCH_SNIPPET_MAX_CHARS
        assert shown.startswith("…") and text.endswith(shown[1:])
    # A space near enough still starts the snippet at its word.
    spaced = "alpha " + "y" * 100 + " the otter"
    assert snippet([], spaced, ["otter"]) == "…" + "y" * 100 + " the otter"


def test_a_snippet_finds_its_match_where_lowercase_changes_the_length() -> None:
    # "İ".lower() is two characters long.
    text = "İ" * 200 + " the otter swims"
    shown = artifact_operations.search_snippet([], text, ["OTTER"])
    assert shown.startswith("…") and shown.endswith("the otter swims")
    assert text.endswith(shown[1:])


def test_a_snippet_shows_the_words_of_the_query_that_found_its_chunk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Another query's word near the start does not push the match out."""
    file = _entry(0)[0]
    filler = " ".join(f"word{index}" for index in range(80))

    @contextmanager
    def session() -> Iterator[MagicMock]:
        yield MagicMock()

    def search_chunks(request: ChunkIndexRequest, *_args: object) -> list[MagicMock]:
        if request.query != "otter":
            return []
        found = MagicMock(spec=InferenceChunk)
        found.document_id = str(file.library_file_id)
        found.match_highlights = []
        found.content = f"beaver {filler} the otter swims"
        return [found]

    monkeypatch.setattr(artifact_operations, "get_session_with_current_tenant", session)
    monkeypatch.setattr(
        artifact_operations,
        "get_user_artifact_search_candidates",
        lambda *_args, **_kwargs: [(file.library_file_id, (False, False))],
    )
    for name in ("get_current_search_settings", "get_default_document_index"):
        monkeypatch.setattr(artifact_operations, name, MagicMock())
    monkeypatch.setattr(artifact_operations, "EmbeddingModel", MagicMock())
    monkeypatch.setattr(artifact_operations, "search_chunks", search_chunks)
    monkeypatch.setattr(
        artifact_operations,
        "get_user_published_files_by_id",
        lambda *_args, **_kwargs: {file.library_file_id: (file, True)},
    )

    found = artifact_operations.search_artifacts(
        uuid4(),
        CancellationSignal(),
        LibrarySearchArguments.model_validate(
            {"search_query": [{"q": "otter"}, {"q": "beaver"}]}
        ),
    )

    (snippet,) = found.results[0].snippets or []
    assert snippet.endswith("the otter swims")


def test_each_query_gets_a_snippet_before_any_query_gets_another(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A query that matches many chunks of a file leaves a slot for the
    snippet of the next query."""
    file = _entry(0)[0]

    @contextmanager
    def session() -> Iterator[MagicMock]:
        yield MagicMock()

    def chunk(content: str) -> MagicMock:
        found = MagicMock(spec=InferenceChunk)
        found.document_id = str(file.library_file_id)
        found.match_highlights = []
        found.content = content
        return found

    def search_chunks(request: ChunkIndexRequest, *_args: object) -> list[MagicMock]:
        if request.query == "otter":
            return [
                chunk(f"otter part {index}")
                for index in range(LIBRARY_SEARCH_MAX_SNIPPETS + 1)
            ]
        return [chunk("the beaver dam")]

    monkeypatch.setattr(artifact_operations, "get_session_with_current_tenant", session)
    monkeypatch.setattr(
        artifact_operations,
        "get_user_artifact_search_candidates",
        lambda *_args, **_kwargs: [(file.library_file_id, (False, False))],
    )
    for name in ("get_current_search_settings", "get_default_document_index"):
        monkeypatch.setattr(artifact_operations, name, MagicMock())
    monkeypatch.setattr(artifact_operations, "EmbeddingModel", MagicMock())
    monkeypatch.setattr(artifact_operations, "search_chunks", search_chunks)
    monkeypatch.setattr(
        artifact_operations,
        "get_user_published_files_by_id",
        lambda *_args, **_kwargs: {file.library_file_id: (file, True)},
    )

    found = artifact_operations.search_artifacts(
        uuid4(),
        CancellationSignal(),
        LibrarySearchArguments.model_validate(
            {"search_query": [{"q": "otter"}, {"q": "beaver"}]}
        ),
    )

    snippets = found.results[0].snippets or []
    assert len(snippets) == LIBRARY_SEARCH_MAX_SNIPPETS
    assert snippets[:2] == ["otter part 0", "the beaver dam"]


@pytest.mark.parametrize("sort", ["relevance", "created_at", "name"])
def test_only_a_relevance_search_builds_the_embedding_model(
    monkeypatch: pytest.MonkeyPatch, sort: str
) -> None:
    """The other sorts search by keyword only and embed no query."""
    file = _entry(0)[0]

    @contextmanager
    def session() -> Iterator[MagicMock]:
        yield MagicMock()

    monkeypatch.setattr(artifact_operations, "get_session_with_current_tenant", session)
    monkeypatch.setattr(
        artifact_operations,
        "get_user_artifact_search_candidates",
        lambda *_args, **_kwargs: [(file.library_file_id, (False,))],
    )
    for name in ("get_current_search_settings", "get_default_document_index"):
        monkeypatch.setattr(artifact_operations, name, MagicMock())
    embedding_model = MagicMock()
    monkeypatch.setattr(artifact_operations, "EmbeddingModel", embedding_model)
    searched: list[object] = []
    monkeypatch.setattr(
        artifact_operations,
        "search_chunks",
        lambda *args: searched.append(args[4]) or [],
    )

    artifact_operations.search_artifacts(
        uuid4(),
        CancellationSignal(),
        LibrarySearchArguments.model_validate(
            {"search_query": [{"q": "otter"}], "sort": sort}
        ),
    )

    built = sort == "relevance"
    assert embedding_model.from_db_model.called == built
    assert searched == [embedding_model.from_db_model.return_value if built else None]


def test_a_full_retrieval_that_drops_no_chunk_is_the_only_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Another retrieval only helps when the per-file cap dropped chunks."""
    document_ids = [str(uuid4()) for _ in range(LIBRARY_SEARCH_CHUNKS_PER_QUERY // 2)]
    searches: list[ChunkIndexRequest] = []

    def search_chunks(request: ChunkIndexRequest, *_args: object) -> list[MagicMock]:
        searches.append(request)
        chunks = []
        for document_id in document_ids:
            for _ in range(2):
                found = MagicMock(spec=InferenceChunk)
                found.document_id = document_id
                chunks.append(found)
        return chunks

    monkeypatch.setattr(artifact_operations, "search_chunks", search_chunks)

    chunks = artifact_operations._search_file_chunks(
        uuid4(),
        CancellationSignal(),
        MagicMock(),
        MagicMock(),
        "x",
        [*document_ids, str(uuid4())],
    )

    assert len(searches) == 1
    assert [chunk.document_id for chunk in chunks] == [
        document_id for document_id in document_ids for _ in range(2)
    ]


def test_a_stop_after_a_retrieval_ends_the_search_before_the_next(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A full retrieval that dropped chunks would search again, but a Stop
    that came during it ends the search first."""
    document_id = str(uuid4())
    signal = CancellationSignal()
    searches: list[ChunkIndexRequest] = []

    def search_chunks(request: ChunkIndexRequest, *_args: object) -> list[MagicMock]:
        searches.append(request)
        signal.cancel("user")
        chunks = []
        for _ in range(LIBRARY_SEARCH_CHUNKS_PER_QUERY):
            found = MagicMock(spec=InferenceChunk)
            found.document_id = document_id
            chunks.append(found)
        return chunks

    monkeypatch.setattr(artifact_operations, "search_chunks", search_chunks)

    with pytest.raises(AgentCancelled):
        artifact_operations._search_file_chunks(
            uuid4(), signal, MagicMock(), MagicMock(), "x", [document_id, str(uuid4())]
        )

    assert len(searches) == 1


def test_a_full_search_page_never_spills_and_its_cursor_continues_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every text at its longest: the page drops its last results to fit,
    and the cursor starts the next page after the last result shown."""
    files = [_entry(index)[0] for index in range(LIBRARY_SEARCH_MAX_TOP_K + 5)]

    @contextmanager
    def session() -> Iterator[MagicMock]:
        yield MagicMock()

    def chunk(artifact_id: UUID, index: int) -> InferenceChunk:
        found = MagicMock(spec=InferenceChunk)
        found.document_id = str(artifact_id)
        found.match_highlights = [str(index) + '"' * 400]
        found.content = ""
        return found

    monkeypatch.setattr(artifact_operations, "get_session_with_current_tenant", session)
    monkeypatch.setattr(
        artifact_operations,
        "get_user_artifact_search_candidates",
        lambda *_args, **_kwargs: [(file.library_file_id, (False,)) for file in files],
    )
    for name in ("get_current_search_settings", "get_default_document_index"):
        monkeypatch.setattr(artifact_operations, name, MagicMock())
    monkeypatch.setattr(artifact_operations, "EmbeddingModel", MagicMock())
    monkeypatch.setattr(
        artifact_operations,
        "search_chunks",
        lambda *_args: [
            chunk(file.library_file_id, index) for file in files for index in range(3)
        ],
    )
    monkeypatch.setattr(
        artifact_operations,
        "get_user_published_files_by_id",
        lambda _db_session, _user_id, artifact_ids, **_kwargs: {
            file.library_file_id: (file, True)
            for file in files
            if file.library_file_id in artifact_ids
        },
    )

    def search(arguments: dict[str, JsonValue]) -> ToolResult:
        turn = _mock_turn(ToolFamily.OPENAI)
        outcome = LibrarySearchTool(turn).run(
            ToolInvocation(
                call_id="search",
                arguments=arguments,
                cancellation=CancellationSignal(),
                update=lambda _progress: None,
            ),
            ToolContext(),
        )
        assert isinstance(outcome, ToolResult)
        turn.start_call.assert_not_called()
        return outcome

    first = search({"search_query": [{"q": "x"}], "top_k": 500})
    assert len(first.content) <= ARTIFACT_RESULT_MAX_CHARS
    page = LibrarySearchResult.model_validate_json(first.content)
    shown = len(page.results)
    assert 0 < shown < LIBRARY_SEARCH_MAX_TOP_K
    assert [hit.file for hit in page.results] == files[:shown]
    assert all(len(hit.snippets or []) == 3 for hit in page.results)
    assert page.next_cursor is not None
    assert LibrarySearchCursor.model_validate_json(
        base64.urlsafe_b64decode(page.next_cursor)
    ) == LibrarySearchCursor(offset=shown)

    following = LibrarySearchResult.model_validate_json(
        search(
            {"search_query": [{"q": "x"}], "top_k": 2, "cursor": page.next_cursor}
        ).content
    )
    assert [hit.file for hit in following.results] == files[shown : shown + 2]

    negative = base64.urlsafe_b64encode(b'{"offset":-1}').decode()
    for cursor in ("%%%", "bm90IGpzb24=", negative):
        bad = search({"search_query": [{"q": "x"}], "cursor": cursor})
        assert bad.is_error
        assert bad.content.startswith("The cursor is not a next_cursor")


_ARTIFACT = "5b1f6e2a-7c3d-4e8f-9a0b-1c2d3e4f5a6b"


@pytest.mark.parametrize(
    ("arguments", "request_type", "fields"),
    [
        # The arguments of the trained shape that Onyx does not use are
        # ignored; a publish keeps its description.
        (
            {"file_path": "a.md", "description": "Notes.", "icon": "x", "pin": True},
            LibraryCreateLibraryFileArguments,
            {"file": "a.md", "description": "Notes."},
        ),
        (
            {"file_paths": [f"{index}.md" for index in range(PUBLISH_FILES_MAX_FILES)]},
            LibraryCreateLibraryFileArguments,
            {"files": [f"{index}.md" for index in range(PUBLISH_FILES_MAX_FILES)]},
        ),
        (
            {"file_path": "a.md", "url": f"/app/artifacts/{_ARTIFACT}/v2"},
            LibraryReplaceLibraryFileArguments,
            {"file": "a.md", "expected_current_version": 2},
        ),
        (
            {"action": "list", "limit": 50, "after": "c", "type": "sheet"},
            LibraryListArguments,
            {"limit": 50, "cursor": "c"},
        ),
        (
            {"action": "list", "query": "q", "limit": 5},
            LibrarySearchArguments,
            {"top_k": 5},
        ),
        (
            {"action": "read", "path": "f", "offset": 3, "limit": 9},
            LibraryReadArguments,
            {},
        ),
        ({"action": "read", "paths": ["f"], "query": "x"}, LibraryFindArguments, {}),
        (
            {"action": "read", "path": "f", "out_dir": "copies"},
            LibraryPrepareMaterializeArguments,
            {},
        ),
        (
            {"action": "delete", "url": f"/app/artifacts/{_ARTIFACT}"},
            ManageLibraryArguments,
            {},
        ),
    ],
)
def test_each_artifact_action_runs_a_library_operation(
    arguments: dict[str, JsonValue],
    request_type: type[BaseModel],
    fields: dict[str, JsonValue],
) -> None:
    """Both families run the library operations: each artifact action gives
    the arguments of one."""
    request = ArtifactArguments.model_validate(arguments).request()
    assert isinstance(request, request_type)
    assert request.model_dump(include=set(fields)) == fields


@pytest.mark.parametrize(
    ("arguments", "error"),
    [
        (
            {"action": "read", "paths": ["f"] * 6},
            "read shows the text of at most 5 files; pass fewer paths, or copy "
            "them with out_dir",
        ),
        ({"action": "read", "paths": []}, "read takes url, path or paths"),
        (
            {"action": "read", "paths": [], "out_dir": "x"},
            "read takes url, path or paths",
        ),
        ({"action": "read", "path": "f", "offset": 0}, "read's offset is at least 1"),
        (
            {"action": "read", "path": "f", "limit": 2_001},
            "read's limit is from 1 to 2000",
        ),
        (
            {"action": "read", "path": "f", "query": "x", "limit": 101},
            "read's limit is from 1 to 100",
        ),
        (
            {"action": "read", "path": "f", "query": ""},
            "read's query takes 1 to 500 characters",
        ),
        (
            {"action": "list", "query": "q" * 201},
            "list's query takes at most 200 characters",
        ),
    ],
)
def test_the_artifact_tool_names_its_own_arguments_in_refusals(
    arguments: dict[str, JsonValue], error: str
) -> None:
    """A refusal names the artifact tool's arguments, never those of the
    library operation that the action runs."""
    with pytest.raises(ValidationError, match=re.escape(error)):
        ArtifactArguments.model_validate(arguments)


def test_the_approval_hook_asks_nothing_for_a_read_without_files() -> None:
    """The hook runs before every call of the gated tool; arguments that the
    call refuses never fail it."""
    tool = ArtifactTool(_mock_turn(ToolFamily.CLAUDE))
    assert tool.approval_details({"action": "read", "paths": []}) is None
