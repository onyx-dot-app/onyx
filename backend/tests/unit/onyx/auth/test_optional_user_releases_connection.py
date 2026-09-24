"""optional_user must end its DB transaction before it yields, so the auth
connection is not held open for the whole (possibly streaming) response."""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from starlette.requests import Request

import onyx.auth.users as users_module


def _make_request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [],
            "query_string": b"",
        }
    )


def _make_session(
    *,
    in_transaction: bool = True,
    is_active: bool = True,
    dirty: set | None = None,
) -> AsyncMock:
    session = AsyncMock()
    session.in_transaction = MagicMock(return_value=in_transaction)
    session.is_active = is_active
    session.new = set()
    session.dirty = dirty if dirty is not None else set()
    session.deleted = set()
    return session


@pytest.mark.asyncio
async def test_ends_clean_read_transaction_before_yield(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolved_user = MagicMock()
    resolved_user.id = uuid.uuid4()
    monkeypatch.setattr(
        users_module,
        "_resolve_optional_user",
        AsyncMock(return_value=resolved_user),
    )
    session = _make_session()

    gen = users_module.optional_user(
        _make_request(),
        async_db_session=session,
        user=None,
        user_manager=MagicMock(),
    )
    try:
        assert await anext(gen) is resolved_user
        session.commit.assert_awaited_once()
    finally:
        await gen.aclose()


@pytest.mark.asyncio
async def test_pending_writes_are_not_committed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        users_module, "_resolve_optional_user", AsyncMock(return_value=None)
    )
    session = _make_session(dirty={object()})

    gen = users_module.optional_user(
        _make_request(),
        async_db_session=session,
        user=None,
        user_manager=MagicMock(),
    )
    try:
        assert await anext(gen) is None
        session.commit.assert_not_awaited()
    finally:
        await gen.aclose()


@pytest.mark.asyncio
async def test_failed_transaction_is_not_committed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A swallowed write failure (e.g. OAuth refresh) leaves the transaction
    in partial-rollback state; committing it would raise and break auth."""
    monkeypatch.setattr(
        users_module, "_resolve_optional_user", AsyncMock(return_value=None)
    )
    session = _make_session(is_active=False)

    gen = users_module.optional_user(
        _make_request(),
        async_db_session=session,
        user=None,
        user_manager=MagicMock(),
    )
    try:
        assert await anext(gen) is None
        session.commit.assert_not_awaited()
    finally:
        await gen.aclose()


@pytest.mark.asyncio
async def test_commit_failure_does_not_break_auth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolved_user = MagicMock()
    resolved_user.id = uuid.uuid4()
    monkeypatch.setattr(
        users_module,
        "_resolve_optional_user",
        AsyncMock(return_value=resolved_user),
    )
    session = _make_session()
    session.commit.side_effect = RuntimeError("connection dropped")

    gen = users_module.optional_user(
        _make_request(),
        async_db_session=session,
        user=None,
        user_manager=MagicMock(),
    )
    try:
        assert await anext(gen) is resolved_user
        session.commit.assert_awaited_once()
    finally:
        await gen.aclose()


@pytest.mark.asyncio
async def test_no_transaction_means_no_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        users_module, "_resolve_optional_user", AsyncMock(return_value=None)
    )
    session = _make_session(in_transaction=False)

    gen = users_module.optional_user(
        _make_request(),
        async_db_session=session,
        user=None,
        user_manager=MagicMock(),
    )
    try:
        assert await anext(gen) is None
        session.commit.assert_not_awaited()
    finally:
        await gen.aclose()
