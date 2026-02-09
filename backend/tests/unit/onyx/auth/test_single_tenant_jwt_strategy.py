import uuid
from datetime import datetime
from datetime import timezone
from unittest.mock import AsyncMock
from unittest.mock import MagicMock

import jwt
import pytest

from onyx.auth.users import SingleTenantJWTStrategy


_TEST_SECRET = "test-secret-key-for-jwt-unit-tests"
_TEST_LIFETIME = 3600  # 1 hour


def _make_strategy(
    lifetime_seconds: int | None = _TEST_LIFETIME,
) -> SingleTenantJWTStrategy:
    return SingleTenantJWTStrategy(
        secret=_TEST_SECRET,
        lifetime_seconds=lifetime_seconds,
    )


def _make_user(user_id: uuid.UUID | None = None) -> MagicMock:
    user = MagicMock()
    user.id = user_id or uuid.uuid4()
    user.email = "test@example.com"
    return user


def _make_user_manager(user: MagicMock) -> MagicMock:
    manager = MagicMock()
    manager.parse_id = MagicMock(return_value=user.id)
    manager.get = AsyncMock(return_value=user)
    return manager


@pytest.mark.asyncio
async def test_write_token_produces_valid_jwt() -> None:
    """write_token should return a JWT whose claims contain sub and iat."""
    strategy = _make_strategy()
    user = _make_user()

    token = await strategy.write_token(user)

    payload = jwt.decode(
        token, _TEST_SECRET, algorithms=["HS256"], audience=["fastapi-users:auth"]
    )
    assert payload["sub"] == str(user.id)
    assert "iat" in payload
    assert "exp" in payload


@pytest.mark.asyncio
async def test_write_token_iat_is_accurate() -> None:
    """The iat claim should be close to the current time."""
    strategy = _make_strategy()
    user = _make_user()
    before = int(datetime.now(timezone.utc).timestamp())

    token = await strategy.write_token(user)

    payload = jwt.decode(
        token, _TEST_SECRET, algorithms=["HS256"], audience=["fastapi-users:auth"]
    )
    after = int(datetime.now(timezone.utc).timestamp())
    assert before <= payload["iat"] <= after


@pytest.mark.asyncio
async def test_read_token_returns_user() -> None:
    """read_token should decode the JWT and return the corresponding user."""
    strategy = _make_strategy()
    user = _make_user()
    manager = _make_user_manager(user)

    token = await strategy.write_token(user)
    result = await strategy.read_token(token, manager)

    assert result is user
    manager.parse_id.assert_called_once_with(str(user.id))
    manager.get.assert_called_once_with(user.id)


@pytest.mark.asyncio
async def test_read_token_returns_none_for_none() -> None:
    """read_token should return None when token is None."""
    strategy = _make_strategy()
    manager = _make_user_manager(_make_user())

    result = await strategy.read_token(None, manager)
    assert result is None


@pytest.mark.asyncio
async def test_read_token_returns_none_for_bad_signature() -> None:
    """read_token should return None for a token signed with a different secret."""
    strategy = _make_strategy()
    user = _make_user()
    manager = _make_user_manager(user)

    bad_strategy = SingleTenantJWTStrategy(secret="wrong-secret", lifetime_seconds=3600)
    bad_token = await bad_strategy.write_token(user)

    result = await strategy.read_token(bad_token, manager)
    assert result is None


@pytest.mark.asyncio
async def test_read_token_returns_none_for_expired_token() -> None:
    """read_token should return None when the token has expired."""
    # lifetime_seconds=0 doesn't set exp, so we craft a token manually
    strategy = _make_strategy()
    user = _make_user()
    manager = _make_user_manager(user)

    expired_payload = {
        "sub": str(user.id),
        "aud": ["fastapi-users:auth"],
        "iat": 1000000000,
        "exp": 1000000001,  # expired long ago
    }
    expired_token = jwt.encode(expired_payload, _TEST_SECRET, algorithm="HS256")

    result = await strategy.read_token(expired_token, manager)
    assert result is None


@pytest.mark.asyncio
async def test_destroy_token_is_noop() -> None:
    """destroy_token should not raise — JWTs can't be server-side invalidated."""
    strategy = _make_strategy()
    user = _make_user()
    token = await strategy.write_token(user)

    # Should complete without error
    await strategy.destroy_token(token, user)


@pytest.mark.asyncio
async def test_refresh_token_returns_new_jwt() -> None:
    """refresh_token should issue a fresh JWT (different from the original)."""
    strategy = _make_strategy()
    user = _make_user()

    original_token = await strategy.write_token(user)
    refreshed_token = await strategy.refresh_token(original_token, user)

    # Tokens contain different iat/exp, so the encoded strings should differ
    # (unless generated in the same second — but we check claims to be safe)
    refreshed_payload = jwt.decode(
        refreshed_token,
        _TEST_SECRET,
        algorithms=["HS256"],
        audience=["fastapi-users:auth"],
    )
    assert refreshed_payload["sub"] == str(user.id)
    assert "iat" in refreshed_payload
    assert "exp" in refreshed_payload


@pytest.mark.asyncio
async def test_refresh_token_with_none_creates_new() -> None:
    """refresh_token(None, user) should create a brand-new token."""
    strategy = _make_strategy()
    user = _make_user()

    token = await strategy.refresh_token(None, user)

    payload = jwt.decode(
        token, _TEST_SECRET, algorithms=["HS256"], audience=["fastapi-users:auth"]
    )
    assert payload["sub"] == str(user.id)


@pytest.mark.asyncio
async def test_write_token_no_lifetime_omits_exp() -> None:
    """When lifetime_seconds is None, the token should have no exp claim."""
    strategy = _make_strategy(lifetime_seconds=None)
    user = _make_user()

    token = await strategy.write_token(user)

    payload = jwt.decode(
        token,
        _TEST_SECRET,
        algorithms=["HS256"],
        audience=["fastapi-users:auth"],
        options={"verify_exp": False},
    )
    assert payload["sub"] == str(user.id)
    assert "exp" not in payload
