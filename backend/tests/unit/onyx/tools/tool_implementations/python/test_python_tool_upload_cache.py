"""Unit tests for PythonTool file-upload caching.

Verifies that PythonTool reuses code-interpreter file IDs across multiple
run() calls within the same session instead of re-uploading identical content
on every agent loop iteration.
"""

import json
from unittest.mock import MagicMock
from unittest.mock import patch

from onyx.tools.models import ChatFile
from onyx.tools.models import PythonToolOverrideKwargs
from onyx.tools.models import ToolResponse
from onyx.tools.tool_implementations.python.code_interpreter_client import (
    StreamResultEvent,
)
from onyx.tools.tool_implementations.python.python_tool import _build_staging_notice
from onyx.tools.tool_implementations.python.python_tool import _code_references_file
from onyx.tools.tool_implementations.python.python_tool import _select_files_for_staging
from onyx.tools.tool_implementations.python.python_tool import PythonTool

TOOL_MODULE = "onyx.tools.tool_implementations.python.python_tool"


def _make_stream_result() -> StreamResultEvent:
    return StreamResultEvent(
        exit_code=0,
        timed_out=False,
        duration_ms=10,
        files=[],
    )


def _make_tool() -> PythonTool:
    emitter = MagicMock()
    return PythonTool(tool_id=1, emitter=emitter)


def _make_override(files: list[ChatFile]) -> PythonToolOverrideKwargs:
    return PythonToolOverrideKwargs(chat_files=files)


def _run_tool(
    tool: PythonTool,
    mock_client: MagicMock,
    files: list[ChatFile],
    code: str = "print('hi')",
) -> ToolResponse:
    """Call tool.run() with a mocked CodeInterpreterClient context manager."""
    from onyx.server.query_and_chat.placement import Placement

    mock_client.execute_streaming.return_value = iter([_make_stream_result()])

    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=mock_client)
    ctx.__exit__ = MagicMock(return_value=False)

    placement = Placement(turn_index=0, tab_index=0)
    override = _make_override(files)

    with patch(f"{TOOL_MODULE}.CodeInterpreterClient", return_value=ctx):
        return tool.run(placement=placement, override_kwargs=override, code=code)


# ---------------------------------------------------------------------------
# Cache hit: same content uploaded in a second call reuses the file_id
# ---------------------------------------------------------------------------


@patch(f"{TOOL_MODULE}.CODE_INTERPRETER_BASE_URL", "http://fake:8000")
def test_same_file_uploaded_only_once_across_two_runs() -> None:
    tool = _make_tool()
    client = MagicMock()
    client.upload_file.return_value = "file-id-abc"

    pptx_content = b"fake pptx bytes"
    files = [ChatFile(filename="report.pptx", content=pptx_content)]

    _run_tool(tool, client, files)
    _run_tool(tool, client, files)

    # upload_file should only have been called once across both runs
    client.upload_file.assert_called_once_with(pptx_content, "report.pptx")


@patch(f"{TOOL_MODULE}.CODE_INTERPRETER_BASE_URL", "http://fake:8000")
def test_cached_file_id_is_staged_on_second_run() -> None:
    tool = _make_tool()
    client = MagicMock()
    client.upload_file.return_value = "file-id-abc"

    files = [ChatFile(filename="data.pptx", content=b"content")]

    _run_tool(tool, client, files)

    # On the second run, execute_streaming should still receive the file
    client.execute_streaming.return_value = iter([_make_stream_result()])
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=client)
    ctx.__exit__ = MagicMock(return_value=False)

    from onyx.server.query_and_chat.placement import Placement

    placement = Placement(turn_index=1, tab_index=0)
    with patch(f"{TOOL_MODULE}.CodeInterpreterClient", return_value=ctx):
        tool.run(
            placement=placement,
            override_kwargs=_make_override(files),
            code="print('hi')",
        )

    # The second execute_streaming call should include the file
    _, kwargs = client.execute_streaming.call_args
    staged_files = kwargs.get("files") or []
    assert any(f["file_id"] == "file-id-abc" for f in staged_files)


