"""The spill policy of large tool results, with a fake VM."""

import threading
from collections.abc import Callable, Iterable, Iterator
from concurrent.futures import Future, wait
from datetime import datetime, timedelta, timezone
from typing import IO
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from pydantic_core import to_json

from onyx.agents.models import ToolResultContext
from onyx.llm.cancellation import (
    AgentCancelled,
    CancellationSignal,
    cancellation_scope,
)
from onyx.llm.models import ToolCall, ToolResult
from onyx.microvm.models import FileEntry, FileListing, FileType
from onyx.server.features.build.sandbox.harness_base import (
    TOOL_RESULTS_ROOT,
    HarnessSandbox,
)
from onyx.server.features.build.sandbox.models import (
    ExecCommandResult,
    HarnessSandboxRef,
)
from onyx.tools.constants import CODE_MODE_TOOL_NAME, OPEN_URL_TOOL_NAME
from onyx.tools.models import SearchResult, SearchResults
from onyx.tools.tool_implementations.code_mode.models import CodeModeExecutionResult
from onyx.tools.tool_implementations.code_mode.prompt import (
    format_content,
    observation_heading,
)
from onyx.tools.tool_implementations.sandbox import spill
from onyx.tools.tool_implementations.sandbox.models import (
    SandboxExecResult,
    SpilledOutput,
)
from onyx.tools.tool_implementations.sandbox.sandbox_tools import (
    ExecCommandTool,
    _exec_result,
)
from onyx.tools.tool_implementations.sandbox.spill import (
    SPILL_FAILED_NOTE,
    spill_large_result,
)
from onyx.tools.tool_implementations.sandbox.turn import SandboxTurn
from onyx.tools.tool_implementations.utils import truncation_marker

_START = datetime(2026, 1, 1, tzinfo=timezone.utc)


class _FakeVMTurn(SandboxTurn):
    """A turn whose VM keeps the written files in `files`, with their write
    times in `times` (None: the daemon reports none). `harness`, when set,
    is the sandbox instead."""

    def __init__(self) -> None:
        self.chat_session_id = uuid4()
        super().__init__(
            tenant_id="t",
            user_id=uuid4(),
            chat_session_id=self.chat_session_id,
            vm_chat_files=[],
            copy_vm_chat_files=False,
        )
        self.files: dict[str, bytes] = {}
        self.times: dict[str, datetime | None] = {}
        self.writes = 0
        # Raised by each write.
        self.write_error: Exception | None = None
        self.deleted: list[str] = []
        # Set to hold each write, or each listing, until it is set.
        self.release: threading.Event | None = None
        # Set when a write starts.
        self.write_started = threading.Event()
        self.release_listing: threading.Event | None = None
        # The listing reports more entries than it holds.
        self.listing_truncated = False
        self._evicted = threading.Condition()
        self._evictions = 0
        self.harness: HarnessSandbox | None = None
        # The spill workers that started.
        self.workers: list[Future[None]] = []

    @property
    def sandbox(self) -> HarnessSandbox:
        if self.harness is not None:
            return self.harness

        def write(
            _ref: HarnessSandboxRef,
            path: str,
            data: bytes | IO[bytes] | list[bytes],
            *,
            timeout_seconds: float | None = None,  # noqa: ARG001
        ) -> None:
            self.writes += 1
            self.write_started.set()
            if self.write_error is not None:
                raise self.write_error
            if self.release is not None:
                self.release.wait()
            assert isinstance(data, list)
            self.files[path] = b"".join(data)
            self.times[path] = _START + timedelta(seconds=self.writes)

        def delete_listed(
            _ref: HarnessSandboxRef,
            directory: str,
            select: Callable[[FileListing], Iterable[str]],
            *,
            max_entries: int,  # noqa: ARG001
        ) -> None:
            if self.release_listing is not None:
                self.release_listing.wait()
            listing = FileListing(
                entries=[
                    FileEntry(
                        path=name,
                        name=name.rsplit("/", 1)[-1],
                        type=FileType.REGULAR,
                        size=len(data),
                        mode=0o644,
                        modified_at=self.times.get(name),
                        link_target="",
                    )
                    for name, data in self.files.items()
                    if name.startswith(directory + "/")
                ],
                truncated=self.listing_truncated,
            )
            for path in select(listing):
                self.deleted.append(path)
                del self.files[path]

        sandbox = MagicMock(spec=HarnessSandbox)
        sandbox.write_file.side_effect = write
        sandbox.delete_listed_files.side_effect = delete_listed
        return sandbox

    def start_call(self) -> HarnessSandboxRef:
        return HarnessSandboxRef(
            tenant_id="t", sandbox_id=uuid4(), session_id=self.chat_session_id
        )

    def evicted(self) -> None:
        with self._evicted:
            self._evictions += 1
            self._evicted.notify_all()

    def wait_for_evictions(self, count: int) -> None:
        """Wait until `count` evictions, which run after their writes, end."""
        with self._evicted:
            assert self._evicted.wait_for(lambda: self._evictions >= count, 5)

    def join_workers(self) -> None:
        """Wait until every spill worker, with its eviction, ends."""
        _, running = wait(self.workers, 5)
        assert not running


