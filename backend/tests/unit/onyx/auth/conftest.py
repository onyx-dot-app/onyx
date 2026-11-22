import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from onyx.auth import oauth_refresher
from onyx.db.models import OAuthAccount, User


@pytest.fixture(autouse=True)
def _in_process_cache_lock(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unit tests have no cache backend. One asyncio lock for each lock name
    stands in for the login refresh lock."""
    locks: dict[str, asyncio.Lock] = {}

    @asynccontextmanager
    async def lock(
        lock_name: str, *_args: Any, **_kwargs: Any
    ) -> AsyncGenerator[None, None]:
        async with locks.setdefault(lock_name, asyncio.Lock()):
            yield

    monkeypatch.setattr(oauth_refresher, "async_cache_shared_lock", lock)


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
    session = MagicMock()
    # `check_and_refresh_oauth_tokens` calls `await db_session.refresh(...)`
    # inside the login refresh lock to re-read the latest expires_at from DB; the
    # AsyncMock here lets that await resolve without raising.
    session.refresh = AsyncMock()
    return session
