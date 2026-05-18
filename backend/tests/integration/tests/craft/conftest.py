"""Shared fixtures for build-mode integration tests.

Tests in this directory hit the running Onyx API server (build router) against
real Postgres / Redis / file store. Sandboxes are real LocalSandboxManager
sandboxes when the environment is configured that way.

See ``docs/craft/test-master-plan.md`` Part V for the contract these fixtures
honour and the broader test layer model.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _reset_db(reset: None) -> None:  # noqa: ARG001
    """Auto-reset DB before each build test.

    Matches the convention used by the sibling ``tests/integration/tests/
    skills/conftest.py`` to prevent cross-test state leak.
    """