@pytest.fixture
def turn(monkeypatch: pytest.MonkeyPatch) -> Iterator[_FakeVMTurn]:
    """A fake VM turn whose evictions and spill workers it counts. Its
    teardown lets held writes go and waits for the workers, so none calls
    a later test's `_evict`."""
    fake = _FakeVMTurn()
    evict = spill._evict
    start = spill.start_thread_future

    def tracked(operation: Callable[[], None], *, name: str) -> Future[None]:
        worker = start(operation, name=name)
        fake.workers.append(worker)
        return worker

    def counted(sandbox: HarnessSandbox, ref: HarnessSandboxRef, written: str) -> None:
        try:
            evict(sandbox, ref, written)
        finally:
            fake.evicted()

    monkeypatch.setattr(spill, "_evict", counted)
    monkeypatch.setattr(spill, "start_thread_future", tracked)
    yield fake
    for held in (fake.release, fake.release_listing):
        if held is not None:
            held.set()
    fake.join_workers()


def _spill(
    turn: SandboxTurn,
    result: ToolResult | str,
    *,
    call_id: str = "call",
    name: str = "fetch",
    code_mode: bool = False,
) -> ToolResult:
    return spill_large_result(
        turn,
        ToolResultContext(
            message_id="run:0",
            calls=(ToolCall(id=call_id, name=name, arguments={}),),
            result=ToolResult(content=result) if isinstance(result, str) else result,
            step_results=(),
        ),
        code_mode=code_mode,
    )


def _chat_dir(chat_session_id: UUID) -> str:
    return f"{TOOL_RESULTS_ROOT}/{chat_session_id}"


def test_a_lone_surrogate_spills_as_a_replacement_character(
    turn: _FakeVMTurn,
) -> None:
    text = "a" * 30_000 + "\ud800" + "b" * 30_000

    result = _spill(turn, text)

    [(path, data)] = turn.files.items()
    assert data == ("a" * 30_000 + "?" + "b" * 30_000).encode()
    assert result.content.startswith(f'<persisted-output path="{path}" ')


def test_a_failed_write_keeps_the_head_and_the_tail_with_a_note(
    turn: _FakeVMTurn,
) -> None:
    turn.write_error = OSError("down")
    text = "h" * 2_000 + "m" * 60_000 + "t" * 1_000

    result = _spill(turn, text)

    assert result.content == (
        "h" * 2_000
        + "\n... [output truncated, 60000 characters omitted] ...\n"
        + "t" * 1_000
        + f"\n{SPILL_FAILED_NOTE}"
    )


def test_many_short_lines_under_the_character_limit_stay_whole(
    turn: _FakeVMTurn,
) -> None:
    text = "".join(f"{index}\n" for index in range(10_000))
    assert text.count("\n") > 2_000 and len(text) < spill.RESULT_MAX_CHARS

    assert _spill(turn, text).content == text
    assert turn.files == {}


