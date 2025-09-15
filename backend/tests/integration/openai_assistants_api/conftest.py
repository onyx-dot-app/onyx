from typing import Optional
from uuid import UUID

import pytest
import requests

from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.constants import GENERAL_HEADERS
from tests.integration.common_utils.test_models import DATestUser

BASE_URL = f"{API_SERVER_URL}/openai-assistants"


@pytest.fixture
def thread_id(admin_user: Optional[DATestUser]) -> UUID:
    # Create a thread to use in the tests
    response = requests.post(
        f"{BASE_URL}/threads",  # Updated endpoint path
        json={},
        headers=admin_user.headers if admin_user else GENERAL_HEADERS,
    )
    assert response.status_code == 200
    return UUID(response.json()["id"])
