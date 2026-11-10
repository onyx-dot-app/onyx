"""Tests for ``BuiltInSkillDefinition`` construction-time validation."""

from __future__ import annotations

import subprocess
import sys

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


def test_builtin_footprints_scan_only_on_first_use() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            """
from pathlib import Path
from unittest.mock import patch

scans = []
rglob = Path.rglob

def track_scan(path, pattern, **kwargs):
    if path.parent.name == "builtin":
        scans.append(path)
    return rglob(path, pattern, **kwargs)

with patch.object(Path, "rglob", track_scan):
    from onyx.skills import built_in
    assert not scans, scans
    first = built_in.get_builtin_skill_footprints()
    assert len(scans) == len(built_in.BUILT_IN_SKILLS)
    assert all(item.bytes > 0 and item.files > 0 for item in first.values())
    assert built_in.get_builtin_skill_footprints() == first
    assert len(scans) == len(built_in.BUILT_IN_SKILLS)
""",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