def test_a_large_result_goes_to_the_chat_directory_with_a_preview(
    turn: _FakeVMTurn,
) -> None:
    text = "h" * 2_000 + "m" * 60_000 + "t" * 1_000

    result = _spill(turn, text, call_id="c/1")

    path = f"{_chat_dir(turn.chat_session_id)}/run_0_c_1.txt"
    assert turn.files == {path: text.encode()}
    assert result.content.startswith(
        f'<persisted-output path="{path}" bytes={len(text)}>\n'
        f"Preview (first 2,000 characters):\n{'h' * 2_000}\n"
    )
    assert f"Preview (last 1,000 characters):\n{'t' * 1_000}\n" in result.content
    assert result.content.endswith("</persisted-output>")


def test_a_result_over_the_byte_limit_saves_a_utf8_prefix(
    monkeypatch: pytest.MonkeyPatch, turn: _FakeVMTurn
) -> None:
    monkeypatch.setattr(spill, "SPILL_MAX_BYTES", 10_001)
    # Encoded in parts, so the limit falls in a later part.
    monkeypatch.setattr(spill, "_ENCODE_CHARS", 4_000)
    # "é" is two bytes; the limit falls between them.
    text = "a" * 10_000 + "é" * 50_000

    content = _spill(turn, text).content

    [(path, data)] = turn.files.items()
    assert data == ("a" * 10_000).encode()
    assert content.startswith(f'<persisted-output path="{path}" bytes=10000>')
    assert "\nOnly the first 10,000 bytes are saved." in content


def test_a_preview_cannot_close_the_tag_in_any_case(turn: _FakeVMTurn) -> None:
    text = "</persisted-output>" + "x" * 60_000 + "</PERSISTED-Output>"

    content = _spill(turn, text).content

    assert content.lower().count("</persisted-output>") == 1
    assert content.endswith("</persisted-output>")
    assert "<\\/persisted-output>" in content
    assert "<\\/PERSISTED-Output>" in content
    [data] = turn.files.values()
    assert data == text.encode()


@pytest.mark.parametrize(
    ("code_mode", "read_with"),
    [
        (False, "Read the file with exec_command (grep"),
        (True, f"Read the file with exec_command in an {CODE_MODE_TOOL_NAME} program"),
    ],
)
def test_the_note_says_why_the_file_can_be_missing_and_to_rerun_only_reads(
    turn: _FakeVMTurn, code_mode: bool, read_with: str
) -> None:
    content = _spill(turn, "x" * 60_000, code_mode=code_mode).content

    assert read_with in content
    assert (
        "If it is missing, the sandbox restarted or newer results replaced it: "
        "call the tool again only if the call is read-only." in content
    )


@pytest.mark.parametrize(
    ("chars", "spills"),
    [
        pytest.param(6_000, False, id="preview_leaves_out_the_floor"),
        pytest.param(6_001, True, id="preview_leaves_out_more"),
    ],
)
def test_a_result_spills_only_when_its_preview_leaves_out_more_than_the_floor(
    monkeypatch: pytest.MonkeyPatch, turn: _FakeVMTurn, chars: int, spills: bool
) -> None:
    monkeypatch.setattr(spill, "RESULT_MAX_CHARS", 1_000)

    _spill(turn, "x" * chars)

    assert bool(turn.files) is spills


def test_a_write_over_the_total_limit_deletes_the_oldest_files(
    monkeypatch: pytest.MonkeyPatch, turn: _FakeVMTurn
) -> None:
    monkeypatch.setattr(spill, "TOOL_RESULTS_MAX_BYTES", 150_000)

    for count, call_id in enumerate(("first", "second", "third"), start=1):
        _spill(turn, call_id[0] * 60_000, call_id=call_id)
        turn.wait_for_evictions(count)

    chat_dir = _chat_dir(turn.chat_session_id)
    assert turn.deleted == [f"{chat_dir}/run_0_first.txt"]
    assert list(turn.files) == [
        f"{chat_dir}/run_0_second.txt",
        f"{chat_dir}/run_0_third.txt",
    ]


