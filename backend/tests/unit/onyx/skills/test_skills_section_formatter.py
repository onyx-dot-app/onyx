"""Tests for the AGENTS.md skills section formatter."""

from unittest.mock import MagicMock

from onyx.db.models import Skill
from onyx.server.features.build.sandbox.util.agent_instructions import (
    build_skills_section_from_data,
)


def _row(slug: str, description: str = "desc") -> Skill:
    skill = MagicMock(spec=Skill)
    skill.slug = slug
    skill.description = description
    return skill


def test_empty_input_renders_no_skills_message() -> None:
    assert build_skills_section_from_data([]) == "No skills available."


def test_rows_render_alphabetically_by_slug() -> None:
    section = build_skills_section_from_data([_row("zebra"), _row("alpha")])
    assert section.splitlines() == [
        "- **alpha**: desc",
        "- **zebra**: desc",
    ]


def test_mixed_built_in_and_custom_rows_interleave_by_slug() -> None:
    """Built-in and custom rows are indistinguishable in the section —
    both contribute one bullet line via slug + truncated description."""
    section = build_skills_section_from_data(
        [
            _row("pptx", "make decks"),
            _row("aardvark", "find things"),
            _row("zulu", "last"),
        ]
    )
    assert section.splitlines() == [
        "- **aardvark**: find things",
        "- **pptx**: make decks",
        "- **zulu**: last",
    ]


def test_long_descriptions_are_truncated() -> None:
    long = "x" * 200
    section = build_skills_section_from_data([_row("s", long)])
    line = section.splitlines()[0]
    assert line.endswith("...")
    assert len(line) <= len("- **s**: ") + 120
