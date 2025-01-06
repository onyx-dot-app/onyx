from typing import Optional
from uuid import UUID

import pytest
import requests

from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.constants import GENERAL_HEADERS
from tests.integration.common_utils.managers.llm_provider import LLMProviderManager
from tests.integration.common_utils.managers.user import build_email
from tests.integration.common_utils.managers.user import DEFAULT_PASSWORD
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.managers.user import UserRole
from tests.integration.common_utils.test_models import DATestLLMProvider
from tests.integration.common_utils.test_models import DATestUser

BASE_URL = f"{API_SERVER_URL}/openai-assistants"


@pytest.fixture
def admin_user() -> DATestUser | None:
    try:
        return UserManager.create("admin_user")
    except Exception:
        pass

    try:
        return UserManager.login_as_user(
            DATestUser(
                id="",
                email=build_email("admin_user"),
                password=DEFAULT_PASSWORD,
                headers=GENERAL_HEADERS,
                role=UserRole.ADMIN,
                is_active=True,
            )
        )
    except Exception:
        pass

    return None


@pytest.fixture
def llm_provider(admin_user: DATestUser | None) -> DATestLLMProvider:
    return LLMProviderManager.create(user_performing_action=admin_user)


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
