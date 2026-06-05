"""Unit tests for token-rate-limit enforcement (in-memory SQLite).

Guards the admin-facing unit: a stored ``token_budget`` of N is in thousands,
so it enforces at N * 1000 tokens (the Onyx convention).
"""

import datetime
from collections.abc import Generator
from typing import cast

import pytest
from sqlalchemy import create_engine
from sqlalchemy import Table
from sqlalchemy.dialects.postgresql import JSONB as PGJSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.engine import Engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session
from sqlalchemy.orm import sessionmaker

import onyx.server.query_and_chat.token_limit as token_limit
from onyx.db.models import TokenRateLimit
from onyx.db.models import TokenRateLimitScope
from onyx.db.models import UserUsage
from onyx.db.user_usage import get_window_start
from onyx.db.user_usage import record_user_usage
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.query_and_chat.token_limit import _worst_triggered_limit


def _is_rate_limited(
    rate_limits: list[TokenRateLimit],
    usage: list[tuple[datetime.datetime, int]],
) -> bool:
    return _worst_triggered_limit(rate_limits, usage) is not None


# Postgres-only column types -> SQLite equivalents so the real UserUsage table
# can back the real cost-source query path.
@compiles(PGUUID, "sqlite")
def _compile_pguuid_sqlite(_e: object, _c: object, **_kw: object) -> str:
    return "CHAR(36)"


@compiles(PGJSONB, "sqlite")
def _compile_jsonb_sqlite(_e: object, _c: object, **_kw: object) -> str:
    return "JSON"


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
    def test_budget_is_in_thousands(self) -> None:
        # token_budget=12 means 12,000 tokens (the Onyx thousands convention).
        limit = _make_limit(token_budget=12)
        assert _is_rate_limited([limit], _usage(11_999)) is False
        assert _is_rate_limited([limit], _usage(12_000)) is True
        assert _is_rate_limited([limit], _usage(12_001)) is True

    def test_below_budget_not_limited(self) -> None:
        limit = _make_limit(token_budget=1000)  # 1,000,000 tokens
        assert _is_rate_limited([limit], _usage(999_999)) is False

    def test_at_budget_is_limited(self) -> None:
        limit = _make_limit(token_budget=1000)  # 1,000,000 tokens
        assert _is_rate_limited([limit], _usage(1_000_000)) is True

    def test_cost_only_limit_is_token_exempt(self) -> None:
        # A cost-only limit (token_budget=None) must NOT block on tokens — a 0
        # would make tokens_used >= 0 always true and block every request.
        cost_only = TokenRateLimit(
            enabled=True,
            token_budget=None,
            cost_budget_cents=500.0,
            period_hours=1,
            scope=TokenRateLimitScope.GLOBAL,
        )
        assert _is_rate_limited([cost_only], _usage(10_000_000)) is False

    def test_zero_token_budget_does_not_block(self) -> None:
        # A legacy/edge token_budget of 0 must be treated as no token limit, not
        # "block at 0 tokens" (which would reject every request).
        zero = TokenRateLimit(
            enabled=True,
            token_budget=0,
            cost_budget_cents=500.0,
            period_hours=1,
            scope=TokenRateLimitScope.GLOBAL,
        )
        assert _is_rate_limited([zero], _usage(10_000_000)) is False

    def test_longest_window_among_exceeded_wins(self) -> None:
        # When several limits are exceeded the reset must be deterministic and
        # conservative: report the longest window so a retry can't immediately
        # re-trip a still-exceeded longer limit. Order must not matter.
        short = TokenRateLimit(
            enabled=True,
            token_budget=1,
            period_hours=1,
            scope=TokenRateLimitScope.GLOBAL,
        )
        long_ = TokenRateLimit(
            enabled=True,
            token_budget=1,
            period_hours=24,
            scope=TokenRateLimitScope.GLOBAL,
        )
        for order in ([short, long_], [long_, short]):
            worst = _worst_triggered_limit(order, _usage(10_000))
            assert worst is not None and worst.period_hours == 24


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