# ---------------------------------------------------------------------------
# Cache miss: different content triggers a new upload
# ---------------------------------------------------------------------------


@patch(f"{TOOL_MODULE}.CODE_INTERPRETER_BASE_URL", "http://fake:8000")
def test_different_file_content_uploaded_separately() -> None:
    tool = _make_tool()
    client = MagicMock()
    client.upload_file.side_effect = ["file-id-v1", "file-id-v2"]

    file_v1 = ChatFile(filename="report.pptx", content=b"version 1")
    file_v2 = ChatFile(filename="report.pptx", content=b"version 2")

    _run_tool(tool, client, [file_v1])
    _run_tool(tool, client, [file_v2])

    assert client.upload_file.call_count == 2


@patch(f"{TOOL_MODULE}.CODE_INTERPRETER_BASE_URL", "http://fake:8000")
def test_multiple_distinct_files_each_uploaded_once() -> None:
    tool = _make_tool()
    client = MagicMock()
    client.upload_file.side_effect = ["id-a", "id-b"]

    files = [
        ChatFile(filename="a.pptx", content=b"aaa"),
        ChatFile(filename="b.xlsx", content=b"bbb"),
    ]

    _run_tool(tool, client, files)
    _run_tool(tool, client, files)

    # Two distinct files — each uploaded exactly once
    assert client.upload_file.call_count == 2


@patch(f"{TOOL_MODULE}.CODE_INTERPRETER_BASE_URL", "http://fake:8000")
def test_same_content_different_filename_uploaded_separately() -> None:
    # Identical bytes but different names must each get their own upload slot
    # so both files appear under their respective paths in the workspace.
    tool = _make_tool()
    client = MagicMock()
    client.upload_file.side_effect = ["id-v1", "id-v2"]

    same_bytes = b"shared content"
    files = [
        ChatFile(filename="report_v1.csv", content=same_bytes),
        ChatFile(filename="report_v2.csv", content=same_bytes),
    ]

    _run_tool(tool, client, files)

    assert client.upload_file.call_count == 2


@patch(f"{TOOL_MODULE}.CODE_INTERPRETER_BASE_URL", "http://fake:8000")
def test_unsafe_filename_sanitized_before_upload_and_stage() -> None:
    tool = _make_tool()
    client = MagicMock()
    client.upload_file.return_value = "safe-file-id"

    files = [ChatFile(filename="../reports/q1.csv", content=b"data")]

    _run_tool(tool, client, files)

    client.upload_file.assert_called_once_with(b"data", "_reports_q1.csv")
    _, kwargs = client.execute_streaming.call_args
    assert kwargs["files"] == [{"path": "_reports_q1.csv", "file_id": "safe-file-id"}]


@patch(f"{TOOL_MODULE}.CODE_INTERPRETER_BASE_URL", "http://fake:8000")
def test_sanitized_filename_collisions_get_deduped() -> None:
    tool = _make_tool()
    client = MagicMock()
    # Return an id derived from the name so assertions don't depend on the
    # (now concurrent, non-deterministic) order uploads complete in.
    client.upload_file.side_effect = lambda _content, name: f"id::{name}"

    files = [
        ChatFile(filename="a/b.csv", content=b"first"),
        ChatFile(filename="a_b.csv", content=b"second"),
    ]

    _run_tool(tool, client, files)

    uploaded_names = {call.args[1] for call in client.upload_file.call_args_list}
    assert uploaded_names == {"a_b.csv", "a_b_1.csv"}
    _, kwargs = client.execute_streaming.call_args
    assert kwargs["files"] == [
        {"path": "a_b.csv", "file_id": "id::a_b.csv"},
        {"path": "a_b_1.csv", "file_id": "id::a_b_1.csv"},
    ]


# ---------------------------------------------------------------------------
# No cross-instance sharing: a fresh PythonTool re-uploads everything
# ---------------------------------------------------------------------------


