"""Autouse fixtures for the unit-tests-for-skills package.

``BuiltinSkillRegistry`` is a process-wide singleton populated at boot. Unit
tests previously sprinkled ``BuiltinSkillRegistry._reset_for_testing()`` calls
across every test that touched the registry; this autouse fixture centralises
that reset so each test starts from a clean slate.
"""

from __future__ import annotations

from collections.abc import Generator

import pytest

from onyx.skills.registry import BuiltinSkillRegistry


@pytest.fixture(autouse=True)
def _reset_builtin_skill_registry() -> Generator[None, None, None]:
    BuiltinSkillRegistry._reset_for_testing()
    yield
    BuiltinSkillRegistry._reset_for_testing()
