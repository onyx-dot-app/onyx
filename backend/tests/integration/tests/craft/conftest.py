"""Fixtures for craft integration tests."""

from __future__ import annotations

import pytest

from tests.integration.common_utils.constants import ADMIN_USER_NAME
from tests.integration.common_utils.managers.llm_provider import LLMProviderManager
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.reset import reset_all


@pytest.fixture(scope="module", autouse=True)
def _module_reset_and_seed() -> None:
    reset_all()
    admin = UserManager.create(name=ADMIN_USER_NAME)
    LLMProviderManager.create(user_performing_action=admin)
