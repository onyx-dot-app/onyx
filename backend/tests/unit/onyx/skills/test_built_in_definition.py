"""Tests for ``BuiltInSkillDefinition`` construction-time validation.

The ``built_in_skill_id`` doubles as the seeded ``slug`` and the
on-disk directory name, so it must match the same grammar enforced for
custom bundle slugs (``SLUG_REGEX`` in ``skills/bundle.py``).
Construction is the right place to fail — at boot, BUILT_IN_SKILLS is
populated once and any drift would otherwise silently break uploads
and on-disk lookups."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from onyx.skills.built_in import BuiltInSkillDefinition


def _definition(slug: str) -> BuiltInSkillDefinition:
    return BuiltInSkillDefinition(built_in_skill_id=slug)


def test_valid_built_in_skill_id_constructs_cleanly() -> None:
    assert _definition("pptx").built_in_skill_id == "pptx"
    assert _definition("image-generation").built_in_skill_id == "image-generation"
    assert _definition("a").built_in_skill_id == "a"


@pytest.mark.parametrize(
    "bad",
    [
        "Pptx",  # uppercase
        "pptx skill",  # whitespace
        "-leading-dash",
        "1-leading-digit",
        "trailing_underscore_",
        "has.dot",
        "x" * 65,  # too long
        "",
    ],
)
def test_invalid_built_in_skill_id_raises_at_construction(bad: str) -> None:
    with pytest.raises(ValidationError):
        _definition(bad)
