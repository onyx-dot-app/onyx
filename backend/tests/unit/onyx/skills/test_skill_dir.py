"""Skill folder paths: the shared model text and the OpenCode version it copies."""

import re
from pathlib import Path

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