@patch(f"{TOOL_MODULE}.CODE_INTERPRETER_BASE_URL", "http://fake:8000")
def test_new_tool_instance_re_uploads_file() -> None:
    client = MagicMock()
    client.upload_file.side_effect = ["id-session-1", "id-session-2"]

    files = [ChatFile(filename="deck.pptx", content=b"slide data")]

    tool_session_1 = _make_tool()
    _run_tool(tool_session_1, client, files)

    tool_session_2 = _make_tool()
    _run_tool(tool_session_2, client, files)

    # Different instances — each uploads independently
    assert client.upload_file.call_count == 2


# ---------------------------------------------------------------------------
# Upload failure: failed upload is not cached, retried next run
# ---------------------------------------------------------------------------


@patch(f"{TOOL_MODULE}.CODE_INTERPRETER_BASE_URL", "http://fake:8000")
def test_upload_failure_not_cached() -> None:
    tool = _make_tool()
    client = MagicMock()
    # First call raises, second succeeds
    client.upload_file.side_effect = [Exception("network error"), "file-id-ok"]

    files = [ChatFile(filename="slides.pptx", content=b"data")]

    # First run — upload fails, file is skipped but not cached
    _run_tool(tool, client, files)

    # Second run — should attempt upload again
    _run_tool(tool, client, files)

    assert client.upload_file.call_count == 2


# ---------------------------------------------------------------------------
# S1 backstop: per-execution staging cap by file count and total bytes
# ---------------------------------------------------------------------------


def _result_of(resp: ToolResponse) -> dict:
    return json.loads(resp.llm_facing_response)


@patch(f"{TOOL_MODULE}.CODE_INTERPRETER_MAX_STAGED_FILES", 2)
@patch(f"{TOOL_MODULE}.CODE_INTERPRETER_BASE_URL", "http://fake:8000")
def test_staging_caps_file_count_and_keeps_most_recent() -> None:
    tool = _make_tool()
    client = MagicMock()
    client.upload_file.side_effect = [f"id-{i}" for i in range(10)]

    # Files accumulate oldest-first; the two most recent should survive the cap.
    files = [ChatFile(filename=f"f{i}.csv", content=f"c{i}".encode()) for i in range(5)]

    resp = _run_tool(tool, client, files)

    _, kwargs = client.execute_streaming.call_args
    assert [f["path"] for f in kwargs["files"]] == ["f3.csv", "f4.csv"]
    assert client.upload_file.call_count == 2

    notice = _result_of(resp)["staging_notice"]
    assert notice is not None and "3 of 5" in notice


@patch(f"{TOOL_MODULE}.CODE_INTERPRETER_MAX_STAGED_FILES", 2)
@patch(f"{TOOL_MODULE}.CODE_INTERPRETER_BASE_URL", "http://fake:8000")
def test_count_overflow_files_are_not_downloaded() -> None:
    # The dropped (oldest) files must never have their bytes read from the
    # object store — that blocking read is exactly what the cap avoids.
    tool = _make_tool()
    client = MagicMock()
    client.upload_file.side_effect = [f"id-{i}" for i in range(10)]

    download_counts = {f"f{i}.csv": 0 for i in range(5)}

    def _make_loader(name: str):  # type: ignore[no-untyped-def]
        def _load() -> bytes:
            download_counts[name] += 1
            return b"data"

        return _load

    files = [
        ChatFile.lazy_from_filename(
            filename=f"f{i}.csv", loader=_make_loader(f"f{i}.csv")
        )
        for i in range(5)
    ]

    _run_tool(tool, client, files)

    # Only the two most recent files were read; the three oldest were skipped.
    assert download_counts == {
        "f0.csv": 0,
        "f1.csv": 0,
        "f2.csv": 0,
        "f3.csv": 1,
        "f4.csv": 1,
    }


@patch(f"{TOOL_MODULE}.CODE_INTERPRETER_MAX_STAGED_FILES", 10)
@patch(f"{TOOL_MODULE}.CODE_INTERPRETER_MAX_STAGED_BYTES", 10)
@patch(f"{TOOL_MODULE}.CODE_INTERPRETER_BASE_URL", "http://fake:8000")
def test_staging_caps_total_bytes_and_keeps_most_recent() -> None:
    tool = _make_tool()
    client = MagicMock()
    client.upload_file.side_effect = [f"id-{i}" for i in range(10)]

    # Three 6-byte files, 10-byte budget: only the most recent fits.
    files = [ChatFile(filename=f"f{i}.csv", content=b"123456") for i in range(3)]

    resp = _run_tool(tool, client, files)

    _, kwargs = client.execute_streaming.call_args
    assert [f["path"] for f in kwargs["files"]] == ["f2.csv"]
    assert client.upload_file.call_count == 1

    notice = _result_of(resp)["staging_notice"]
    assert notice is not None and "2 of 3" in notice


