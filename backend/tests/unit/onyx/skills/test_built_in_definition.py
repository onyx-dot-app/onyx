"""Tests for ``BuiltInSkillDefinition`` construction-time validation."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from onyx.skills.built_in import BuiltInSkillDefinition


def _definition(name: str) -> BuiltInSkillDefinition:
    return BuiltInSkillDefinition(built_in_skill_id=name)


def test_valid_built_in_skill_id_constructs_cleanly() -> None:
    assert _definition("pptx").built_in_skill_id == "pptx"
    assert _definition("image-generation").built_in_skill_id == "image-generation"
    assert _definition("a").built_in_skill_id == "a"
    assert _definition("1-report").built_in_skill_id == "1-report"


@pytest.mark.parametrize(
    "bad",
    [
        "Pptx",  # uppercase
        "pptx skill",  # whitespace
        "-leading-dash",
        "trailing_underscore_",
        "has.dot",
        "x" * 65,  # too long
        "",
    ],
)
def test_invalid_built_in_skill_id_raises_at_construction(bad: str) -> None:
    with pytest.raises(ValidationError):
        _definition(bad)
