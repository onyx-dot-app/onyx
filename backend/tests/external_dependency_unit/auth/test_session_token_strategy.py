"""
Redis session-token tests: embedded expiry, grace TTL, tombstones, and rejection
classification. Real Redis + Postgres, strategy called directly. The
request-level 403 contract lives in test_session_rejection_contract.py.
"""

import contextvars
import json
import secrets
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from typing import cast

import pytest
from fastapi import Request
from sqlalchemy.orm import Session

from onyx.auth.session_tokens import get_session_rejection
from onyx.auth.session_tokens import record_session_rejection
from onyx.auth.session_tokens import SESSION_TOKEN_GRACE_PERIOD_SECONDS
from onyx.auth.session_tokens import SessionRejection
from onyx.auth.session_tokens import SessionRejectionReason
from onyx.auth.session_tokens import SessionTokenValue
from onyx.auth.users import TenantAwareRedisStrategy
from onyx.auth.users import UserManager
from onyx.configs.app_configs import REDIS_AUTH_KEY_PREFIX
from onyx.configs.app_configs import SESSION_EXPIRE_TIME_SECONDS
from onyx.configs.constants import FASTAPI_USERS_AUTH_COOKIE_NAME
from onyx.db.auth import SQLAlchemyUserAdminDB
from onyx.db.engine.async_sql_engine import get_async_session_context_manager
from onyx.db.models import OAuthAccount
from onyx.db.models import User
from onyx.redis.redis_pool import get_raw_redis_client
from onyx.server.manage.users import get_current_auth_token_expiry_redis
from tests.external_dependency_unit.conftest import create_test_user

# Covers the delay between the strategy's SET and the test's TTL read.
_TTL_SLACK_SECONDS = 60


async def _read_token(strategy: TenantAwareRedisStrategy, token: str) -> User | None:
    async with get_async_session_context_manager() as async_session:
        user_db = SQLAlchemyUserAdminDB(async_session, User, OAuthAccount)
        return await strategy.read_token(token, UserManager(user_db))


def _redis_key(token: str) -> str:
    return REDIS_AUTH_KEY_PREFIX + token


def _get_raw_value(token: str) -> bytes | None:
    return cast(bytes | None, get_raw_redis_client().get(_redis_key(token)))


def _delete_key(token: str) -> None:
    get_raw_redis_client().delete(_redis_key(token))


@pytest.mark.asyncio
@pytest.mark.usefixtures("tenant_context")
async def test_write_read_round_trip(db_session: Session) -> None:
    # Precondition.
    user = create_test_user(db_session, "session_round_trip")
    strategy = TenantAwareRedisStrategy()

    # Under test.
    token = await strategy.write_token(user)
    try:
        raw_value = _get_raw_value(token)

        # Postcondition.
        assert raw_value is not None
        value = SessionTokenValue.model_validate_json(raw_value)
        assert value.sub == str(user.id)
        assert value.issued_at is not None
        assert value.expires_at is not None
        assert value.logged_out_at is None

        expected_expiry = value.issued_at + timedelta(
            seconds=SESSION_EXPIRE_TIME_SECONDS
        )
        assert value.expires_at == expected_expiry

        # The physical TTL outlives the logical expiry by the grace window.
        ttl = get_raw_redis_client().ttl(_redis_key(token))
        assert isinstance(ttl, int)
        nominal_ttl = SESSION_EXPIRE_TIME_SECONDS + SESSION_TOKEN_GRACE_PERIOD_SECONDS
        assert nominal_ttl - _TTL_SLACK_SECONDS <= ttl <= nominal_ttl

        read_user = await _read_token(strategy, token)
        assert read_user is not None
        assert read_user.id == user.id
        assert get_session_rejection() is None
    finally:
        _delete_key(token)


