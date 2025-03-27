from unittest.mock import AsyncMock
from unittest.mock import MagicMock

import pytest

from onyx.db.models import OAuthAccount
from onyx.db.models import User


@pytest.fixture
def mock_user() -> MagicMock:
    """Creates a mock User instance for testing."""
    user = MagicMock(spec=User)
    user.email = "test@example.com"
    user.id = "test-user-id"
    return user


@pytest.fixture
def mock_oauth_account() -> MagicMock:
    """Creates a mock OAuthAccount instance for testing."""
    oauth_account = MagicMock(spec=OAuthAccount)
    oauth_account.oauth_name = "google"
    oauth_account.refresh_token = "test-refresh-token"
    oauth_account.access_token = "test-access-token"
    oauth_account.expires_at = None
    return oauth_account


@pytest.fixture
def mock_user_manager() -> MagicMock:
    """Creates a mock user manager for testing."""
    user_manager = MagicMock()
    user_manager.user_db = MagicMock()
    user_manager.user_db.update_oauth_account = AsyncMock()
    user_manager.user_db.update = AsyncMock()
    return user_manager


@pytest.fixture
def mock_db_session() -> MagicMock:
    """Creates a mock database session for testing."""
    return MagicMock()
