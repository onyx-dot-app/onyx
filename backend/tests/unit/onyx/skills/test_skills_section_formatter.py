"""Tests for the AGENTS.md skills section formatter."""

from pathlib import Path
from unittest.mock import MagicMock

from onyx.db.models import Skill
from onyx.server.features.build.sandbox.util.agent_instructions import (
    build_skills_section_from_data,
)
from onyx.skills.registry import BuiltinSkill


def _builtin(slug: str, description: str = "desc") -> BuiltinSkill:
    return BuiltinSkill(
        slug=slug,
        name=slug,
        description=description,
        source_dir=Path("/tmp/does-not-matter"),
        has_template=False,
    )


def _custom(slug: str, description: str = "desc") -> Skill:
    skill = MagicMock(spec=Skill)
    skill.slug = slug
    skill.description = description
    return skill


def test_empty_inputs_render_no_skills_message() -> None:
    assert build_skills_section_from_data([], []) == "No skills available."


def test_builtins_only_render_alphabetically() -> None:
    section = build_skills_section_from_data([_builtin("zebra"), _builtin("alpha")], [])
    lines = section.splitlines()
    assert lines == [
        "- **alpha**: desc",
        "- **zebra**: desc",
    ]


def test_builtins_and_customs_interleaved_by_slug() -> None:
    section = build_skills_section_from_data(
        [_builtin("pptx", "make decks")],
        [_custom("aardvark", "find things"), _custom("zulu", "last")],
    )
    lines = section.splitlines()
    assert lines == [
        "- **aardvark**: find things",
        "- **pptx**: make decks",
        "- **zulu**: last",
    ]


def test_long_descriptions_are_truncated() -> None:
    long = "x" * 200
    section = build_skills_section_from_data([_builtin("s", long)], [])
    line = section.splitlines()[0]
    assert line.endswith("...")
    assert len(line) <= len("- **s**: ") + 120
