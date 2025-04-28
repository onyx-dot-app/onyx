import os

import pytest

from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.reset import reset_all
from tests.integration.common_utils.test_models import DATestUser


@pytest.mark.skipif(
    os.getenv("PYTEST_IGNORE_SKIP") is None,
    reason="Skipped by default unless env var exists",
)
def test_playwright_setup() -> None:
    """Not really a test, just using this to automate setup for playwright tests."""
    if not os.getenv("PYTEST_PLAYWRIGHT_SKIP_INITIAL_RESET", "").lower() == "true":
        reset_all()

    # Creating an admin user (first user created is automatically an admin)
    admin_user: DATestUser = UserManager.create(name="admin_user")
    assert admin_user
