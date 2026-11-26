"""FirecrackerHarnessSandbox.render_preview runs poppler and LibreOffice as
typed commands in a scratch directory. Against a mock daemon: the commands,
the budget clock, and the kill and the scratch delete after a Stop, a broken
stream or a failed clean-up."""

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
    RENDER_PREVIEW_MAX_OUTPUT_BYTES,
    RENDER_PREVIEW_MAX_PDF_BYTES,
    RENDER_PREVIEW_ROOT,
    RenderBudgetSpentError,
    SandboxPathError,
)
from onyx.server.features.build.sandbox.models import (
    HarnessSandboxKey,
    HarnessSandboxRef,
    RenderedPreview,
    RenderFileBytes,
    RenderSessionFile,
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
    command by its program; others exit 0. Each command and read takes
    `step_seconds` on the render's clock. A read raises `read_error`."""

    def __init__(
        self,
        monkeypatch: pytest.MonkeyPatch,
        exit_codes: dict[str, int] | None = None,
        steps: dict[str, Callable[[], Iterator[ExecEvent]]] | None = None,
        step_seconds: float = 0.0,
        read_error: Exception | None = None,
    ) -> None:
        self.commands: list[ExecCommand] = []
        self.reads: list[tuple[str, int]] = []
        self.read_timeouts: list[float | None] = []
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

        def read(
            _daemon: object,
            _session_id: str,
            target: str,
            *,
            max_bytes: int,
            timeout_seconds: float | None = None,
            **_: object,
        ) -> bytes:
            self.reads.append((target, max_bytes))
            self.read_timeouts.append(timeout_seconds)
            self.now += step_seconds
            if read_error is not None:
                raise read_error
            return b"pdf" if target.endswith(".pdf") else b"jpeg"

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
        monkeypatch.setattr(harness_sandbox, "_read", read)
        monkeypatch.setattr(
            harness_sandbox, "time", SimpleNamespace(monotonic=lambda: self.now)
        )

    def render(
        self,
        path: str | RenderFileBytes,
        budget: float = 30.0,
        first_page: bool = True,
    ) -> RenderedPreview | None:
        return self.sandbox.render_preview(
            RenderSessionFile(ref=self.ref, path=path)
            if isinstance(path, str)
            else path,
            first_page=first_page,
            budget_seconds=budget,
        )

    @property
    def scratch(self) -> str:
        return self.commands[0].argv[-1]

    def assert_scratch_deleted(self) -> None:
        self.daemon.delete_file.assert_called_once_with(
            session_id="", path=self.scratch, recursive=True
        )


def test_a_pdf_renders_with_pdftoppm(monkeypatch: pytest.MonkeyPatch) -> None:
    render = _Render(monkeypatch)

    assert render.render("out/Q3 report.pdf", budget=20.0) == RenderedPreview(
        first_page=b"jpeg", pdf=None
    )

    scratch = render.scratch
    assert scratch.startswith(f"{RENDER_PREVIEW_ROOT}/")
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
    assert render.reads == [(f"{scratch}/page.jpg", RENDER_PREVIEW_MAX_OUTPUT_BYTES)]
    render.assert_scratch_deleted()


def test_a_deck_converts_to_a_pdf_with_libreoffice_and_returns_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    render = _Render(monkeypatch)
    path = f"{session_workspace(render.ref.session_id)}/q3.final.PPTX"

    assert render.render(path) == RenderedPreview(first_page=b"jpeg", pdf=b"pdf")

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
    assert render.reads == [
        (f"{scratch}/q3.final.pdf", RENDER_PREVIEW_MAX_PDF_BYTES),
        (f"{scratch}/page.jpg", RENDER_PREVIEW_MAX_OUTPUT_BYTES),
    ]
    render.assert_scratch_deleted()


def test_a_file_under_the_onyx_directory_renders_without_a_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    render = _Render(monkeypatch)
    path = f"{ONYX_VM_FILES_ROOT}/decks/q3.pptx"

    assert render.render(path) is not None

    _, soffice, _ = render.commands
    assert soffice.argv[-1] == path
    assert all(command.session_id == "" for command in render.commands)
    render.session_vm.assert_not_called()


def test_a_first_page_that_fails_keeps_the_pdf(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    render = _Render(monkeypatch, {"pdftoppm": 1})

    assert render.render("memo.docx") == RenderedPreview(first_page=None, pdf=b"pdf")

    render.assert_scratch_deleted()


def test_a_file_of_another_type_does_not_render(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    render = _Render(monkeypatch)

    assert render.render("notes.md") is None

    assert render.commands == []


def test_a_file_outside_the_session_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    render = _Render(monkeypatch)

    with pytest.raises(SandboxPathError):
        render.render("/etc/report.pdf")

    assert render.commands == []


def test_a_spent_budget_raises_and_runs_no_further_step(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Each step gets what is left of the budget, and none starts after it."""
    render = _Render(monkeypatch, step_seconds=6.0)

    with pytest.raises(RenderBudgetSpentError):
        render.render("memo.docx", budget=10.0)

    assert [command.argv[0] for command in render.commands] == ["mkdir", "soffice"]
    assert [command.deadline_seconds for command in render.commands] == [10.0, 4.0]
    render.assert_scratch_deleted()


def test_each_output_read_gets_what_is_left_of_the_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stalled transfer of the PDF or the first page stops with the
    budget."""
    render = _Render(monkeypatch, step_seconds=3.0)

    assert render.render("deck.pptx", budget=30.0) is not None

    assert [command.deadline_seconds for command in render.commands] == [
        30.0,
        27.0,
        21.0,
    ]
    assert render.read_timeouts == [24.0, 18.0]


@pytest.mark.parametrize("case", ["read_past_the_budget", "no_time_left"])
def test_an_output_read_without_budget_raises_the_spent_budget(
    monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    """A read that the budget's deadline stops, or a read with no time left
    after LibreOffice, raises the spent budget, not a sandbox fault."""
    if case == "read_past_the_budget":
        render = _Render(
            monkeypatch,
            read_error=HostAgentError(
                grpc.StatusCode.DEADLINE_EXCEEDED, "deadline", None
            ),
        )
    else:

        def until_the_budget_ends() -> Iterator[ExecEvent]:
            render.now += 30.0
            yield from _events(0)

        render = _Render(monkeypatch, steps={"soffice": until_the_budget_ends})

    with pytest.raises(RenderBudgetSpentError):
        render.render("deck.pptx", budget=30.0)

    assert len(render.reads) == (1 if case == "read_past_the_budget" else 0)
    render.assert_scratch_deleted()


@pytest.mark.parametrize("source", ["session", "bytes"])
def test_the_budget_starts_once_the_vm_runs(
    monkeypatch: pytest.MonkeyPatch, source: str
) -> None:
    """A wake of the VM does not spend the render budget."""
    render = _Render(monkeypatch)

    def wake(*_: object) -> object:
        render.now += 50.0
        return MagicMock() if source == "bytes" else (MagicMock(), render.daemon)

    if source == "bytes":
        monkeypatch.setattr(render.sandbox, "_place", wake)
        path: str | RenderFileBytes = RenderFileBytes(
            sandbox=HarnessSandboxKey(tenant_id="tenant", sandbox_id=uuid4()),
            suffix=".pptx",
            data=b"deck",
        )
    else:
        render.session_vm.side_effect = wake
        path = "deck.pptx"

    assert render.render(path, budget=30.0) is not None

    assert render.commands[0].deadline_seconds == 30.0


def test_a_broken_stream_kills_the_step_before_the_scratch_directory_goes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A sandbox fault raises, so the caller can retry."""

    def broken() -> Iterator[ExecEvent]:
        yield _STARTED
        raise HostAgentError(grpc.StatusCode.UNAVAILABLE, "connection lost", None)

    render = _Render(monkeypatch, steps={"soffice": broken})

    with pytest.raises(HostAgentError):
        render.render("memo.docx")

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
