"""Unit tests for token-rate-limit enforcement (in-memory SQLite).

Guards the admin-facing unit: a stored ``token_budget`` of N is in thousands,
so it enforces at N * 1000 tokens (the Onyx convention).
"""

import datetime
from collections.abc import Generator
from typing import cast

import pytest
from sqlalchemy import Table, create_engine
from sqlalchemy.dialects.postgresql import JSONB as PGJSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.engine import Engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session, sessionmaker

import onyx.server.query_and_chat.token_limit as token_limit
from onyx.db.models import TokenRateLimit, TokenRateLimitScope, UserUsage
from onyx.db.user_usage import (
    TokenUsageBucket,
    get_cost_window_reset,
    get_cost_window_start,
    get_token_window_reset,
    get_token_window_start,
    record_user_usage,
)
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.query_and_chat.token_limit import _token_budget_reset


def _is_rate_limited(
    rate_limits: list[TokenRateLimit],
    usage: list[TokenUsageBucket],
) -> bool:
    return _token_budget_reset(rate_limits, usage) is not None


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


def _usage(token_count: int) -> list[TokenUsageBucket]:
    now = datetime.datetime.now(tz=datetime.timezone.utc)
    return [TokenUsageBucket(window_start=now, tokens=token_count)]


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

    def test_latest_reset_among_exceeded_wins(self) -> None:
        # When several limits are exceeded the reported reset is the max across
        # them, so a retry can't immediately re-trip a limit that clears later.
        # Usage lands in today's bucket, so each limit clears only when its whole
        # window rolls off: the 48h limit binds. Order must not matter.
        now = datetime.datetime.now(datetime.timezone.utc)
        short = TokenRateLimit(
            enabled=True,
            token_budget=1,
            period_hours=24,
            scope=TokenRateLimitScope.GLOBAL,
        )
        long_ = TokenRateLimit(
            enabled=True,
            token_budget=1,
            period_hours=48,
            scope=TokenRateLimitScope.GLOBAL,
        )
        for order in ([short, long_], [long_, short]):
            assert _token_budget_reset(order, _usage(10_000)) == get_token_window_reset(
                now, 48
            )

    def test_thirty_day_token_window_is_unchanged(self) -> None:
        limit = _make_limit(token_budget=1)
        limit.period_hours = 30 * 24
        now = datetime.datetime.now(datetime.timezone.utc)

        assert _is_rate_limited(
            [limit],
            [
                TokenUsageBucket(
                    window_start=now - datetime.timedelta(days=29), tokens=1_000
                )
            ],
        )
        assert not _is_rate_limited(
            [limit],
            [
                TokenUsageBucket(
                    window_start=now - datetime.timedelta(days=31), tokens=1_000
                )
            ],
        )


def _structured_reset_at(
    exc: OnyxError, scope: TokenRateLimitScope
) -> datetime.datetime:
    assert exc.error_code is OnyxErrorCode.RATE_LIMITED
    assert exc.status_code == 429
    assert "usage budget" in exc.detail

    extra = exc.extra or {}
    assert extra["scope"] == scope.value
    reset_at = datetime.datetime.fromisoformat(cast(str, extra["reset_at"]))
    retry_after_seconds = cast(int, extra["retry_after_seconds"])
    assert exc.headers == {"Retry-After": str(retry_after_seconds)}
    return reset_at


def _assert_token_reset(
    exc: OnyxError, scope: TokenRateLimitScope, period_hours: int
) -> None:
    reset_at = _structured_reset_at(exc, scope)
    assert reset_at == get_token_window_reset(
        datetime.datetime.now(tz=datetime.timezone.utc),
        period_hours,
    )


def _assert_cost_reset(
    exc: OnyxError,
    scope: TokenRateLimitScope,
    period_hours: int = 24,
) -> None:
    reset_at = _structured_reset_at(exc, scope)
    expected = get_cost_window_reset(
        datetime.datetime.now(tz=datetime.timezone.utc),
        period_hours,
    )
    assert reset_at == expected


class TestRaiseRateLimited:
    def test_global_scope_shape(self) -> None:
        reset_at = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(
            hours=2
        )
        with pytest.raises(OnyxError) as ei:
            token_limit.raise_rate_limited(TokenRateLimitScope.GLOBAL, reset_at)
        assert _structured_reset_at(ei.value, TokenRateLimitScope.GLOBAL) == reset_at