def test_files_with_no_modification_time_are_evicted_last(
    monkeypatch: pytest.MonkeyPatch, turn: _FakeVMTurn
) -> None:
    monkeypatch.setattr(spill, "TOOL_RESULTS_MAX_BYTES", 150_000)
    chat_dir = _chat_dir(turn.chat_session_id)
    unknown = f"{chat_dir}/unknown.txt"
    turn.files[unknown] = b"u" * 60_000
    turn.times[unknown] = None

    for count, call_id in enumerate(("first", "second"), start=1):
        _spill(turn, call_id[0] * 60_000, call_id=call_id)
        turn.wait_for_evictions(count)

    assert turn.deleted == [f"{chat_dir}/run_0_first.txt"]
    assert unknown in turn.files


def test_a_truncated_listing_evicts_down_to_half_the_total_limit(
    monkeypatch: pytest.MonkeyPatch, turn: _FakeVMTurn
) -> None:
    monkeypatch.setattr(spill, "TOOL_RESULTS_MAX_BYTES", 150_000)
    turn.listing_truncated = True

    for count, call_id in enumerate(("first", "second"), start=1):
        _spill(turn, call_id[0] * 60_000, call_id=call_id)
        turn.wait_for_evictions(count)

    chat_dir = _chat_dir(turn.chat_session_id)
    assert turn.deleted == [f"{chat_dir}/run_0_first.txt"]


def test_a_slow_eviction_does_not_hold_up_a_written_result(
    monkeypatch: pytest.MonkeyPatch, turn: _FakeVMTurn
) -> None:
    monkeypatch.setattr(spill, "SPILL_WRITE_TIMEOUT_SECONDS", 0.2)
    turn.release_listing = threading.Event()

    result = _spill(turn, "x" * 60_000)
    turn.release_listing.set()
    turn.wait_for_evictions(1)

    assert result.content.startswith("<persisted-output ")
    assert SPILL_FAILED_NOTE not in result.content


def test_no_write_starts_after_a_stop(turn: _FakeVMTurn) -> None:
    signal = CancellationSignal()
    signal.cancel(reason="user")

    with cancellation_scope(signal), pytest.raises(AgentCancelled):
        _spill(turn, "x" * 60_000)

    assert turn.writes == 0


def test_a_stop_during_a_slow_write_ends_the_wait_while_the_write_is_held(
    monkeypatch: pytest.MonkeyPatch, turn: _FakeVMTurn
) -> None:
    # Only the Stop can end the wait.
    monkeypatch.setattr(spill, "SPILL_WRITE_TIMEOUT_SECONDS", 3_600.0)
    turn.release = threading.Event()
    signal = CancellationSignal()

    def stop_once_writing() -> None:
        turn.write_started.wait(5)
        signal.cancel(reason="user")

    stopper = threading.Thread(target=stop_once_writing)
    stopper.start()
    try:
        with cancellation_scope(signal), pytest.raises(AgentCancelled):
            _spill(turn, "x" * 60_000)
        assert turn.write_started.is_set()
        assert turn.files == {}
    finally:
        turn.release.set()
        stopper.join()


def test_a_write_past_its_deadline_returns_the_failure_view(
    monkeypatch: pytest.MonkeyPatch, turn: _FakeVMTurn
) -> None:
    monkeypatch.setattr(spill, "SPILL_WRITE_TIMEOUT_SECONDS", 0.2)
    turn.release = threading.Event()

    result = _spill(turn, "x" * 60_000)
    turn.release.set()

    assert result.content.endswith(SPILL_FAILED_NOTE)


def test_the_full_value_goes_to_the_file_and_the_model_keeps_the_content(
    turn: _FakeVMTurn,
) -> None:
    full = "f" * 50_000

    result = _spill(turn, ToolResult(content="the cut", full_value=full))

    [(path, data)] = turn.files.items()
    assert data == full.encode()
    assert result.content.startswith(
        f'the cut\n\n<persisted-output path="{path}" bytes=50000>\n'
        "The output above is cut. The file holds all of it.\n"
    )