class TestRaiseForLongestWindow:
    """Token + cost gates are evaluated together; the reported reset is the
    longest window, so a short token limit can't mask a longer cost reset."""

    def test_longest_of_token_and_cost_wins(self) -> None:
        with pytest.raises(OnyxError) as ei:
            token_limit._raise_for_longest_window("user", 1, 24)
        _assert_structured_429(ei.value, "user", 24)

    def test_skips_none_windows(self) -> None:
        with pytest.raises(OnyxError) as ei:
            token_limit._raise_for_longest_window("user", None, 5)
        _assert_structured_429(ei.value, "user", 5)

    def test_no_trigger_does_not_raise(self) -> None:
        token_limit._raise_for_longest_window("user", None, None)  # no raise


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
        monkeypatch.setattr(
            token_limit, "_fetch_global_usage", lambda *_: _usage(1_500_000)
        )

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


def _cost_limit(
    cost_budget_cents: float | None,
    scope: TokenRateLimitScope,
    period_hours: int = 1,
    token_budget: int = 10**12,  # effectively unbounded so only cost can trigger
) -> TokenRateLimit:
    limit = TokenRateLimit(
        enabled=True,
        token_budget=token_budget,
        period_hours=period_hours,
        scope=scope,
    )
    limit.cost_budget_cents = cost_budget_cents
    return limit


class TestWorstTriggeredCostLimit:
    """Unit of the shared cost evaluator (no DB; cost is injected)."""

    def test_over_cost_budget_returns_row(self) -> None:
        limit = _cost_limit(100.0, TokenRateLimitScope.USER)
        triggered = token_limit._worst_triggered_cost_limit(
            [limit], cost_since=lambda _cutoff: 150.0
        )
        assert triggered is limit

    def test_under_cost_budget_returns_none(self) -> None:
        limit = _cost_limit(100.0, TokenRateLimitScope.USER)
        assert (
            token_limit._worst_triggered_cost_limit(
                [limit], cost_since=lambda _cutoff: 99.99
            )
            is None
        )

    def test_at_cost_budget_triggers(self) -> None:
        limit = _cost_limit(100.0, TokenRateLimitScope.USER)
        assert (
            token_limit._worst_triggered_cost_limit(
                [limit], cost_since=lambda _cutoff: 100.0
            )
            is limit
        )

    def test_row_without_cost_budget_is_exempt(self) -> None:
        # token-only row (cost_budget_cents is None) is never cost-limited
        limit = _cost_limit(None, TokenRateLimitScope.USER)
        assert (
            token_limit._worst_triggered_cost_limit(
                [limit], cost_since=lambda _cutoff: 10**9
            )
            is None
        )