@pytest.mark.asyncio
@pytest.mark.usefixtures("tenant_context")
async def test_logical_expiry_enforced_while_key_present(db_session: Session) -> None:
    # Precondition.
    user = create_test_user(db_session, "session_expired")
    strategy = TenantAwareRedisStrategy()
    token = await strategy.write_token(user)
    try:
        # Push the logical expiry into the past; the physical key stays put.
        raw_value = _get_raw_value(token)
        assert raw_value is not None
        data = json.loads(raw_value)
        data["expires_at"] = (
            datetime.now(timezone.utc) - timedelta(minutes=5)
        ).isoformat()
        redis = get_raw_redis_client()
        redis.set(_redis_key(token), json.dumps(data), keepttl=True)

        # Under test.
        read_user = await _read_token(strategy, token)

        # Postcondition.
        assert read_user is None

        rejection = get_session_rejection()
        assert rejection is not None
        assert rejection.reason == SessionRejectionReason.EXPIRED
        assert rejection.token_value is not None
        assert rejection.token_value.sub == str(user.id)

        assert redis.exists(_redis_key(token)) == 1
    finally:
        _delete_key(token)


@pytest.mark.asyncio
@pytest.mark.usefixtures("tenant_context")
async def test_destroy_token_writes_tombstone(db_session: Session) -> None:
    # Precondition.
    user = create_test_user(db_session, "session_tombstone")
    strategy = TenantAwareRedisStrategy()
    token = await strategy.write_token(user)
    try:
        # Under test.
        await strategy.destroy_token(token, user)

        # Postcondition.
        raw_value = _get_raw_value(token)
        assert raw_value is not None
        value = SessionTokenValue.model_validate_json(raw_value)
        assert value.logged_out_at is not None
        # Original fields carry over into the tombstone.
        assert value.sub == str(user.id)
        assert value.issued_at is not None

        ttl = get_raw_redis_client().ttl(_redis_key(token))
        assert isinstance(ttl, int)
        assert (
            SESSION_TOKEN_GRACE_PERIOD_SECONDS - _TTL_SLACK_SECONDS
            <= ttl
            <= SESSION_TOKEN_GRACE_PERIOD_SECONDS
        )

        read_user = await _read_token(strategy, token)
        assert read_user is None

        rejection = get_session_rejection()
        assert rejection is not None
        assert rejection.reason == SessionRejectionReason.TERMINATED
    finally:
        _delete_key(token)


@pytest.mark.asyncio
@pytest.mark.usefixtures("tenant_context")
async def test_absent_token_classified_not_found() -> None:
    strategy = TenantAwareRedisStrategy()
    read_user = await _read_token(strategy, secrets.token_urlsafe())
    assert read_user is None

    rejection = get_session_rejection()
    assert rejection is not None
    assert rejection.reason == SessionRejectionReason.NOT_FOUND
    assert rejection.token_value is None


@pytest.mark.asyncio
@pytest.mark.usefixtures("tenant_context")
async def test_legacy_value_accepted(db_session: Session) -> None:
    # Precondition.
    # Pre-upgrade values stay valid on key existence; deploy signs nobody out.
    user = create_test_user(db_session, "session_legacy")
    strategy = TenantAwareRedisStrategy()
    token = secrets.token_urlsafe()
    get_raw_redis_client().set(
        _redis_key(token),
        json.dumps({"sub": str(user.id), "tenant_id": "public"}),
        ex=SESSION_EXPIRE_TIME_SECONDS,
    )
    try:
        # Under test.
        read_user = await _read_token(strategy, token)

        # Postcondition.
        assert read_user is not None
        assert read_user.id == user.id
        assert get_session_rejection() is None

        # The read path never rewrites: the stored value keeps its legacy shape.
        raw_value = _get_raw_value(token)
        assert raw_value is not None
        assert SessionTokenValue.model_validate_json(raw_value).issued_at is None
    finally:
        _delete_key(token)


