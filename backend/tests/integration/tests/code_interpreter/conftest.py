from collections.abc import Generator

import pytest
import requests

from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.test_models import DATestUser

CODE_INTERPRETER_URL = f"{API_SERVER_URL}/admin/code-interpreter"


@pytest.fixture
def preserve_code_interpreter_state(
    admin_user: DATestUser,
) -> Generator[None, None, None]:
    """Capture the code interpreter enabled state before a test and restore it
    afterwards, so that tests that toggle the setting cannot leak state."""
    response = requests.get(
        CODE_INTERPRETER_URL,
        headers=admin_user.headers,
    )
    response.raise_for_status()
    initial_enabled = response.json()["enabled"]

    yield

    restore = requests.put(
        CODE_INTERPRETER_URL,
        json={"enabled": initial_enabled},
        headers=admin_user.headers,
    )
    restore.raise_for_status()
