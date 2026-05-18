"""Shared fixtures for build-mode integration tests.

Tests in this directory hit the running Onyx API server (build router) against
real Postgres / Redis / file store. The integration CI workflow sets
``ENABLE_CRAFT=true`` so the Craft endpoints are available.
"""

from __future__ import annotations

import pytest

from tests.integration.common_utils.constants import ADMIN_USER_NAME
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.test_models import DATestLLMProvider
from tests.integration.common_utils.test_models import DATestUser


@pytest.fixture(autouse=True)
def _reset_db(reset: None) -> None:  # noqa: ARG001
    """Auto-reset DB before each build test."""


@pytest.fixture(autouse=True)
def _ensure_llm_provider(llm_provider: DATestLLMProvider) -> None:  # noqa: ARG001
    """Seed a default LLM provider after each DB reset."""


@pytest.fixture
def admin_user(reset: None) -> DATestUser:  # noqa: ARG001
    """Override root conftest's admin_user to depend on reset.

    Without this, pytest may schedule the root admin_user fixture BEFORE
    the autouse _reset_db fixture, leaving a stale admin object after the
    DB wipe.  Any fixture that depends on admin_user (e.g. basic_user)
    then creates the first post-reset user and gets ADMIN instead of BASIC.
    """
    return UserManager.create(name=ADMIN_USER_NAME)