@patch(f"{TOOL_MODULE}.CODE_INTERPRETER_BASE_URL", "http://fake:8000")
def test_no_staging_notice_when_under_caps() -> None:
    tool = _make_tool()
    client = MagicMock()
    client.upload_file.side_effect = ["id-a", "id-b"]

    files = [
        ChatFile(filename="a.csv", content=b"aaa"),
        ChatFile(filename="b.xlsx", content=b"bbb"),
    ]

    resp = _run_tool(tool, client, files)

    assert _result_of(resp)["staging_notice"] is None


@patch(f"{TOOL_MODULE}.CODE_INTERPRETER_BASE_URL", "http://fake:8000")
def test_upload_failure_is_surfaced_and_other_files_still_staged() -> None:
    tool = _make_tool()
    client = MagicMock()

    def _upload(_content: bytes, name: str) -> str:
        if name == "bad.csv":
            raise RuntimeError("boom")
        return f"id::{name}"

    client.upload_file.side_effect = _upload

    files = [
        ChatFile(filename="good.csv", content=b"g"),
        ChatFile(filename="bad.csv", content=b"b"),
    ]

    resp = _run_tool(tool, client, files, code="open('good.csv'); open('bad.csv')")

    # The failed file is reported to the LLM; the other file still staged.
    notice = _result_of(resp)["staging_notice"]
    assert notice is not None and "bad.csv" in notice
    _, kwargs = client.execute_streaming.call_args
    assert [f["path"] for f in kwargs["files"]] == ["good.csv"]


# ---------------------------------------------------------------------------
# Reference filter: code that names a file prioritizes staging it, then the
# remaining budget is backfilled with the most recent files.
# ---------------------------------------------------------------------------


@patch(f"{TOOL_MODULE}.CODE_INTERPRETER_MAX_STAGED_FILES", 2)
@patch(f"{TOOL_MODULE}.CODE_INTERPRETER_BASE_URL", "http://fake:8000")
def test_referenced_file_prioritized_then_recency_backfill() -> None:
    tool = _make_tool()
    client = MagicMock()
    client.upload_file.side_effect = [f"id-{i}" for i in range(10)]

    # a.csv is the OLDEST file but the code names it; b/c/d are unreferenced.
    files = [ChatFile(filename=f"{n}.csv", content=n.encode()) for n in "abcd"]

    resp = _run_tool(
        tool, client, files, code="import pandas as pd\ndf = pd.read_csv('a.csv')"
    )

    _, kwargs = client.execute_streaming.call_args
    staged = {f["path"] for f in kwargs["files"]}
    # Referenced oldest file kept despite recency, plus the newest backfill.
    assert staged == {"a.csv", "d.csv"}
    assert _result_of(resp)["staging_notice"] is not None


@patch(f"{TOOL_MODULE}.CODE_INTERPRETER_MAX_STAGED_FILES", 1)
@patch(f"{TOOL_MODULE}.CODE_INTERPRETER_BASE_URL", "http://fake:8000")
def test_referenced_old_file_read_unreferenced_recent_not() -> None:
    # With no budget to backfill, only the referenced (old) file is read; the
    # more recent unreferenced file is never pulled from the object store.
    tool = _make_tool()
    client = MagicMock()
    client.upload_file.side_effect = ["id-old"]

    download_counts = {"old.csv": 0, "new.csv": 0}

    def _make_loader(name: str):  # type: ignore[no-untyped-def]
        def _load() -> bytes:
            download_counts[name] += 1
            return b"data"

        return _load

    files = [
        ChatFile.lazy_from_filename(filename="old.csv", loader=_make_loader("old.csv")),
        ChatFile.lazy_from_filename(filename="new.csv", loader=_make_loader("new.csv")),
    ]

    _run_tool(tool, client, files, code="open('old.csv').read()")

    _, kwargs = client.execute_streaming.call_args
    assert [f["path"] for f in kwargs["files"]] == ["old.csv"]
    assert download_counts == {"old.csv": 1, "new.csv": 0}


