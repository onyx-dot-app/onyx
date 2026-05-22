"""Fixtures for no-vector-DB integration tests.

These tests are intended to run against an Onyx deployment started with
DISABLE_VECTOR_DB=true. They are automatically **skipped** when the
env var is unset.
"""

import os

import pytest

from tests.integration.common_utils.managers.llm_provider import LLMProviderManager
from tests.integration.common_utils.test_models import DATestLLMProvider
from tests.integration.common_utils.test_models import DATestUser

# Skip the entire module when vector DB is enabled. The env var is the
# source of truth because pytestmark is evaluated at module import time
# — the api_server fixture hasn't started yet, so querying the server
# here would raise and (previously) silently disable the whole suite.
_VECTOR_DB_DISABLED = os.getenv("DISABLE_VECTOR_DB", "false").lower() == "true"

pytestmark = pytest.mark.skipif(
    not _VECTOR_DB_DISABLED,
    reason="DISABLE_VECTOR_DB is not true; skipping no-vectordb tests",
)


@pytest.fixture()
def llm_provider(admin_user: DATestUser) -> DATestLLMProvider:
    """Ensure an LLM provider exists for the test session."""
    return LLMProviderManager.create(user_performing_action=admin_user)
