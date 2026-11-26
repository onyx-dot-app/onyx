from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from onyx.agents.tools import ToolInvocation
from onyx.llm.cancellation import AgentCancelled, CancellationSignal
from onyx.server.features.build.sandbox.harness_base import HarnessSandboxError
from onyx.server.features.build.sandbox.models import HarnessSandboxRef
from onyx.tools.models import ToolCallException
from onyx.tools.tool_implementations.sandbox import sandbox_tools
from onyx.tools.tool_implementations.sandbox.models import (
    PUBLISH_FILES_MAX_TITLE_CHARS,
    PublishedFile,
    PublishedFiles,
)
from onyx.tools.tool_implementations.sandbox.sandbox_tools import PublishFilesTool
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
        path: str,
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
            path=path,
            size=len(content),
            mime_type=mime_type,
        )

    monkeypatch.setattr(sandbox_tools, "save_chat_artifact", save)
    turn = MagicMock(spec=SandboxTurn)
    turn.start_call.return_value = HarnessSandboxRef(
        tenant_id="tenant", sandbox_id=uuid4(), session_id=uuid4()
    )
    turn.sandbox.read_file.return_value = b"data"

    result = PublishFilesTool(turn)._run(
        ToolInvocation(
            call_id="publish",
            arguments={
                "files": [
                    {"path": "a.csv", "title": "Q3\u0000 report"},
                    {"path": "b.csv", "title": "x" * 1000},
                    {"path": "c.csv", "title": "\u0000"},
                    {"path": "d.csv", "title": "  Summary  "},
                    {"path": "e.csv", "title": " \t "},
                ]
            },
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
    thumbnails: dict[str, bytes | None] = {}

    def save(
        content: bytes,
        *,
        name: str,
        mime_type: str,
        path: str,
        thumbnail: bytes | None,
        **_: object,
    ) -> PublishedFile:
        thumbnails[name] = thumbnail
        return PublishedFile(
            file_id=name,
            name=name,
            path=path,
            size=len(content),
            mime_type=mime_type,
            thumbnail_file_id=None if thumbnail is None else f"{name}-thumbnail",
        )

    monkeypatch.setattr(sandbox_tools, "save_chat_artifact", save)
    monkeypatch.setattr(sandbox_tools, "RENDER_FIRST_PAGE_MAX_INPUT_BYTES", 4)
    turn = MagicMock(spec=SandboxTurn)
    turn.start_call.return_value = HarnessSandboxRef(
        tenant_id="tenant", sandbox_id=uuid4(), session_id=uuid4()
    )
    turn.sandbox.read_file.side_effect = lambda _ref, path, **_: (
        b"large" if path == "big.pdf" else b"data"
    )
    # The Word file does not render.
    turn.sandbox.render_first_page.side_effect = lambda _ref, path, **_: (
        None if path.endswith(".docx") else b"jpeg"
    )

    result = PublishFilesTool(turn)._run(
        ToolInvocation(
            call_id="publish",
            arguments={
                "files": [
                    {"path": name}
                    for name in (
                        "a.pdf",
                        "b.PPTX",
                        "c.docx",
                        "d.md",
                        "big.pdf",
                    )
                ]
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
    }
    rendered = [call.args[1] for call in turn.sandbox.render_first_page.call_args_list]
    assert [path.rsplit("/", 1)[-1] for path in rendered] == [
        "a.pdf",
        "b.PPTX",
        "c.docx",
    ]
    assert isinstance(result.details, PublishedFiles)
    assert [file.thumbnail_file_id for file in result.details.files] == [
        "a.pdf-thumbnail",
        "b.PPTX-thumbnail",
        None,
        None,
        None,
    ]


def test_the_renders_of_a_call_share_one_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every render gets the call's deadline, counted once the call has its
    sandbox, and the files after it publish without a render."""
    now = [100.0]
    monkeypatch.setattr(
        sandbox_tools, "time", SimpleNamespace(monotonic=lambda: now[0])
    )
    monkeypatch.setattr(sandbox_tools, "RENDER_FIRST_PAGE_BUDGET_SECONDS", 10.0)

    def save(
        content: bytes, *, name: str, mime_type: str, path: str, **_: object
    ) -> PublishedFile:
        return PublishedFile(
            file_id=name, name=name, path=path, size=len(content), mime_type=mime_type
        )

    def render(_ref: HarnessSandboxRef, _path: str, **_: object) -> bytes:
        now[0] += 6.0
        return b"jpeg"

    monkeypatch.setattr(sandbox_tools, "save_chat_artifact", save)
    ref = HarnessSandboxRef(tenant_id="tenant", sandbox_id=uuid4(), session_id=uuid4())

    def start_call() -> HarnessSandboxRef:
        # A wake and a skills sync take time before the call has its sandbox
        now[0] += 25.0
        return ref

    turn = MagicMock(spec=SandboxTurn)
    turn.start_call.side_effect = start_call
    turn.sandbox.read_file.return_value = b"data"
    turn.sandbox.render_first_page.side_effect = render

    PublishFilesTool(turn)._run(
        ToolInvocation(
            call_id="publish",
            arguments={
                "files": [{"path": name} for name in ("a.pdf", "b.pptx", "c.docx")]
            },
            cancellation=CancellationSignal(),
            update=lambda _progress: None,
        ),
        MagicMock(),
    )

    renders = turn.sandbox.render_first_page.call_args_list
    assert [call.args[1].rsplit("/", 1)[-1] for call in renders] == [
        "a.pdf",
        "b.pptx",
    ]
    assert [call.kwargs["until"] for call in renders] == [135.0, 135.0]


@pytest.mark.parametrize("stopped", [True, False])
def test_a_failed_clean_up_keeps_the_stop_or_the_error_of_the_call(
    monkeypatch: pytest.MonkeyPatch, stopped: bool
) -> None:
    """The first file saves; then a Stop or a read error fails the call, and
    the clean-up of the saved file fails too."""
    signal = CancellationSignal()
    cleaned: list[list[str]] = []

    def save(
        content: bytes, *, name: str, mime_type: str, path: str, **_: object
    ) -> PublishedFile:
        if stopped:
            signal.cancel("user")
        return PublishedFile(
            file_id=name, name=name, path=path, size=len(content), mime_type=mime_type
        )

    def clean_up(published: list[PublishedFile]) -> None:
        cleaned.append([file.file_id for file in published])
        raise RuntimeError("the database is gone")

    def read_file(_ref: HarnessSandboxRef, path: str, **_: object) -> bytes:
        if path == "b.md":
            raise HarnessSandboxError("b.md is not a regular file")
        return b"data"

    monkeypatch.setattr(sandbox_tools, "save_chat_artifact", save)
    monkeypatch.setattr(sandbox_tools, "delete_unpublished_chat_artifacts", clean_up)
    turn = MagicMock(spec=SandboxTurn)
    turn.start_call.return_value = HarnessSandboxRef(
        tenant_id="tenant", sandbox_id=uuid4(), session_id=uuid4()
    )
    turn.sandbox.read_file.side_effect = read_file

    with pytest.raises(AgentCancelled if stopped else ToolCallException):
        PublishFilesTool(turn)._run(
            ToolInvocation(
                call_id="publish",
                arguments={"files": [{"path": "a.md"}, {"path": "b.md"}]},
                cancellation=signal,
                update=lambda _progress: None,
            ),
            MagicMock(),
        )

    assert cleaned == [["a.md"]]
