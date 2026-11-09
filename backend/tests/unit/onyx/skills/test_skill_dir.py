"""Skill folder paths: the shared model text and the OpenCode version it copies."""

import re
from pathlib import Path

import pytest

from onyx.skills import push
from onyx.skills.rendering import render_skill_for_model, resolve_skill_dir_placeholder

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


@pytest.mark.parametrize("excess", [0, 1])
def test_expansion_limit_skips_the_whole_skill_only_above_the_limit(
    monkeypatch: pytest.MonkeyPatch, excess: int
) -> None:
    path = "report/SKILL.md"
    body = "${CLAUDE_SKILL_DIR}/café\n".encode()
    files = {
        path: body,
        "report/data.txt": b"supporting data",
        "report-other/SKILL.md": b"other instructions",
    }
    expected = f"{_SKILL_DIR}/café\n".encode()
    monkeypatch.setattr(
        push, "DEFAULT_PER_FILE_MAX_BYTES", len(expected) - excess, raising=False
    )

    push._resolve_skill_dirs(files, ["report", "report-other"])

    if excess:
        assert files == {"report-other/SKILL.md": b"other instructions"}
    else:
        assert files[path] == expected
        assert files["report/data.txt"] == b"supporting data"


def test_existing_files_and_combined_library_are_not_readmitted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    files = {
        "first/SKILL.md": b"old instructions" * 100,
        "first/data.txt": b"a" * 2000,
        "second/SKILL.md": b"other instructions" * 100,
        "second/data.txt": b"b" * 2000,
    }
    original = dict(files)
    monkeypatch.setattr(push, "DEFAULT_PER_FILE_MAX_BYTES", 100, raising=False)
    monkeypatch.setattr(push, "DEFAULT_TOTAL_MAX_BYTES", 150, raising=False)

    push._resolve_skill_dirs(files, ["first", "second"])

    assert files == original
