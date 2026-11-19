from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from onyx.agents.tools import ToolInvocation
from onyx.llm.cancellation import CancellationSignal
from onyx.server.features.build.sandbox.models import HarnessSandboxRef
from onyx.tools.tool_implementations.sandbox import sandbox_tools
from onyx.tools.tool_implementations.sandbox.models import (
    PUBLISH_FILES_MAX_TITLE_CHARS,
    PublishedFiles,
)
from onyx.tools.tool_implementations.sandbox.sandbox_tools import PublishFilesTool
from onyx.tools.tool_implementations.sandbox.turn import SandboxTurn


def test_a_title_is_stored_trimmed_without_nul_and_within_its_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    saved_titles: list[str | None] = []

    def save(_content: bytes, *, published_title: str | None, **_: object) -> str:
        saved_titles.append(published_title)
        return f"file-{len(saved_titles)}"

    monkeypatch.setattr(sandbox_tools, "save_chat_output_file", save)
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
    assert [file.title for file in result.details.files] == expected