class TestRaiseForLatestReset:
    """Independent limits report the latest relevant reset."""

    def test_latest_reset_wins(self) -> None:
        now = datetime.datetime.now(datetime.timezone.utc)
        latest = now + datetime.timedelta(hours=24)
        with pytest.raises(OnyxError) as ei:
            token_limit._raise_for_latest_reset(
                TokenRateLimitScope.USER, now + datetime.timedelta(hours=1), latest
            )
        assert _structured_reset_at(ei.value, TokenRateLimitScope.USER) == latest

    def test_skips_none_resets(self) -> None:
        reset_at = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(
            hours=5
        )
        with pytest.raises(OnyxError) as ei:
            token_limit._raise_for_latest_reset(
                TokenRateLimitScope.USER, None, reset_at
            )
        assert _structured_reset_at(ei.value, TokenRateLimitScope.USER) == reset_at

    def test_no_trigger_does_not_raise(self) -> None:
        token_limit._raise_for_latest_reset(TokenRateLimitScope.USER, None, None)


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
        _assert_token_reset(ei.value, TokenRateLimitScope.GLOBAL, 3)

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
    period_hours: int = 24,
    token_budget: int | None = 10**12,
) -> TokenRateLimit:
    limit = TokenRateLimit(
        enabled=True,
        token_budget=token_budget,
        period_hours=period_hours,
        scope=scope,
    )
    limit.cost_budget_cents = cost_budget_cents
    return limit


def _recent_cost_buckets(total: float) -> list[tuple[datetime.datetime, float]]:
    """A single just-now cost bucket, so it lands inside any limit's window."""
    return [(datetime.datetime.now(datetime.timezone.utc), total)]


class TestCostBudgetReset:
    """Unit of the shared cost evaluator (no DB; cost buckets are injected)."""

    def test_current_day_usage_expires_at_full_window(self) -> None:
        # Usage sits in today's (newest) bucket, so a 2-day window only clears
        # once today itself rolls off — the full-window expiry.
        now = datetime.datetime.now(datetime.timezone.utc)
        limit = _cost_limit(100.0, TokenRateLimitScope.USER, period_hours=48)
        assert token_limit._cost_budget_reset(
            [limit], _recent_cost_buckets(150.0)
        ) == get_cost_window_reset(now, 48)

    def test_stale_day_usage_expires_early(self) -> None:
        # The overage is entirely in the oldest day of a 2-day window, so it ages
        # out tomorrow — the exact reset, well before the full-window expiry.
        now = datetime.datetime.now(datetime.timezone.utc)
        limit = _cost_limit(100.0, TokenRateLimitScope.USER, period_hours=48)
        oldest_day = [(get_cost_window_start(now, 48), 150.0)]
        assert token_limit._cost_budget_reset(
            [limit], oldest_day
        ) == get_cost_window_reset(now, 24)

    def test_over_cost_budget_returns_reset(self) -> None:
        limit = _cost_limit(100.0, TokenRateLimitScope.USER)
        assert (
            token_limit._cost_budget_reset([limit], _recent_cost_buckets(150.0))
            is not None
        )

    def test_under_cost_budget_returns_none(self) -> None:
        limit = _cost_limit(100.0, TokenRateLimitScope.USER)
        assert (
            token_limit._cost_budget_reset([limit], _recent_cost_buckets(99.99)) is None
        )

    def test_at_cost_budget_triggers(self) -> None:
        limit = _cost_limit(100.0, TokenRateLimitScope.USER)
        assert (
            token_limit._cost_budget_reset([limit], _recent_cost_buckets(100.0))
            is not None
        )

    def test_row_without_cost_budget_is_exempt(self) -> None:
        # token-only row (cost_budget_cents is None) is never cost-limited
        limit = _cost_limit(None, TokenRateLimitScope.USER)
        assert (
            token_limit._cost_budget_reset([limit], _recent_cost_buckets(10**9)) is None
        )


