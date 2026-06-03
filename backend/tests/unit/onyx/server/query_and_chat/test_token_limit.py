"""Unit tests for token-rate-limit enforcement (in-memory SQLite).

Guards the admin-facing unit: a stored ``token_budget`` of N must enforce at
exactly N tokens (raw), so the value an admin types is the value enforced.
"""

import datetime
from collections.abc import Generator
from typing import cast

import pytest
from sqlalchemy import create_engine
from sqlalchemy import Table
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.orm import sessionmaker

import ee.onyx.server.query_and_chat.token_limit as ee_token_limit
import onyx.server.query_and_chat.token_limit as token_limit
from onyx.db.models import TokenRateLimit
from onyx.db.models import TokenRateLimitScope
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.query_and_chat.token_limit import _is_rate_limited


@pytest.fixture
def db_session() -> Generator[Session, None, None]:
    engine: Engine = create_engine("sqlite://")
    # Only the table under test; user-group FK is not exercised here.
    cast(Table, TokenRateLimit.__table__).create(bind=engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def _make_limit(token_budget: int) -> TokenRateLimit:
    return TokenRateLimit(
        enabled=True,
        token_budget=token_budget,
        period_hours=1,
        scope=TokenRateLimitScope.GLOBAL,
    )


def _usage(token_count: int) -> list[tuple[datetime.datetime, int]]:
    now = datetime.datetime.now(tz=datetime.timezone.utc)
    return [(now, token_count)]


class TestIsRateLimitedUnit:
    def test_budget_is_raw_tokens(self) -> None:
        # token_budget=12 must enforce at 12 tokens, not 12,000.
        limit = _make_limit(token_budget=12)
        assert _is_rate_limited([limit], _usage(11)) is False
        assert _is_rate_limited([limit], _usage(12)) is True
        assert _is_rate_limited([limit], _usage(13)) is True

    def test_below_budget_not_limited(self) -> None:
        limit = _make_limit(token_budget=1000)
        assert _is_rate_limited([limit], _usage(999)) is False

    def test_at_budget_is_limited(self) -> None:
        limit = _make_limit(token_budget=1000)
        assert _is_rate_limited([limit], _usage(1000)) is True


def _assert_structured_429(exc: OnyxError, scope: str, period_hours: int) -> None:
    """The 429 the FE banner binds to: RATE_LIMITED + scope + reset fields + header."""
    assert exc.error_code is OnyxErrorCode.RATE_LIMITED
    assert exc.status_code == 429
    assert scope in exc.detail

    extra = exc.extra or {}
    assert extra["scope"] == scope
    assert extra["retry_after_seconds"] == period_hours * 3600

    reset_at = datetime.datetime.fromisoformat(cast(str, extra["reset_at"]))
    now = datetime.datetime.now(tz=datetime.timezone.utc)
    expected = now + datetime.timedelta(hours=period_hours)
    # Allow a few seconds of execution slop.
    assert abs((reset_at - expected).total_seconds()) < 60

    assert exc.headers == {"Retry-After": str(period_hours * 3600)}


class TestRaiseRateLimited:
    def test_global_scope_shape(self) -> None:
        with pytest.raises(OnyxError) as ei:
            token_limit.raise_rate_limited("organization", period_hours=2)
        _assert_structured_429(ei.value, "organization", 2)


class _SessionCtx:
    """Minimal stand-in for get_session_with_current_tenant (only the limit fetch is patched)."""

    def __enter__(self) -> object:
        return object()

    def __exit__(self, *args: object) -> None:
        return None


class TestGlobalRejectionPath:
    """CE path: a global limit over budget raises the structured 429."""

    def test_over_global_budget_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        limit = _make_limit(token_budget=1000)
        limit.period_hours = 3

        monkeypatch.setattr(
            token_limit, "get_session_with_current_tenant", lambda: _SessionCtx()
        )
        monkeypatch.setattr(
            token_limit,
            "fetch_all_global_token_rate_limits",
            lambda **_: [limit],
        )
        # date_trunc isn't valid on SQLite; stub usage directly.
        monkeypatch.setattr(token_limit, "_fetch_global_usage", lambda *_: _usage(1500))

        with pytest.raises(OnyxError) as ei:
            token_limit._user_is_rate_limited_by_global()
        _assert_structured_429(ei.value, "organization", 3)

    def test_under_global_budget_does_not_raise(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        limit = _make_limit(token_budget=1000)
        monkeypatch.setattr(
            token_limit, "get_session_with_current_tenant", lambda: _SessionCtx()
        )
        monkeypatch.setattr(
            token_limit,
            "fetch_all_global_token_rate_limits",
            lambda **_: [limit],
        )
        monkeypatch.setattr(token_limit, "_fetch_global_usage", lambda *_: _usage(10))

        token_limit._user_is_rate_limited_by_global()  # no raise


class TestEEUserRejectionPath:
    """EE path: a per-user limit over budget raises the structured 429."""

    def test_over_user_budget_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        limit = TokenRateLimit(
            enabled=True,
            token_budget=1000,
            period_hours=4,
            scope=TokenRateLimitScope.USER,
        )
        monkeypatch.setattr(
            ee_token_limit, "get_session_with_current_tenant", lambda: _SessionCtx()
        )
        monkeypatch.setattr(
            ee_token_limit,
            "fetch_all_user_token_rate_limits",
            lambda **_: [limit],
        )
        monkeypatch.setattr(
            ee_token_limit, "_fetch_user_usage", lambda *_: _usage(2000)
        )

        import uuid

        with pytest.raises(OnyxError) as ei:
            ee_token_limit._user_is_rate_limited(uuid.uuid4())
        _assert_structured_429(ei.value, "user", 4)


class TestEEGroupRejectionPath:
    """EE path: limited only when EVERY group is over budget; reset = longest window."""

    def test_all_groups_over_budget_raises(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        g1 = TokenRateLimit(
            enabled=True,
            token_budget=1000,
            period_hours=1,
            scope=TokenRateLimitScope.USER_GROUP,
        )
        g2 = TokenRateLimit(
            enabled=True,
            token_budget=1000,
            period_hours=5,
            scope=TokenRateLimitScope.USER_GROUP,
        )
        monkeypatch.setattr(
            ee_token_limit, "get_session_with_current_tenant", lambda: _SessionCtx()
        )
        monkeypatch.setattr(
            ee_token_limit,
            "_fetch_all_user_group_rate_limits",
            lambda *_: {10: [g1], 20: [g2]},
        )
        monkeypatch.setattr(
            ee_token_limit,
            "_fetch_user_group_usage",
            lambda *_: {10: _usage(2000), 20: _usage(2000)},
        )

        import uuid

        with pytest.raises(OnyxError) as ei:
            ee_token_limit._user_is_rate_limited_by_group(uuid.uuid4())
        # longest triggering window (5h) is the conservative retry
        _assert_structured_429(ei.value, "user's groups", 5)

    def test_one_group_under_budget_does_not_raise(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        g1 = TokenRateLimit(
            enabled=True,
            token_budget=1000,
            period_hours=1,
            scope=TokenRateLimitScope.USER_GROUP,
        )
        g2 = TokenRateLimit(
            enabled=True,
            token_budget=1000,
            period_hours=5,
            scope=TokenRateLimitScope.USER_GROUP,
        )
        monkeypatch.setattr(
            ee_token_limit, "get_session_with_current_tenant", lambda: _SessionCtx()
        )
        monkeypatch.setattr(
            ee_token_limit,
            "_fetch_all_user_group_rate_limits",
            lambda *_: {10: [g1], 20: [g2]},
        )
        monkeypatch.setattr(
            ee_token_limit,
            "_fetch_user_group_usage",
            lambda *_: {10: _usage(2000), 20: _usage(10)},
        )

        import uuid

        ee_token_limit._user_is_rate_limited_by_group(uuid.uuid4())  # no raise
