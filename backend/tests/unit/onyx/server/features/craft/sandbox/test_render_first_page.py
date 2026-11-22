"""FirecrackerHarnessSandbox.render_first_page runs poppler and LibreOffice as
typed commands in a scratch directory, and returns None when a step fails."""

from collections.abc import Callable, Iterator
from types import SimpleNamespace
from unittest.mock import MagicMock, call
from uuid import uuid4

import grpc
import pytest

from onyx.llm.cancellation import (
    AgentCancelled,
    CancellationSignal,
    cancellation_scope,
)
from onyx.microvm.agent_client import HostAgentError
from onyx.microvm.models import (
    ExecCommand,
    ExecCompletion,
    ExecEvent,
    ExecOutput,
    ExecResult,
    ExecStarted,
    OutputStream,
)
from onyx.server.features.build.sandbox.firecracker import harness_sandbox
from onyx.server.features.build.sandbox.firecracker.harness_sandbox import (
    FirecrackerHarnessSandbox,
)
from onyx.server.features.build.sandbox.harness_base import (
    ONYX_VM_FILES_ROOT,
    RENDER_FIRST_PAGE_MAX_OUTPUT_BYTES,
    RENDER_FIRST_PAGE_ROOT,
)
from onyx.server.features.build.sandbox.models import (
    HarnessSandboxRef,
    session_workspace,
)

_STARTED = ExecStarted(execution_id="exec", pid=1, started_at=None, deadline_at=None)


def _result(completion: ExecCompletion, exit_code: int) -> ExecResult:
    return ExecResult(
        completion=completion,
        exit_code=exit_code,
        signal=0,
        finished_at=None,
        stdout_bytes=0,
        stderr_bytes=0,
    )


def _events(exit_code: int, output: bytes = b"") -> Iterator[ExecEvent]:
    yield _STARTED
    yield ExecOutput(stream=OutputStream.STDERR, offset=0, data=output)
    yield _result(ExecCompletion.EXITED, exit_code)


class _Render:
    """A render against a mock daemon. `steps` scripts the events of a
    command by its program; others exit 0. Each command takes `step_seconds`
    on the render's clock."""

    def __init__(
        self,
        monkeypatch: pytest.MonkeyPatch,
        exit_codes: dict[str, int] | None = None,
        steps: dict[str, Callable[[], Iterator[ExecEvent]]] | None = None,
        step_seconds: float = 0.0,
    ) -> None:
        self.commands: list[ExecCommand] = []
        self.reads: list[tuple[str, int]] = []
        self.now = 100.0
        self.ref = HarnessSandboxRef(
            tenant_id="tenant", sandbox_id=uuid4(), session_id=uuid4()
        )
        self.daemon = MagicMock()

        def run(command: ExecCommand) -> Iterator[ExecEvent]:
            self.commands.append(command)
            self.now += step_seconds
            program = command.argv[0]
            if steps is not None and program in steps:
                return steps[program]()
            return _events((exit_codes or {}).get(program, 0), b"bad file")

        def read_file(_ref: HarnessSandboxRef, path: str, *, max_bytes: int) -> bytes:
            self.reads.append((path, max_bytes))
            return b"jpeg"

        self.daemon.run.side_effect = run
        self.sandbox = FirecrackerHarnessSandbox(
            template="template", client_factory=MagicMock()
        )
        self.session_vm = MagicMock(return_value=(MagicMock(), self.daemon))
        monkeypatch.setattr(self.sandbox, "_session_vm", self.session_vm)
        monkeypatch.setattr(self.sandbox, "_place", MagicMock())
        monkeypatch.setattr(
            harness_sandbox, "sandbox_daemon", lambda _factory, _placed: self.daemon
        )
        monkeypatch.setattr(self.sandbox, "read_file", read_file)
        monkeypatch.setattr(
            harness_sandbox, "time", SimpleNamespace(monotonic=lambda: self.now)
        )

    def render(self, path: str, budget: float = 30.0) -> bytes | None:
        return self.sandbox.render_first_page(self.ref, path, until=self.now + budget)

    @property
    def scratch(self) -> str:
        return self.commands[0].argv[-1]

    def assert_scratch_deleted(self) -> None:
        self.daemon.delete_file.assert_called_once_with(
            session_id="", path=self.scratch, recursive=True
        )


def test_a_pdf_renders_with_pdftoppm(monkeypatch: pytest.MonkeyPatch) -> None:
    render = _Render(monkeypatch)

    assert render.render("out/Q3 report.pdf", budget=20.0) == b"jpeg"

    scratch = render.scratch
    assert scratch.startswith(f"{RENDER_FIRST_PAGE_ROOT}/")
    assert [command.argv for command in render.commands] == [
        ["mkdir", "-p", scratch],
        [
            "pdftoppm",
            "-jpeg",
            "-f",
            "1",
            "-l",
            "1",
            "-scale-to",
            "640",
            "-singlefile",
            f"{session_workspace(render.ref.session_id)}/out/Q3 report.pdf",
            f"{scratch}/page",
        ],
    ]
    assert all(
        command.session_id == str(render.ref.session_id)
        and command.deadline_seconds == 20.0
        for command in render.commands
    )
    assert render.reads == [(f"{scratch}/page.jpg", RENDER_FIRST_PAGE_MAX_OUTPUT_BYTES)]
    render.assert_scratch_deleted()


