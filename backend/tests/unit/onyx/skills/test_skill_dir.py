"""Skill folder paths in the sandbox and the OpenCode version they rely on."""

import re
from pathlib import Path

import pytest

from onyx.skills import push
from onyx.skills.rendering import resolve_skill_dir_placeholder

_SANDBOX_DOCKERFILE = (
    Path(__file__).resolve().parents[4]
    / "onyx/server/features/build/sandbox/image/Dockerfile"
)
_OPENCODE_PIN = re.compile(r"^ARG OPENCODE_VERSION=(?P<version>\S+)$", re.MULTILINE)

# The version whose skill tool was checked: it ends a loaded skill with the
# base folder line and the relative-path rule, and it does not replace
# ${CLAUDE_SKILL_DIR}.
_VERIFIED_OPENCODE_VERSION = "1.18.19"

_SKILL_DIR = "/workspace/managed/skills/report"


def test_sandbox_opencode_pin_matches_verified_skill_tool() -> None:
    match = _OPENCODE_PIN.search(_SANDBOX_DOCKERFILE.read_text())

    assert match is not None
    assert match.group("version") == _VERIFIED_OPENCODE_VERSION, (
        "The sandbox OpenCode pin changed. Read packages/opencode/src/tool/skill.ts "
        "at the new version. Confirm it still adds the base folder line and the "
        "relative-path rule, and that it does not replace ${CLAUDE_SKILL_DIR}. "
        "Then update _VERIFIED_OPENCODE_VERSION."
    )


def test_resolve_replaces_every_placeholder() -> None:
    skill_md = "Run ${CLAUDE_SKILL_DIR}/scripts/x.py on ${CLAUDE_SKILL_DIR}/data.\n"

    assert resolve_skill_dir_placeholder(skill_md, _SKILL_DIR) == (
        f"Run {_SKILL_DIR}/scripts/x.py on {_SKILL_DIR}/data.\n"
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


def test_skills_without_placeholder_keep_files_over_the_file_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    files = {
        "first/SKILL.md": b"old instructions" * 100,
        "first/data.txt": b"a" * 2000,
        "second/SKILL.md": b"other instructions" * 100,
        "second/data.txt": b"b" * 2000,
    }
    original = dict(files)
    monkeypatch.setattr(push, "DEFAULT_PER_FILE_MAX_BYTES", 100, raising=True)

    push._resolve_skill_dirs(files, ["first", "second"])

    assert files == original


def test_expansion_respects_receiver_file_limit_when_upload_limit_is_higher(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = b"${CLAUDE_SKILL_DIR}/run.py"
    files = {
        "report/SKILL.md": body,
        "report/run.py": b"script",
        "report-other/SKILL.md": b"healthy",
    }
    expected = f"{_SKILL_DIR}/run.py".encode()
    monkeypatch.setattr(push, "DEFAULT_PER_FILE_MAX_BYTES", 1000)
    monkeypatch.setattr(push, "MAX_FILE_BYTES", len(expected) - 1, raising=False)
    push._resolve_skill_dirs(files, ["report", "report-other"])
    assert files == {"report-other/SKILL.md": b"healthy"}


@pytest.mark.parametrize("excess", [0, 1])
def test_expansion_checks_combined_bytes_before_substitution(
    monkeypatch: pytest.MonkeyPatch,
    excess: int,
) -> None:
    body = b"${CLAUDE_SKILL_DIR}/run.py"
    files = {
        "report/SKILL.md": body,
        "report/run.py": b"script",
        "report-other/SKILL.md": b"healthy",
    }
    expected = f"{_SKILL_DIR}/run.py".encode()
    monkeypatch.setattr(
        push,
        "SKILL_RUNTIME_MAX_BYTES",
        len(expected) + len(b"scripthealthy") - excess,
        raising=False,
    )
    push._resolve_skill_dirs(files, ["report", "report-other"])
    if excess:
        assert files == {"report-other/SKILL.md": b"healthy"}
    else:
        assert files["report/SKILL.md"] == expected
        assert files["report/run.py"] == b"script"
        assert files["report-other/SKILL.md"] == b"healthy"


def test_expansion_accumulates_growth_and_keeps_later_fitting_skill(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = b"${CLAUDE_SKILL_DIR}"
    files = {
        "first/SKILL.md": body,
        "second/SKILL.md": body,
        "third/SKILL.md": body,
        "healthy/SKILL.md": b"healthy",
    }
    first = b"/workspace/managed/skills/first"
    third = b"/workspace/managed/skills/third"
    monkeypatch.setattr(
        push,
        "SKILL_RUNTIME_MAX_BYTES",
        len(first) + len(body) * 2 + len(b"healthy"),
        raising=False,
    )
    push._resolve_skill_dirs(files, ["first", "second", "third", "healthy"])
    assert files == {
        "first/SKILL.md": first,
        "third/SKILL.md": third,
        "healthy/SKILL.md": b"healthy",
    }
