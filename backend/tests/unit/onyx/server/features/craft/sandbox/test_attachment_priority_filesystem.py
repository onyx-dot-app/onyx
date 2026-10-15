import subprocess
from pathlib import Path
from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest

from onyx.server.features.build.sandbox import manager as sandbox_manager
from onyx.server.features.build.sandbox.manager import SandboxManager
from onyx.server.features.build.sandbox.util.agent_instructions import (
    ATTACHMENTS_SECTION_CONTENT,
)


@pytest.fixture
def local_manager(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[SandboxManager, Path, UUID]:
    workspace = tmp_path / "workspace"
    session_id = uuid4()
    session_path = workspace / "sessions" / str(session_id)
    session_path.mkdir(parents=True)

    def run_script(_self: SandboxManager, _sandbox_id: UUID, script: str) -> str:
        result = subprocess.run(
            ["/bin/bash", "-s"],
            input=script.replace("/workspace", str(workspace)),
            text=True,
            capture_output=True,
        )
        assert result.returncode == 0, result.stderr
        return result.stdout

    monkeypatch.setattr(SandboxManager, "_run_script", run_script)
    return object.__new__(SandboxManager), session_path, session_id


@pytest.mark.parametrize(
    "before,after",
    [
        ("# Agent\n\n", "## Connectable apps\nApps.\n"),
        (
            "# Agent\n\nInline ## Connectable apps mention.\n\n",
            "## Connectable apps\nApps.\n",
        ),
        (
            "# Agent\n\n",
            "## Connectable apps\nFirst.\n\n## Connectable apps\nSecond.\n",
        ),
        ("# Agent\n\nInline ## Connectable apps mention.\n", ""),
    ],
)
def test_attachment_section_uses_first_heading_or_eof_and_is_idempotent(
    local_manager: tuple[SandboxManager, Path, UUID], before: str, after: str
) -> None:
    manager, session_path, session_id = local_manager
    agents_md = session_path / "AGENTS.md"
    agents_md.write_text(before + after)
    expected = (
        before + ATTACHMENTS_SECTION_CONTENT + "\n\n" + after
        if after
        else before + "\n\n" + ATTACHMENTS_SECTION_CONTENT
    )

    manager._ensure_agents_md_attachments_section(uuid4(), session_id)
    assert agents_md.read_text() == expected

    manager._ensure_agents_md_attachments_section(uuid4(), session_id)
    assert agents_md.read_text() == expected


def test_attachment_section_leaves_missing_document_absent(
    local_manager: tuple[SandboxManager, Path, UUID],
) -> None:
    manager, session_path, session_id = local_manager

    manager._ensure_agents_md_attachments_section(uuid4(), session_id)

    assert list(session_path.iterdir()) == []


@pytest.mark.parametrize("has_attachments", [False, True])
def test_regeneration_preserves_attachment_priority_when_files_exist(
    local_manager: tuple[SandboxManager, Path, UUID],
    monkeypatch: pytest.MonkeyPatch,
    has_attachments: bool,
) -> None:
    manager, session_path, session_id = local_manager
    before = "# Agent\n\n"
    after = "## Connectable apps\nApps.\n"
    monkeypatch.setattr(
        manager, "_load_agent_instructions", Mock(return_value=before + after)
    )
    monkeypatch.setattr(
        sandbox_manager, "get_opencode_disabled_tools", Mock(return_value=[])
    )
    monkeypatch.setattr(
        sandbox_manager,
        "build_opencode_dependency_setup_command",
        Mock(return_value=":"),
    )
    if has_attachments:
        attachments = session_path / "attachments"
        attachments.mkdir()
        (attachments / "first.txt").write_text("hello")
    expected = (
        before + ATTACHMENTS_SECTION_CONTENT + "\n\n" + after
        if has_attachments
        else before + after
    )

    for _ in range(2):
        manager.regenerate_session_config(
            sandbox_id=uuid4(),
            session_id=session_id,
            agent_provider=None,
            agent_model=None,
            connectable_apps_section="Apps.",
        )
        assert (session_path / "AGENTS.md").read_text() == expected
