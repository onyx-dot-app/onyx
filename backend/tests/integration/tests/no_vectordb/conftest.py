"""Fixtures for no-vector-DB integration tests.

These tests are intended to run against an Onyx deployment started with
DISABLE_VECTOR_DB=true.  They are automatically **skipped** when the
server reports vector_db_enabled=true (i.e. when Vespa is available).
"""

import pytest
import requests

from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.constants import GENERAL_HEADERS
from tests.integration.common_utils.managers.llm_provider import LLMProviderManager
from tests.integration.common_utils.test_models import DATestUser


def _server_has_vector_db_disabled() -> bool:
    """Query the running server to check whether DISABLE_VECTOR_DB is set."""
    try:
        resp = requests.get(
            f"{API_SERVER_URL}/settings",
            headers=GENERAL_HEADERS,
        )
        if resp.ok:
            return resp.json().get("vector_db_enabled") is False
    except Exception:
        pass
    return False


# Skip the entire module when the server has vector DB enabled —
# these tests only make sense in no-vector-DB deployments.
pytestmark = pytest.mark.skipif(
    not _server_has_vector_db_disabled(),
    reason="Server is running with vector DB enabled; skipping no-vectordb tests",
)


@pytest.fixture()
def llm_provider(admin_user: DATestUser) -> None:
    """Ensure an LLM provider exists for the test session."""
    LLMProviderManager.create(user_performing_action=admin_user)