class TestGlobalCostRejectionPath:
    """CE global path: a global cost budget summed across the tenant raises."""

    def test_over_global_cost_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        limit = _cost_limit(500.0, TokenRateLimitScope.GLOBAL, period_hours=3)
        monkeypatch.setattr(
            token_limit, "get_session_with_current_tenant", lambda: _SessionCtx()
        )
        monkeypatch.setattr(
            token_limit, "fetch_all_global_token_rate_limits", lambda **_: [limit]
        )
        # under token budget so only cost can trigger
        monkeypatch.setattr(token_limit, "_fetch_global_usage", lambda *_: _usage(1))
        monkeypatch.setattr(token_limit, "get_total_cost_cents_since", lambda *_: 600.0)

        with pytest.raises(OnyxError) as ei:
            token_limit._user_is_rate_limited_by_global()
        _assert_structured_429(ei.value, "organization", 3)

    def test_under_global_cost_does_not_raise(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        limit = _cost_limit(500.0, TokenRateLimitScope.GLOBAL)
        monkeypatch.setattr(
            token_limit, "get_session_with_current_tenant", lambda: _SessionCtx()
        )
        monkeypatch.setattr(
            token_limit, "fetch_all_global_token_rate_limits", lambda **_: [limit]
        )
        monkeypatch.setattr(token_limit, "_fetch_global_usage", lambda *_: _usage(1))
        monkeypatch.setattr(token_limit, "get_total_cost_cents_since", lambda *_: 100.0)

        token_limit._user_is_rate_limited_by_global()  # no raise

    def test_cost_only_skips_token_aggregation(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A cost-only limit (token_budget=None) must not run the token-usage query.
        limit = TokenRateLimit(
            enabled=True,
            token_budget=None,
            cost_budget_cents=500.0,
            period_hours=1,
            scope=TokenRateLimitScope.GLOBAL,
        )
        monkeypatch.setattr(
            token_limit, "get_session_with_current_tenant", lambda: _SessionCtx()
        )
        monkeypatch.setattr(
            token_limit, "fetch_all_global_token_rate_limits", lambda **_: [limit]
        )

        def _boom(*_a: object) -> object:
            raise AssertionError("token aggregation ran for a cost-only limit")

        monkeypatch.setattr(token_limit, "_fetch_global_usage", _boom)
        monkeypatch.setattr(token_limit, "get_total_cost_cents_since", lambda *_: 100.0)

        token_limit._user_is_rate_limited_by_global()  # no raise, no token query


class _RealLedgerSessionCtx:
    """Yields a real SQLite session backing the actual UserUsage cost query."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def __enter__(self) -> Session:
        return self._session

    def __exit__(self, *args: object) -> None:
        return None


@pytest.fixture
def ledger_session() -> Generator[Session, None, None]:
    engine: Engine = create_engine("sqlite://")
    cast(Table, UserUsage.__table__).create(bind=engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


class TestCostEnforcementRealLedgerPath:
    """The global cost gate, end-to-end through the real cost source — the
    regression that the prior exact-window read fail-opened on a sub-grid
    budget period."""

    def test_sub_grid_period_blocks_against_real_ledger(
        self, monkeypatch: pytest.MonkeyPatch, ledger_session: Session
    ) -> None:
        # Ledger row written at the weekly grid (as the real processor does),
        # but the admin's budget period is 24h. The sliding cutoff still reads it.
        import uuid

        now = datetime.datetime.now(tz=datetime.timezone.utc)
        ledger_window = get_window_start(now, period_hours=168)
        record_user_usage(
            ledger_session,
            str(uuid.uuid4()),
            "m",
            "CHAT",
            None,
            1,
            1,
            0,
            500.0,
            ledger_window,
        )

        limit = _cost_limit(100.0, TokenRateLimitScope.GLOBAL, period_hours=24)
        monkeypatch.setattr(
            token_limit,
            "get_session_with_current_tenant",
            lambda: _RealLedgerSessionCtx(ledger_session),
        )
        monkeypatch.setattr(
            token_limit, "fetch_all_global_token_rate_limits", lambda **_: [limit]
        )
        monkeypatch.setattr(token_limit, "_fetch_global_usage", lambda *_: _usage(1))

        with pytest.raises(OnyxError) as ei:
            token_limit._user_is_rate_limited_by_global()
        _assert_structured_429(ei.value, "organization", 24)

    def test_window_rollover_does_not_count(
        self, monkeypatch: pytest.MonkeyPatch, ledger_session: Session
    ) -> None:
        import uuid

        now = datetime.datetime.now(tz=datetime.timezone.utc)
        current = get_window_start(now, period_hours=168)
        # Two grids back: always before the (period + one-grid) relaxed cutoff,
        # regardless of weekday. A 24h budget must not see last-period spend.
        prior = current - datetime.timedelta(days=14)
        record_user_usage(
            ledger_session, str(uuid.uuid4()), "m", "CHAT", None, 1, 1, 0, 9999.0, prior
        )

        limit = _cost_limit(100.0, TokenRateLimitScope.GLOBAL, period_hours=24)
        monkeypatch.setattr(
            token_limit,
            "get_session_with_current_tenant",
            lambda: _RealLedgerSessionCtx(ledger_session),
        )
        monkeypatch.setattr(
            token_limit, "fetch_all_global_token_rate_limits", lambda **_: [limit]
        )
        monkeypatch.setattr(token_limit, "_fetch_global_usage", lambda *_: _usage(1))

        token_limit._user_is_rate_limited_by_global()  # no raise


class TestTokenRateLimitArgsValidation:
    """A limit must carry a token budget, a cost budget, or both — never neither."""

    def test_neither_budget_rejected(self) -> None:
        from onyx.server.token_rate_limits.models import TokenRateLimitArgs

        with pytest.raises(ValueError):
            TokenRateLimitArgs(enabled=True, token_budget=None, period_hours=24)

    def test_cost_only_accepted(self) -> None:
        from onyx.server.token_rate_limits.models import TokenRateLimitArgs

        args = TokenRateLimitArgs(
            enabled=True, token_budget=None, period_hours=24, cost_budget_cents=500.0
        )
        assert args.token_budget is None and args.cost_budget_cents == 500.0

    def test_token_only_accepted(self) -> None:
        from onyx.server.token_rate_limits.models import TokenRateLimitArgs

        args = TokenRateLimitArgs(enabled=True, token_budget=1000, period_hours=24)
        assert args.token_budget == 1000 and args.cost_budget_cents is None
