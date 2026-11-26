from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import grpc
import pytest

from onyx.agents.tools import ToolInvocation
from onyx.llm.cancellation import AgentCancelled, CancellationSignal
from onyx.llm.model_capabilities import ToolFamily
from onyx.microvm.agent_client import HostAgentError
from onyx.server.features.build.sandbox.harness_base import HarnessSandboxError
from onyx.server.features.build.sandbox.models import (
    HarnessSandboxRef,
    RenderedPreview,
    RenderSessionFile,
)
from onyx.tools.models import ToolCallException
from onyx.tools.tool_implementations.sandbox import artifact_operations
from onyx.tools.tool_implementations.sandbox.models import (
    PUBLISH_FILES_MAX_TITLE_CHARS,
    ArtifactAtPath,
    PublishedFile,
    PublishedFiles,
)
from onyx.tools.tool_implementations.sandbox.sandbox_tools import (
    LibraryCreateLibraryFileTool,
)
from onyx.tools.tool_implementations.sandbox.shapes import SHELL_SHAPES
from onyx.tools.tool_implementations.sandbox.turn import SandboxTurn


def test_a_title_is_stored_trimmed_without_nul_and_within_its_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    saved_titles: list[str | None] = []

    def save(
        content: bytes,
        *,
        name: str,
        mime_type: str,
        target: ArtifactAtPath,
        title: str | None,
        **_: object,
    ) -> PublishedFile:
        saved_titles.append(title)
        return PublishedFile(
            file_id=f"file-{len(saved_titles)}",
            artifact_id=uuid4(),
            version=1,
            name=name,
            title=title,
            path=target.path,
            size=len(content),
            mime_type=mime_type,
        )

    monkeypatch.setattr(artifact_operations, "save_chat_artifact", save)
    turn = MagicMock(spec=SandboxTurn)
    turn.shell = SHELL_SHAPES[ToolFamily.OPENAI]
    turn.start_call.return_value = HarnessSandboxRef(
        tenant_id="tenant", sandbox_id=uuid4(), session_id=uuid4()
    )
    turn.sandbox.read_file.return_value = b"data"

    for path, title in (
        ("a.csv", "Q3\u0000 report"),
        ("b.csv", "x" * 1000),
        ("c.csv", "\u0000"),
        ("d.csv", "  Summary  "),
        ("e.csv", " \t "),
    ):
        result = LibraryCreateLibraryFileTool(turn)._run(
            ToolInvocation(
                call_id="publish",
                arguments={"file": path, "title": title},
                cancellation=CancellationSignal(),
                update=lambda _progress: None,
            ),
            MagicMock(),
        )

    expected = [
        "Q3 report",
        "x" * PUBLISH_FILES_MAX_TITLE_CHARS,
        None,
        "Summary",
        None,
    ]
    assert saved_titles == expected
    assert isinstance(result.details, PublishedFiles)