@patch(f"{TOOL_MODULE}.CODE_INTERPRETER_MAX_STAGED_FILES", 2)
@patch(f"{TOOL_MODULE}.CODE_INTERPRETER_BASE_URL", "http://fake:8000")
def test_dynamic_reference_falls_back_to_recent() -> None:
    # A glob/dynamic reference names no file literally, so the filter matches
    # nothing and we fall back to staging the most recent files (capped).
    tool = _make_tool()
    client = MagicMock()
    client.upload_file.side_effect = [f"id-{i}" for i in range(10)]

    files = [ChatFile(filename=f"f{i}.csv", content=f"c{i}".encode()) for i in range(4)]

    _run_tool(
        tool,
        client,
        files,
        code="import glob\nfor p in glob.glob('*.csv'):\n    print(p)",
    )

    _, kwargs = client.execute_streaming.call_args
    assert [f["path"] for f in kwargs["files"]] == ["f2.csv", "f3.csv"]


# ---------------------------------------------------------------------------
# Direct coverage of the pure selection helper
# ---------------------------------------------------------------------------


def test_select_returns_chronological_order_and_no_drops() -> None:
    files = [ChatFile(filename=f"f{i}.csv", content=b"x") for i in range(4)]
    code = "open('f0.csv'); open('f3.csv')"  # mix of referenced and not

    selection = _select_files_for_staging(
        files, code, max_files=10, max_bytes=1000, read_concurrency=4
    )

    assert [cf.filename for cf, _ in selection.files] == [
        "f0.csv",
        "f1.csv",
        "f2.csv",
        "f3.csv",
    ]
    assert selection.dropped_by_caps == 0
    assert selection.read_failures == []


def test_select_always_keeps_one_file_over_byte_budget() -> None:
    # A single file larger than the entire budget is still staged, otherwise
    # the tool could never run against a big-but-required input.
    files = [ChatFile(filename="big.csv", content=b"x" * 100)]

    selection = _select_files_for_staging(
        files, "big.csv", max_files=10, max_bytes=10, read_concurrency=4
    )

    assert [cf.filename for cf, _ in selection.files] == ["big.csv"]
    assert selection.dropped_by_caps == 0


def test_select_skips_unreadable_files() -> None:
    # A file whose bytes can't be read from the object store is skipped rather
    # than aborting staging, and is reported as a read failure (NOT a cap-drop).
    def _bad_loader() -> bytes:
        raise RuntimeError("object store unavailable")

    files = [
        ChatFile.lazy_from_filename(filename="bad.csv", loader=_bad_loader),
        ChatFile(filename="good.csv", content=b"ok"),
    ]

    selection = _select_files_for_staging(
        files,
        "open('bad.csv'); open('good.csv')",
        max_files=10,
        max_bytes=1000,
        read_concurrency=4,
    )

    assert [cf.filename for cf, _ in selection.files] == ["good.csv"]
    assert selection.dropped_by_caps == 0
    assert selection.read_failures == ["bad.csv"]


def test_code_references_file_matches_raw_and_sanitized_names() -> None:
    # Raw filename appears in the code.
    assert _code_references_file("report.csv", "pd.read_csv('report.csv')")
    # Only the sanitized sandbox form ("a:b.csv" -> "a_b.csv") appears.
    assert _code_references_file("a:b.csv", "open('a_b.csv')")
    # Neither form present, and the empty-name guard.
    assert not _code_references_file("report.csv", "print('hello')")
    assert not _code_references_file("", "anything")


def test_staging_notice_combines_drops_and_upload_failures() -> None:
    notice = _build_staging_notice(2, 5, ["x.csv"])
    assert notice is not None
    assert "2 of 5" in notice
    assert "x.csv" in notice

    assert _build_staging_notice(0, 5, []) is None
