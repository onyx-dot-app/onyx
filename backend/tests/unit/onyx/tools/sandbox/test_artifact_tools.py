import base64
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from pydantic import BaseModel, JsonValue

from onyx.agents.tools import ToolInvocation
from onyx.llm.cancellation import CancellationSignal
from onyx.llm.models import ToolResult
from onyx.tools.models import ToolContext
from onyx.tools.tool_implementations.code_mode.stubs import build_tool_stubs
from onyx.tools.tool_implementations.sandbox import sandbox_tools
from onyx.tools.tool_implementations.sandbox.models import (
    ARTIFACTS_CHAT_TITLE_MAX_CHARS,
    ARTIFACTS_LIST_MAX_CHARS,
    ARTIFACTS_LIST_MAX_LIMIT,
    ARTIFACTS_NAME_MAX_CHARS,
    ARTIFACTS_PATH_MAX_CHARS,
    ARTIFACTS_QUERY_MAX_CHARS,
    PUBLISH_FILES_MAX_BYTES,
    PUBLISH_FILES_MAX_TITLE_CHARS,
    ArtifactCursor,
    ArtifactList,
    ListedArtifact,
)
from onyx.tools.tool_implementations.sandbox.sandbox_tools import (
    ArtifactsDownloadTool,
    ArtifactsListTool,
    PublishFilesTool,
    sandbox_tools_for_model,
)
from onyx.tools.tool_implementations.sandbox.spill import RESULT_MAX_CHARS
from onyx.tools.tool_implementations.sandbox.turn import SandboxTurn


@pytest.mark.parametrize("model", ["claude-sonnet-4-5", "gpt-5.1"])
def test_every_model_gets_the_artifact_tools_after_publish_files(model: str) -> None:
    tools = sandbox_tools_for_model([model])
    assert tools[-3:] == (PublishFilesTool, ArtifactsListTool, ArtifactsDownloadTool)


def test_code_mode_defers_the_artifact_tools_in_their_group() -> None:
    turn = MagicMock(spec=SandboxTurn)
    turn.vm_chat_files = []
    stubs = build_tool_stubs(
        [tool(turn) for tool in sandbox_tools_for_model(["gpt-5.1"])]
    )

    assert stubs.deferred_namespaces == {
        "artifacts": "Find and download the files that you published in this "
        "chat and the user's other chats."
    }
    assert {
        name for name, function in stubs.functions.items() if function.deferred
    } == {"artifacts__list", "artifacts__download"}
    assert "artifacts__" not in stubs.listed_text
    assert "def publish_files(" in stubs.listed_text
    assert stubs.tool_index is not None
    # The program gets the result as a typed dict.
    download = stubs.functions["artifacts__download"]
    assert "-> DownloadedArtifact" in download.stub
    assert any(
        "class DownloadedArtifact(TypedDict)" in declaration
        for declaration in download.declarations
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
    """An artifacts_list call whose database gives `rows` (None: the call
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

    monkeypatch.setattr(sandbox_tools, "get_session_with_current_tenant", session)
    monkeypatch.setattr(sandbox_tools, "get_user_published_files", published)
    turn = MagicMock(spec=SandboxTurn)
    outcome = ArtifactsListTool(turn).run(
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

    for cursor in ("%%%", "bm90IGpzb24=", str(uuid4())):
        bad_cursor, _ = _run(monkeypatch, {"cursor": cursor})
        assert bad_cursor.is_error
        assert bad_cursor.content.startswith("The cursor is not a next_cursor")

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


def _entry(index: int) -> tuple[ListedArtifact, ArtifactCursor]:
    """An entry with every text at its longest, all of it characters that
    JSON escapes."""
    return (
        ListedArtifact(
            file_id=str(uuid4()),
            name='"' * ARTIFACTS_NAME_MAX_CHARS,
            title='"' * PUBLISH_FILES_MAX_TITLE_CHARS,
            path="\\" * ARTIFACTS_PATH_MAX_CHARS,
            version=index,
            chat_id=uuid4(),
            chat_title='"' * ARTIFACTS_CHAT_TITLE_MAX_CHARS,
            published_at=datetime.now(timezone.utc),
            size=PUBLISH_FILES_MAX_BYTES,
            mime_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ),
        ArtifactCursor(updated_at=datetime.now(timezone.utc), artifact_id=uuid4()),
    )


def test_a_full_page_never_spills(monkeypatch: pytest.MonkeyPatch) -> None:
    assert ARTIFACTS_LIST_MAX_CHARS < RESULT_MAX_CHARS
    rows = [_entry(index) for index in range(ARTIFACTS_LIST_MAX_LIMIT + 1)]
    result, _ = _run(monkeypatch, {"limit": ARTIFACTS_LIST_MAX_LIMIT}, rows=rows)

    assert len(result.content) <= ARTIFACTS_LIST_MAX_CHARS
    page = ArtifactList.model_validate_json(result.content)
    # The page drops its last entries to fit; the cursor starts after the
    # last one shown.
    shown = len(page.artifacts)
    assert 0 < shown < ARTIFACTS_LIST_MAX_LIMIT
    assert page.artifacts == [artifact for artifact, _ in rows[:shown]]
    assert page.next_cursor is not None
    assert (
        ArtifactCursor.model_validate_json(base64.urlsafe_b64decode(page.next_cursor))
        == rows[shown - 1][1]
    )