def test_a_pdf_or_office_file_is_saved_with_its_rendered_first_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A file whose render fails or raises still publishes, without a
    thumbnail."""
    thumbnails: dict[str, bytes | None] = {}

    def save(
        content: bytes,
        *,
        name: str,
        mime_type: str,
        target: ArtifactAtPath,
        thumbnail: bytes | None,
        **_: object,
    ) -> PublishedFile:
        thumbnails[name] = thumbnail
        return PublishedFile(
            file_id=name,
            name=name,
            path=target.path,
            size=len(content),
            mime_type=mime_type,
            thumbnail_file_id=None if thumbnail is None else f"{name}-thumbnail",
        )

    def render(source: RenderSessionFile, **_: object) -> RenderedPreview | None:
        if source.path.endswith(".docx"):
            return None
        if source.path.endswith("e.pptx"):
            raise HostAgentError(grpc.StatusCode.UNAVAILABLE, "connection lost", None)
        return RenderedPreview(first_page=b"jpeg", pdf=None)

    monkeypatch.setattr(artifact_operations, "save_chat_artifact", save)
    monkeypatch.setattr(artifact_operations, "RENDER_PREVIEW_MAX_INPUT_BYTES", 4)
    turn = MagicMock(spec=SandboxTurn)
    turn.shell = SHELL_SHAPES[ToolFamily.OPENAI]
    turn.start_call.return_value = HarnessSandboxRef(
        tenant_id="tenant", sandbox_id=uuid4(), session_id=uuid4()
    )
    turn.sandbox.read_file.side_effect = lambda _ref, path, **_: (
        b"large" if path == "big.pdf" else b"data"
    )
    turn.sandbox.render_preview.side_effect = render

    result = LibraryCreateLibraryFileTool(turn)._run(
        ToolInvocation(
            call_id="publish",
            arguments={
                "files": ["a.pdf", "b.PPTX", "c.docx", "d.md", "big.pdf", "e.pptx"]
            },
            cancellation=CancellationSignal(),
            update=lambda _progress: None,
        ),
        MagicMock(),
    )

    assert thumbnails == {
        "a.pdf": b"jpeg",
        "b.PPTX": b"jpeg",
        "c.docx": None,
        "d.md": None,
        "big.pdf": None,
        "e.pptx": None,
    }
    renders = turn.sandbox.render_preview.call_args_list
    assert [call.args[0].path.rsplit("/", 1)[-1] for call in renders] == [
        "a.pdf",
        "b.PPTX",
        "c.docx",
        "e.pptx",
    ]
    assert all(call.kwargs["first_page"] for call in renders)
    assert isinstance(result.details, PublishedFiles)
    assert [file.thumbnail_file_id for file in result.details.files] == [
        "a.pdf-thumbnail",
        "b.PPTX-thumbnail",
        None,
        None,
        None,
        None,
    ]


def test_a_stop_during_a_render_stops_the_publish(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    saved: list[str] = []

    def save(_content: bytes, *, name: str, **_: object) -> PublishedFile:
        saved.append(name)
        raise AssertionError("a stopped publish saves nothing")

    def render(_source: RenderSessionFile, **_: object) -> RenderedPreview:
        raise AgentCancelled("user")

    monkeypatch.setattr(artifact_operations, "save_chat_artifact", save)
    turn = MagicMock(spec=SandboxTurn)
    turn.shell = SHELL_SHAPES[ToolFamily.OPENAI]
    turn.start_call.return_value = HarnessSandboxRef(
        tenant_id="tenant", sandbox_id=uuid4(), session_id=uuid4()
    )
    turn.sandbox.read_file.return_value = b"data"
    turn.sandbox.render_preview.side_effect = render

    with pytest.raises(AgentCancelled):
        LibraryCreateLibraryFileTool(turn)._run(
            ToolInvocation(
                call_id="publish",
                arguments={"files": ["a.pptx"]},
                cancellation=CancellationSignal(),
                update=lambda _progress: None,
            ),
            MagicMock(),
        )

    assert saved == []


def test_the_renders_of_a_call_share_one_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The renders of a call share one budget, counted from the first read,
    which wakes the VM; the files after it publish without a render."""
    now = [100.0]
    monkeypatch.setattr(
        artifact_operations, "time", SimpleNamespace(monotonic=lambda: now[0])
    )
    monkeypatch.setattr(artifact_operations, "RENDER_PREVIEW_BUDGET_SECONDS", 10.0)

    def save(
        content: bytes,
        *,
        name: str,
        mime_type: str,
        target: ArtifactAtPath,
        **_: object,
    ) -> PublishedFile:
        return PublishedFile(
            file_id=name,
            name=name,
            path=target.path,
            size=len(content),
            mime_type=mime_type,
        )

    def render(_source: RenderSessionFile, **_: object) -> RenderedPreview:
        now[0] += 6.0
        return RenderedPreview(first_page=b"jpeg", pdf=None)

    monkeypatch.setattr(artifact_operations, "save_chat_artifact", save)
    ref = HarnessSandboxRef(tenant_id="tenant", sandbox_id=uuid4(), session_id=uuid4())
    reads: list[str] = []

    def read_file(_ref: HarnessSandboxRef, path: str, **_: object) -> bytes:
        if not reads:
            # The first read wakes the VM.
            now[0] += 25.0
        reads.append(path)
        return b"data"

    turn = MagicMock(spec=SandboxTurn)
    turn.shell = SHELL_SHAPES[ToolFamily.OPENAI]
    turn.start_call.return_value = ref
    turn.sandbox.read_file.side_effect = read_file
    turn.sandbox.render_preview.side_effect = render

    LibraryCreateLibraryFileTool(turn)._run(
        ToolInvocation(
            call_id="publish",
            arguments={"files": ["a.pdf", "b.pptx", "c.docx"]},
            cancellation=CancellationSignal(),
            update=lambda _progress: None,
        ),
        MagicMock(),
    )

    renders = turn.sandbox.render_preview.call_args_list
    assert [call.args[0].path.rsplit("/", 1)[-1] for call in renders] == [
        "a.pdf",
        "b.pptx",
    ]
    assert [call.kwargs["budget_seconds"] for call in renders] == [10.0, 4.0]