class TestGlobalCostRejectionPath:
    """CE global path: a global cost budget summed across the tenant raises."""

    def test_over_global_cost_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        limit = _cost_limit(500.0, TokenRateLimitScope.GLOBAL)
        monkeypatch.setattr(
            token_limit, "get_session_with_current_tenant", lambda: _SessionCtx()
        )
        monkeypatch.setattr(
            token_limit, "fetch_all_global_token_rate_limits", lambda **_: [limit]
        )
        # under token budget so only cost can trigger
        monkeypatch.setattr(token_limit, "_fetch_global_usage", lambda *_: _usage(1))
        monkeypatch.setattr(
            token_limit,
            "get_total_cost_cents_buckets_since",
            lambda *_: _recent_cost_buckets(600.0),
        )

        with pytest.raises(OnyxError) as ei:
            token_limit._user_is_rate_limited_by_global()
        _assert_cost_reset(ei.value, TokenRateLimitScope.GLOBAL)

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
        monkeypatch.setattr(
            token_limit,
            "get_total_cost_cents_buckets_since",
            lambda *_: _recent_cost_buckets(100.0),
        )

        token_limit._user_is_rate_limited_by_global()  # no raise

    def test_cost_only_skips_token_aggregation(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A cost-only limit (token_budget=None) must not run the token-usage query.
        limit = TokenRateLimit(
            enabled=True,
            token_budget=None,
            cost_budget_cents=500.0,
            period_hours=24,
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
        monkeypatch.setattr(
            token_limit,
            "get_total_cost_cents_buckets_since",
            lambda *_: _recent_cost_buckets(100.0),
        )

        token_limit._user_is_rate_limited_by_global()  # no raise, no token query

    def test_long_token_window_does_not_widen_cost_query(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        now = datetime.datetime.now(datetime.timezone.utc)
        token_limit_row = _make_limit(token_budget=1)
        token_limit_row.period_hours = 30 * 24
        cost_limit_row = _cost_limit(
            500.0, TokenRateLimitScope.GLOBAL, token_budget=None
        )
        token_cutoffs: list[datetime.datetime] = []
        cost_cutoffs: list[datetime.datetime] = []

        monkeypatch.setattr(
            token_limit, "get_session_with_current_tenant", lambda: _SessionCtx()
        )
        monkeypatch.setattr(
            token_limit,
            "fetch_all_global_token_rate_limits",
            lambda **_: [token_limit_row, cost_limit_row],
        )

        def _fetch_tokens(
            cutoff: datetime.datetime, _session: object
        ) -> list[TokenUsageBucket]:
            token_cutoffs.append(cutoff)
            # Oldest day in the 30-day window: over budget now, ages out tomorrow.
            return [
                TokenUsageBucket(
                    window_start=get_token_window_start(now, 30 * 24), tokens=1_000
                )
            ]

        def _fetch_cost(
            _session: object, cutoff: datetime.datetime
        ) -> list[tuple[datetime.datetime, float]]:
            cost_cutoffs.append(cutoff)
            return [(get_cost_window_start(now, 24), 1.0)]

        monkeypatch.setattr(token_limit, "_fetch_global_usage", _fetch_tokens)
        monkeypatch.setattr(
            token_limit, "get_total_cost_cents_buckets_since", _fetch_cost
        )

        with pytest.raises(OnyxError) as exc_info:
            token_limit._user_is_rate_limited_by_global()

        reset_at = _structured_reset_at(exc_info.value, TokenRateLimitScope.GLOBAL)
        # The lone token bucket is the oldest day in the 30-day window, so it ages
        # out tomorrow: the exact reset, not the 30-day full-window expiry.
        assert reset_at == get_token_window_reset(now, 24)
        assert token_cutoffs == [get_token_window_start(now, 30 * 24)]
        assert cost_cutoffs == [get_cost_window_start(now, 24)]


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
    """The global cost gate reads UTC-day buckets from the real ledger query."""

    def test_current_day_blocks_against_real_ledger(
        self, monkeypatch: pytest.MonkeyPatch, ledger_session: Session
    ) -> None:
        import uuid

        now = datetime.datetime.now(tz=datetime.timezone.utc)
        ledger_window = get_cost_window_start(now, 24)
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
        _assert_cost_reset(ei.value, TokenRateLimitScope.GLOBAL)

    def test_window_rollover_does_not_count(
        self, monkeypatch: pytest.MonkeyPatch, ledger_session: Session
    ) -> None:
        import uuid

        now = datetime.datetime.now(tz=datetime.timezone.utc)
        current = get_cost_window_start(now, 24)
        prior = current - datetime.timedelta(days=1)
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

    def test_cost_period_must_be_whole_days(self) -> None:
        from onyx.server.token_rate_limits.models import TokenRateLimitArgs

        with pytest.raises(ValueError, match="whole UTC days"):
            TokenRateLimitArgs(
                enabled=True,
                token_budget=None,
                period_hours=25,
                cost_budget_cents=500.0,
            )

    def test_token_only_accepted(self) -> None:
        from onyx.server.token_rate_limits.models import TokenRateLimitArgs

        args = TokenRateLimitArgs(enabled=True, token_budget=1000, period_hours=24)
        assert args.token_budget == 1000 and args.cost_budget_cents is None
