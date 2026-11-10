"""Skill folder paths: the shared model text and the OpenCode version it copies."""

import re
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest.mock import MagicMock

import pytest
from sqlalchemy.orm import Session

from onyx.db.models import User
from onyx.file_store.file_store import FileStore
from onyx.skills import push
from onyx.skills.rendering import render_skill_for_model, resolve_skill_dir_placeholder
from tests.unit.onyx.skills.test_push import _assemble, _skill

_SANDBOX_DOCKERFILE = (
    Path(__file__).resolve().parents[4]
    / "onyx/server/features/build/sandbox/image/Dockerfile"
)
_OPENCODE_PIN = re.compile(r"^ARG OPENCODE_VERSION=(?P<version>\S+)$", re.MULTILINE)

# The version whose skill tool was checked: it ends a loaded skill with the
# base folder line and the relative-path rule that render_skill_for_model
# copies, and it does not replace ${CLAUDE_SKILL_DIR}.
_VERIFIED_OPENCODE_VERSION = "1.18.19"

_SKILL_DIR = "/workspace/managed/skills/report"


def test_sandbox_opencode_pin_matches_verified_skill_tool() -> None:
    match = _OPENCODE_PIN.search(_SANDBOX_DOCKERFILE.read_text())

    assert match is not None
    assert match.group("version") == _VERIFIED_OPENCODE_VERSION, (
        "The sandbox OpenCode pin changed. Read packages/opencode/src/tool/skill.ts "
        "at the new version. Confirm it still adds the base folder line and the "
        "relative-path rule in onyx/skills/rendering.py, and that it does not "
        "replace ${CLAUDE_SKILL_DIR}. Then update _VERIFIED_OPENCODE_VERSION."
    )


def test_resolve_replaces_every_placeholder() -> None:
    skill_md = "Run ${CLAUDE_SKILL_DIR}/scripts/x.py on ${CLAUDE_SKILL_DIR}/data.\n"

    assert resolve_skill_dir_placeholder(skill_md, _SKILL_DIR) == (
        f"Run {_SKILL_DIR}/scripts/x.py on {_SKILL_DIR}/data.\n"
    )


@pytest.mark.parametrize("path", ["report/SKILL.md", "report/references/SKILL.md"])
@pytest.mark.parametrize("text", ["café", "${CLAUDE_SKILL_DIR}/café\n" * 100])
def test_resolved_size_matches_encoded_output(path: str, text: str) -> None:
    expected = (
        resolve_skill_dir_placeholder(text, _SKILL_DIR)
        if path == "report/SKILL.md"
        else text
    )
    assert push._resolved_file_size(path, text.encode()) == len(expected.encode())


def test_render_for_model_matches_opencode_skill_tool() -> None:
    rendered = render_skill_for_model(
        "Run ${CLAUDE_SKILL_DIR}/scripts/x.py, then scripts/y.py.\n", _SKILL_DIR
    )

    assert rendered == "\n".join(
        [
            f"Run {_SKILL_DIR}/scripts/x.py, then scripts/y.py.",
            "",
            f"Base directory for this skill: {_SKILL_DIR}",
            "Relative paths in this skill (e.g., scripts/, reference/) are "
            "relative to this base directory.",
        ]
    )


@pytest.mark.parametrize("limit", ["file", "receiver", "total"])
@pytest.mark.parametrize("excess", [0, 1])
def test_expansion_admission_keeps_other_skills(
    monkeypatch: pytest.MonkeyPatch, limit: str, excess: int
) -> None:
    body = b"${CLAUDE_SKILL_DIR}/run.py"
    expanded = b"/workspace/managed/skills/report/run.py"

    def render(skill: object, *_args: object) -> dict[str, bytes]:
        if skill is report:
            return {"report/SKILL.md": body, "report/run.py": b"script"}
        return {"healthy/SKILL.md": b"healthy"}

    report = _skill(name="report", is_valid=True)
    healthy = _skill(name="healthy", is_valid=True)
    monkeypatch.setattr(push, "_render_candidate", render)
    monkeypatch.setattr(
        push, "get_default_file_store", lambda: MagicMock(spec=FileStore)
    )
    monkeypatch.setattr(push, "persist_skill_validity", MagicMock())
    monkeypatch.setattr(push, "SKILL_RUNTIME_MIN_FILE_CHARGE_BYTES", 1)
    if limit == "total":
        monkeypatch.setattr(
            push,
            "SKILL_RUNTIME_MAX_BYTES",
            len(expanded) + len(b"scripthealthy") - excess,
        )
        skills = [healthy, report]
    else:
        name = (
            "PUSH_MAX_FILE_BYTES"
            if limit == "receiver"
            else "DEFAULT_PER_FILE_MAX_BYTES"
        )
        monkeypatch.setattr(push, name, len(expanded) - excess)
        skills = [report, healthy]
    files = _assemble(skills, cast(User, SimpleNamespace()), MagicMock(spec=Session))
    assert files["healthy/SKILL.md"] == b"healthy"
    if excess:
        assert set(files) == {"healthy/SKILL.md"}
    else:
        assert files["report/SKILL.md"] == expanded
        assert files["report/run.py"] == b"script"