@pytest.mark.parametrize("stopped", [True, False])
def test_a_failed_clean_up_keeps_the_stop_or_the_error_of_the_call(
    monkeypatch: pytest.MonkeyPatch, stopped: bool
) -> None:
    """The first file saves; then a Stop or a read error fails the call, and
    the clean-up of the saved file fails too."""
    signal = CancellationSignal()
    cleaned: list[list[str]] = []

    def save(
        content: bytes,
        *,
        name: str,
        mime_type: str,
        target: ArtifactAtPath,
        **_: object,
    ) -> PublishedFile:
        if stopped:
            signal.cancel("user")
        return PublishedFile(
            file_id=name,
            name=name,
            path=target.path,
            size=len(content),
            mime_type=mime_type,
        )

    def clean_up(published: list[PublishedFile]) -> None:
        cleaned.append([file.file_id for file in published])
        raise RuntimeError("the database is gone")

    def read_file(_ref: HarnessSandboxRef, path: str, **_: object) -> bytes:
        if path == "b.md":
            raise HarnessSandboxError("b.md is not a regular file")
        return b"data"

    monkeypatch.setattr(artifact_operations, "save_chat_artifact", save)
    monkeypatch.setattr(
        artifact_operations, "delete_unpublished_chat_artifacts", clean_up
    )
    turn = MagicMock(spec=SandboxTurn)
    turn.shell = SHELL_SHAPES[ToolFamily.OPENAI]
    turn.start_call.return_value = HarnessSandboxRef(
        tenant_id="tenant", sandbox_id=uuid4(), session_id=uuid4()
    )
    turn.sandbox.read_file.side_effect = read_file

    with pytest.raises(AgentCancelled if stopped else ToolCallException):
        LibraryCreateLibraryFileTool(turn)._run(
            ToolInvocation(
                call_id="publish",
                arguments={"files": ["a.md", "b.md"]},
                cancellation=signal,
                update=lambda _progress: None,
            ),
            MagicMock(),
        )

    assert cleaned == [["a.md"]]


def test_an_unexpected_save_failure_is_a_tool_error_and_cleans_up(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A publish maps errors as every artifact operation does: the details go
    to the log, and the model gets a fixed message. The file saved before the
    failure is cleaned up."""
    cleaned: list[list[str]] = []

    def save(
        content: bytes,
        *,
        name: str,
        mime_type: str,
        target: ArtifactAtPath,
        **_: object,
    ) -> PublishedFile:
        if name == "b.md":
            raise RuntimeError("the database is gone")
        return PublishedFile(
            file_id=name,
            name=name,
            path=target.path,
            size=len(content),
            mime_type=mime_type,
        )

    monkeypatch.setattr(artifact_operations, "save_chat_artifact", save)
    monkeypatch.setattr(
        artifact_operations,
        "delete_unpublished_chat_artifacts",
        lambda published: cleaned.append([file.file_id for file in published]),
    )
    turn = MagicMock(spec=SandboxTurn)
    turn.shell = SHELL_SHAPES[ToolFamily.OPENAI]
    turn.start_call.return_value = HarnessSandboxRef(
        tenant_id="tenant", sandbox_id=uuid4(), session_id=uuid4()
    )
    turn.sandbox.read_file.return_value = b"data"

    with pytest.raises(ToolCallException, match="The publish failed; try again"):
        LibraryCreateLibraryFileTool(turn)._run(
            ToolInvocation(
                call_id="publish",
                arguments={"files": ["a.md", "b.md"]},
                cancellation=CancellationSignal(),
                update=lambda _progress: None,
            ),
            MagicMock(),
        )
    assert cleaned == [["a.md"]]
