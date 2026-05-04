from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from onyx.auth.users import _maybe_refresh_oauth_tokens
from onyx.db.models import User


@pytest.mark.asyncio
async def test_maybe_refresh_oauth_tokens_invokes_check_and_refresh(
    mock_user: MagicMock,
    mock_user_manager: MagicMock,
    mock_db_session: AsyncSession,
) -> None:
    """Happy path: the helper delegates to `check_and_refresh_oauth_tokens`.

    `check_and_refresh_oauth_tokens` already short-circuits when no
    oauth_account is within the 5-minute renewal buffer, so calling it on
    every authenticated request is the right granularity for this hook.
    """
    with patch(
        "onyx.auth.oauth_refresher.check_and_refresh_oauth_tokens",
        AsyncMock(return_value=None),
    ) as mock_refresh:
        await _maybe_refresh_oauth_tokens(mock_user, mock_db_session, mock_user_manager)

    mock_refresh.assert_awaited_once()
    await_args = mock_refresh.await_args
    assert await_args is not None
    assert await_args.kwargs["user"] is mock_user
    assert await_args.kwargs["db_session"] is mock_db_session
    assert await_args.kwargs["user_manager"] is mock_user_manager


@pytest.mark.asyncio
async def test_maybe_refresh_oauth_tokens_swallows_failures(
    mock_user: MagicMock,
    mock_user_manager: MagicMock,
    mock_db_session: AsyncSession,
) -> None:
    """A misconfigured IdP must NOT break authentication of a valid request.

    `check_and_refresh_oauth_tokens` raising should be logged and the
    helper should return None — leaving the caller (`optional_user`) to
    return the resolved user with whatever access_token is already stored.
    """
    with patch(
        "onyx.auth.oauth_refresher.check_and_refresh_oauth_tokens",
        AsyncMock(side_effect=RuntimeError("IdP unreachable")),
    ):
        result = await _maybe_refresh_oauth_tokens(
            mock_user, mock_db_session, mock_user_manager
        )

    # The helper has no return value; the assertion that matters is that
    # the exception did NOT propagate.
    assert result is None


@pytest.fixture
def mock_user() -> MagicMock:
    user = MagicMock(spec=User)
    user.email = "test@example.com"
    return user


@pytest.fixture
def mock_user_manager() -> MagicMock:
    user_manager = MagicMock()
    user_manager.user_db = MagicMock()
    user_manager.user_db.update_oauth_account = AsyncMock()
    user_manager.user_db.update = AsyncMock()
    return user_manager


@pytest.fixture
def mock_db_session() -> MagicMock:
    return MagicMock()
