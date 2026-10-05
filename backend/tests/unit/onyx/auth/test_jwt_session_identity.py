import hashlib
import uuid
from datetime import datetime, timedelta, timezone, tzinfo
from unittest.mock import AsyncMock, MagicMock

import jwt
import pytest
from fastapi_users.jwt import generate_jwt

from onyx.auth import users as users_module
from onyx.auth.users import SingleTenantJWTStrategy

_SECRET = "jwt-session-identity-test-secret-32-bytes"
_OTHER_SECRET = "jwt-session-identity-other-secret-32-bytes"
_AUDIENCE = ["fastapi-users:auth"]


def _strategy(
    *,
    secret: str = _SECRET,
    audience: list[str] | None = None,
    lifetime_seconds: int | None = 3600,
) -> SingleTenantJWTStrategy:
    return SingleTenantJWTStrategy(
        secret=secret,
        lifetime_seconds=lifetime_seconds,
        token_audience=audience or _AUDIENCE,
    )


def _user(user_id: uuid.UUID | None = None) -> MagicMock:
    user = MagicMock()
    user.id = user_id or uuid.uuid4()
    user.email = "jwt-session@example.com"
    return user


def _manager(user: MagicMock) -> MagicMock:
    manager = MagicMock()
    manager.parse_id = MagicMock(return_value=user.id)
    manager.get = AsyncMock(return_value=user)
    return manager


def _decode(token: str, *, audience: list[str] | None = None) -> dict[str, object]:
    return jwt.decode(
        token,
        _SECRET,
        algorithms=["HS256"],
        audience=audience or _AUDIENCE,
    )


def _token_with_claims(
    *,
    user_id: uuid.UUID,
    secret: str = _SECRET,
    audience: list[str] | None = None,
    lifetime_seconds: int | None = 3600,
    sid: str | None = "attacker-controlled-session",
) -> str:
    data: dict[str, object] = {
        "sub": str(user_id),
        "aud": audience or _AUDIENCE,
        "iat": int(datetime.now(timezone.utc).timestamp()),
    }
    if sid is not None:
        data["sid"] = sid
    return generate_jwt(data, secret, lifetime_seconds, algorithm="HS256")


@pytest.mark.asyncio
async def test_write_token_adds_unique_session_id_even_in_same_second(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frozen = datetime.now(timezone.utc)

    class _FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz: tzinfo | None = None) -> "_FrozenDatetime":  # noqa: ARG003
            return cls.fromtimestamp(frozen.timestamp(), tz=timezone.utc)

    monkeypatch.setattr(users_module, "datetime", _FrozenDatetime)
    strategy = _strategy()
    user = _user()

    first = await strategy.write_token(user)
    second = await strategy.write_token(user)

    first_payload = _decode(first)
    second_payload = _decode(second)
    assert first_payload["iat"] == second_payload["iat"]
    assert first_payload["sub"] == str(user.id)
    assert second_payload["sub"] == str(user.id)
    assert isinstance(first_payload["sid"], str)
    assert isinstance(second_payload["sid"], str)
    assert first_payload["sid"] != second_payload["sid"]
    assert strategy.get_session_id(first, user) != strategy.get_session_id(second, user)


@pytest.mark.asyncio
async def test_refresh_preserves_current_session_id() -> None:
    strategy = _strategy()
    user = _user()
    token = await strategy.write_token(user)

    refreshed = await strategy.refresh_token(token, user)

    assert strategy.get_session_id(refreshed, user) == strategy.get_session_id(
        token, user
    )


@pytest.mark.asyncio
async def test_refresh_preserves_legacy_hash_session_id() -> None:
    strategy = _strategy()
    user = _user()
    legacy = _token_with_claims(user_id=user.id, sid=None)

    refreshed = await strategy.refresh_token(legacy, user)

    expected = hashlib.sha256(legacy.encode("utf-8")).hexdigest()
    assert strategy.get_session_id(legacy, user) == expected
    assert strategy.get_session_id(refreshed, user) == expected


@pytest.mark.asyncio
async def test_invalid_refresh_token_mints_fresh_session_id() -> None:
    strategy = _strategy()
    user = _user()
    attacker_token = _token_with_claims(user_id=user.id, secret=_OTHER_SECRET)

    refreshed = await strategy.refresh_token(attacker_token, user)

    assert strategy.get_session_id(refreshed, user) != "attacker-controlled-session"


@pytest.mark.parametrize(
    "token_kind",
    ["wrong_signature", "wrong_audience", "wrong_subject", "expired"],
)
def test_invalid_token_cannot_supply_session_id(token_kind: str) -> None:
    strategy = _strategy()
    user = _user()
    token_user_id = user.id
    secret = _SECRET
    audience = _AUDIENCE
    lifetime_seconds: int | None = 3600

    if token_kind == "wrong_signature":
        secret = _OTHER_SECRET
    elif token_kind == "wrong_audience":
        audience = ["other-audience"]
    elif token_kind == "wrong_subject":
        token_user_id = uuid.uuid4()
    elif token_kind == "expired":
        lifetime_seconds = None

    token = _token_with_claims(
        user_id=token_user_id,
        secret=secret,
        audience=audience,
        lifetime_seconds=lifetime_seconds,
    )
    if token_kind == "expired":
        payload = jwt.decode(
            token,
            _SECRET,
            algorithms=["HS256"],
            audience=_AUDIENCE,
            options={"verify_exp": False},
        )
        payload["exp"] = datetime.now(timezone.utc) - timedelta(seconds=1)
        token = jwt.encode(payload, _SECRET, algorithm="HS256")

    assert strategy.get_session_id(token, user) is None


@pytest.mark.asyncio
async def test_existing_jwt_authentication_still_accepts_current_and_legacy_tokens() -> (
    None
):
    strategy = _strategy()
    user = _user()
    manager = _manager(user)
    current = await strategy.write_token(user)
    legacy = _token_with_claims(user_id=user.id, sid=None)

    assert await strategy.read_token(current, manager) is user
    assert await strategy.read_token(legacy, manager) is user