def test_legacy_expiry_reported_from_ttl(db_session: Session) -> None:
    # Precondition.
    # /me's expiry for a legacy value comes from the physical TTL.
    user = create_test_user(db_session, "session_legacy_expiry")
    token = secrets.token_urlsafe()
    remaining_seconds = 1234
    get_raw_redis_client().set(
        _redis_key(token),
        json.dumps({"sub": str(user.id), "tenant_id": "public"}),
        ex=remaining_seconds,
    )
    request = Request(
        scope={
            "type": "http",
            "headers": [
                (b"cookie", f"{FASTAPI_USERS_AUTH_COOKIE_NAME}={token}".encode())
            ],
        }
    )
    try:
        # Under test.
        expires_at = get_current_auth_token_expiry_redis(user, request)

        # Postcondition.
        assert expires_at is not None
        expected = datetime.now(timezone.utc) + timedelta(seconds=remaining_seconds)
        assert abs((expires_at - expected).total_seconds()) < _TTL_SLACK_SECONDS
    finally:
        _delete_key(token)


@pytest.mark.asyncio
@pytest.mark.usefixtures("tenant_context")
async def test_unparseable_value_rejected() -> None:
    # Precondition.
    strategy = TenantAwareRedisStrategy()
    token = secrets.token_urlsafe()
    get_raw_redis_client().set(_redis_key(token), "not-json", ex=60)
    try:
        # Under test.
        read_user = await _read_token(strategy, token)

        # Postcondition.
        assert read_user is None

        rejection = get_session_rejection()
        assert rejection is not None
        assert rejection.reason == SessionRejectionReason.MALFORMED
    finally:
        _delete_key(token)


@pytest.mark.asyncio
@pytest.mark.usefixtures("tenant_context")
async def test_api_key_shaped_token_miss_not_classified() -> None:
    # Precondition.
    # bearer-transport credentials that miss in Redis must not classify
    strategy = TenantAwareRedisStrategy()
    for credential in (
        f"on_{secrets.token_urlsafe()}",
        f"onyx_pat_{secrets.token_urlsafe()}",
        "header.payload.signature",
    ):
        # Under test.
        read_user = await _read_token(strategy, credential)

        # Postcondition.
        assert read_user is None
    assert get_session_rejection() is None


@pytest.mark.asyncio
@pytest.mark.usefixtures("tenant_context")
async def test_refresh_extends_expiry_and_preserves_issue_time(
    db_session: Session,
) -> None:
    # Precondition.
    user = create_test_user(db_session, "session_refresh")
    strategy = TenantAwareRedisStrategy()
    token = await strategy.write_token(user)
    try:
        raw_value = _get_raw_value(token)
        assert raw_value is not None
        original = SessionTokenValue.model_validate_json(raw_value)
        assert original.issued_at is not None
        assert original.expires_at is not None

        # Under test.
        refreshed_token = await strategy.refresh_token(token, user)

        # Postcondition.
        assert refreshed_token == token

        raw_value = _get_raw_value(token)
        assert raw_value is not None
        refreshed = SessionTokenValue.model_validate_json(raw_value)
        assert refreshed.issued_at == original.issued_at
        assert refreshed.expires_at is not None
        assert refreshed.expires_at > original.expires_at
    finally:
        _delete_key(token)


def test_first_stored_value_rejection_wins() -> None:
    def scenario() -> None:
        not_found = SessionRejection(
            reason=SessionRejectionReason.NOT_FOUND, token_value=None
        )
        expired = SessionRejection(
            reason=SessionRejectionReason.EXPIRED,
            token_value=SessionTokenValue(sub="some-user"),
        )
        terminated = SessionRejection(
            reason=SessionRejectionReason.TERMINATED,
            token_value=SessionTokenValue(sub="some-user"),
        )

        # A stored-value-backed rejection replaces a bare miss.
        record_session_rejection(not_found)
        record_session_rejection(expired)
        assert get_session_rejection() == expired

        # But nothing replaces it: not a later strong rejection, not a miss.
        record_session_rejection(terminated)
        assert get_session_rejection() == expired
        record_session_rejection(not_found)
        assert get_session_rejection() == expired

    # copy_context so this sync test doesn't leak the var into later tests
    contextvars.copy_context().run(scenario)