def test_a_deck_converts_to_a_pdf_with_libreoffice_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    render = _Render(monkeypatch)
    path = f"{session_workspace(render.ref.session_id)}/q3.final.PPTX"

    assert render.render(path) == b"jpeg"

    scratch = render.scratch
    _, soffice, pdftoppm = render.commands
    assert soffice.argv == [
        "soffice",
        f"-env:UserInstallation=file://{scratch}/profile",
        "--headless",
        "--convert-to",
        "pdf",
        "--outdir",
        scratch,
        path,
    ]
    assert soffice.env == {"SAL_USE_VCLPLUGIN": "svp"}
    assert pdftoppm.argv[-2:] == [f"{scratch}/q3.final.pdf", f"{scratch}/page"]


def test_a_file_under_the_onyx_directory_renders_without_a_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    render = _Render(monkeypatch)
    path = f"{ONYX_VM_FILES_ROOT}/decks/q3.pptx"

    assert render.render(path) == b"jpeg"

    _, soffice, _ = render.commands
    assert soffice.argv[-1] == path
    assert all(command.session_id == "" for command in render.commands)
    render.session_vm.assert_not_called()


@pytest.mark.parametrize("failing", ["mkdir", "soffice", "pdftoppm"])
def test_a_failed_step_returns_none_and_deletes_the_scratch_directory(
    monkeypatch: pytest.MonkeyPatch, failing: str
) -> None:
    render = _Render(monkeypatch, {failing: 1})

    assert render.render("memo.docx") is None

    assert render.commands[-1].argv[0] == failing
    assert render.reads == []
    render.assert_scratch_deleted()


def test_a_file_of_another_type_or_outside_the_session_does_not_render(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    render = _Render(monkeypatch)

    assert render.render("notes.md") is None
    assert render.render("/etc/report.pdf") is None

    assert render.commands == []


def test_a_spent_budget_runs_no_further_step(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Each step gets what is left of the budget, and none starts after it."""
    render = _Render(monkeypatch, step_seconds=6.0)

    assert render.render("memo.docx", budget=10.0) is None

    assert "the render budget is spent" in caplog.text
    assert [command.argv[0] for command in render.commands] == ["mkdir", "soffice"]
    assert [command.deadline_seconds for command in render.commands] == [10.0, 4.0]
    assert render.reads == []
    render.assert_scratch_deleted()


def test_a_broken_stream_kills_the_step_before_the_scratch_directory_goes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def broken() -> Iterator[ExecEvent]:
        yield _STARTED
        raise HostAgentError(grpc.StatusCode.UNAVAILABLE, "connection lost", None)

    render = _Render(monkeypatch, steps={"soffice": broken})

    assert render.render("memo.docx") is None

    assert render.daemon.mock_calls[-2:] == [
        call.cancel("exec"),
        call.delete_file(session_id="", path=render.scratch, recursive=True),
    ]
    assert render.reads == []


@pytest.mark.parametrize("before_start", [False, True])
def test_a_stop_kills_the_running_step_and_raises(
    monkeypatch: pytest.MonkeyPatch, before_start: bool
) -> None:
    signal = CancellationSignal()

    def stopped() -> Iterator[ExecEvent]:
        if before_start:
            signal.cancel("user")
        yield _STARTED
        signal.cancel("user")
        # The daemon ends the command once it is killed.
        yield _result(ExecCompletion.CANCELED, 0)

    render = _Render(monkeypatch, steps={"soffice": stopped})

    with cancellation_scope(signal), pytest.raises(AgentCancelled):
        render.render("memo.docx")

    assert call("exec") in render.daemon.cancel.call_args_list
    assert [command.argv[0] for command in render.commands] == ["mkdir", "soffice"]
    render.assert_scratch_deleted()


@pytest.mark.parametrize("failing", ["cancel", "delete_file"])
@pytest.mark.parametrize("before_start", [False, True])
def test_a_stop_raises_when_the_render_clean_up_fails(
    monkeypatch: pytest.MonkeyPatch, before_start: bool, failing: str
) -> None:
    """A failed kill or scratch delete is logged; the Stop still raises."""
    signal = CancellationSignal()

    def stopped() -> Iterator[ExecEvent]:
        if before_start:
            signal.cancel("user")
        yield _STARTED
        signal.cancel("user")
        yield _result(ExecCompletion.CANCELED, 0)

    render = _Render(monkeypatch, steps={"soffice": stopped})
    if failing == "cancel":
        render.daemon.cancel.side_effect = RuntimeError("the daemon is gone")
    else:
        render.daemon.delete_file.side_effect = RuntimeError("the daemon is gone")

    with cancellation_scope(signal), pytest.raises(AgentCancelled):
        render.render("memo.docx")


def test_a_daemon_error_after_a_stop_raises_the_stop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    signal = CancellationSignal()

    def broken_after_stop() -> Iterator[ExecEvent]:
        yield _STARTED
        signal.cancel("user")
        raise HostAgentError(grpc.StatusCode.UNAVAILABLE, "connection lost", None)

    render = _Render(monkeypatch, steps={"soffice": broken_after_stop})

    with cancellation_scope(signal), pytest.raises(AgentCancelled):
        render.render("memo.docx")

    render.assert_scratch_deleted()


def test_a_failed_file_lookup_after_a_stop_raises_the_stop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    signal = CancellationSignal()
    render = _Render(monkeypatch)

    def wake(_ref: HarnessSandboxRef) -> None:
        signal.cancel("user")
        raise HostAgentError(grpc.StatusCode.UNAVAILABLE, "connection lost", None)

    render.session_vm.side_effect = wake

    with cancellation_scope(signal), pytest.raises(AgentCancelled):
        render.render("memo.docx")

    assert render.commands == []