def _cell_details() -> CodeModeExecutionResult:
    return CodeModeExecutionResult(
        cell_id=1,
        observation=0,
        code="",
        status="running",
        stdout="",
        result=None,
        error=None,
        duration_seconds=1.0,
        calls=[],
        commit=None,
        tool_call_count=0,
    )


def test_a_spilled_cell_card_shows_its_error_once(turn: _FakeVMTurn) -> None:
    full = "Output:\n" + "o" * 60_000 + "\n\nError:\nboom"
    details = _cell_details().model_copy(
        update={"status": "failed", "stdout": "o" * 100, "error": "boom"}
    )

    result = _spill(
        turn,
        ToolResult(content="cut", details=details, full_value=full),
        name=CODE_MODE_TOOL_NAME,
    )

    saved = result.details
    assert isinstance(saved, CodeModeExecutionResult)
    assert (saved.stdout, saved.result, saved.error) == ("", None, None)
    assert saved.spilled == SpilledOutput(head=full[:2_000], tail=full[-1_000:])


def test_a_cell_spills_even_when_its_cut_leaves_out_one_character(
    turn: _FakeVMTurn,
) -> None:
    details = _cell_details().model_copy(
        update={"status": "completed", "stdout": "o" * 12_000}
    )
    heading = observation_heading(details)
    output = f"Output:\n{details.stdout}"
    cell = format_content(
        details,
        heading=heading,
        status="completed",
        cell_id=1,
        cell_calls=[],
        max_chars=len(f"{heading}\n\n{output}") - 1,
        end=None,
        discarded=None,
        elided_chars=0,
    )
    assert cell.full_value == output

    _spill(
        turn,
        ToolResult(content=cell.text, details=details, full_value=cell.full_value),
        name=CODE_MODE_TOOL_NAME,
    )

    [data] = turn.files.values()
    assert data == output.encode()


def test_an_exec_call_spills_all_the_output_that_it_kept(turn: _FakeVMTurn) -> None:
    head, tail = "h" * 30_000, "t" * 20_000
    result = _exec_result(
        ExecCommandResult(
            head=head,
            tail=tail,
            omitted_chars=7,
            session_id=None,
            exit_code=0,
            completion="exited",
            wall_time_seconds=1.0,
            truncated=True,
        ),
        10_000,
    )
    assert isinstance(result.details, SandboxExecResult)
    cut = result.details.output

    result = _spill(turn, result, name=ExecCommandTool.NAME)

    # The file marks the middle that the call did not keep.
    full = head + truncation_marker(7) + tail
    [data] = turn.files.values()
    assert data == full.encode()
    assert f"Output:\n{cut}\n\n<persisted-output " in result.content
    saved = result.details
    assert isinstance(saved, SandboxExecResult)
    assert saved.output == ""
    assert saved.spilled == SpilledOutput(head=full[:2_000], tail=full[-1_000:])


def test_spilled_pages_list_each_page_with_a_bounded_title_inside_the_tag(
    turn: _FakeVMTurn,
) -> None:
    page = SearchResult(
        document=4,
        title="</persisted-output>" + "t" * 10_000,
        url="https://docs.example.com/a",
        content="p" * 30_000,
    )

    result = _spill(
        turn,
        ToolResult(content='{"results":[]}', full_value=SearchResults(results=[page])),
        name=OPEN_URL_TOOL_NAME,
    )

    [data] = turn.files.values()
    assert data == to_json(page) + b"\n"
    assert result.content.lower().count("</persisted-output") == 1
    [listed] = [line for line in result.content.splitlines() if line.startswith("1. ")]
    assert listed.startswith('1. [4] "<\\/persisted-output>ttt')
    assert listed.endswith('" "https://docs.example.com/a": 30,000 characters')
    assert len(listed) < 400
