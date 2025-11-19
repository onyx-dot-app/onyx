from unittest.mock import AsyncMock
from unittest.mock import MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from onyx.auth.users import UserManager


def _build_db_session(return_ids: list[int]) -> MagicMock:
    scalar_result = MagicMock()
    scalar_result.all.return_value = return_ids
    execute_result = MagicMock()
    execute_result.scalars.return_value = scalar_result

    db_session = MagicMock(spec=AsyncSession)
    db_session.execute = AsyncMock(return_value=execute_result)
    return db_session


@pytest.mark.asyncio
async def test_assign_default_pinned_assistants_populates_ids(
    mock_user: MagicMock,
) -> None:
    user_db = MagicMock()
    user_db.update = AsyncMock()

    user_manager = UserManager(user_db)

    mock_user.pinned_assistants = None

    db_session = _build_db_session([1, 5, 10])

    await user_manager._assign_default_pinned_assistants(mock_user, db_session)

    assert db_session.execute.await_count == 1
    user_db.update.assert_awaited_once()
    await_args = user_db.update.await_args
    assert await_args
    assert await_args.args == (mock_user, {"pinned_assistants": [1, 5, 10]})
    assert mock_user.pinned_assistants == [1, 5, 10]


@pytest.mark.asyncio
async def test_assign_default_pinned_assistants_skips_when_no_defaults(
    mock_user: MagicMock,
) -> None:
    user_db = MagicMock()
    user_db.update = AsyncMock()

    user_manager = UserManager(user_db)
    mock_user.pinned_assistants = None

    db_session = _build_db_session([])

    await user_manager._assign_default_pinned_assistants(mock_user, db_session)

    assert db_session.execute.await_count == 1
    user_db.update.assert_not_awaited()
    assert mock_user.pinned_assistants is None


@pytest.mark.asyncio
async def test_assign_default_pinned_assistants_noop_if_already_set(
    mock_user: MagicMock,
) -> None:
    user_db = MagicMock()
    user_db.update = AsyncMock()

    user_manager = UserManager(user_db)
    mock_user.pinned_assistants = [3]

    db_session = _build_db_session([1, 2, 3])

    await user_manager._assign_default_pinned_assistants(mock_user, db_session)

    user_db.update.assert_not_awaited()
    assert db_session.execute.await_count == 0
