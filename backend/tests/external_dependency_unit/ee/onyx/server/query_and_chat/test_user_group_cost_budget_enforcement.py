"""Enterprise user and group budget enforcement against the usage ledger."""

from datetime import datetime, timezone
from typing import NoReturn
from uuid import uuid4

import pytest
from sqlalchemy import delete
from sqlalchemy.orm import Session

import ee.onyx.server.query_and_chat.token_limit as ee_token_limit
from onyx.configs.constants import TokenRateLimitScope
from onyx.db.models import (
    TokenRateLimit,
    TokenRateLimit__UserGroup,
    User,
    User__UserGroup,
    UserGroup,
)
from onyx.db.user_usage import (
    TokenUsageBucket,
    get_cost_window_reset,
    get_cost_window_start,
    get_token_window_reset,
    record_user_usage,
)
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.tracing.flows import LLMFlow
from tests.external_dependency_unit.conftest import create_test_user

pytestmark = pytest.mark.usefixtures("tenant_context")

_TEST_MODEL = "cost-budget-test-model"


def _cost_limit(scope: TokenRateLimitScope, period_hours: int = 24) -> TokenRateLimit:
    return TokenRateLimit(
        enabled=True,
        token_budget=None,
        cost_budget_cents=100.0,
        period_hours=period_hours,
        scope=scope,
    )


def _record_cost(db_session: Session, user: User, cost_cents: float) -> None:
    window_start = get_cost_window_start(datetime.now(timezone.utc), 24)
    record_user_usage(
        db_session=db_session,
        user_id=str(user.id),
        model=_TEST_MODEL,
        flow=LLMFlow.CHAT_RESPONSE.value,
        provider=None,
        input_tokens=1,
        output_tokens=1,
        cache_read_tokens=0,
        cost_cents=cost_cents,
        window_start=window_start,
    )
    db_session.commit()


def _fail_token_query(*_args: object) -> NoReturn:
    raise AssertionError("cost-only enforcement queried token usage")


def _assert_rate_limited(error: OnyxError, scope: TokenRateLimitScope) -> None:
    assert error.error_code is OnyxErrorCode.RATE_LIMITED
    assert error.extra is not None
    assert error.extra["scope"] == scope.value


def _assert_cost_rate_limited(
    error: OnyxError,
    scope: TokenRateLimitScope,
    period_hours: int,
) -> None:
    _assert_rate_limited(error, scope)
    assert error.extra is not None
    assert datetime.fromisoformat(str(error.extra["reset_at"])) == (
        get_cost_window_reset(
            datetime.now(timezone.utc),
            period_hours,
        )
    )


def test_user_cost_isolated_and_longest_window_reported(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = create_test_user(db_session, "cost_budget_user")
    other_user = create_test_user(db_session, "cost_budget_other")
    limits = [
        _cost_limit(TokenRateLimitScope.USER, period_hours=24),
        _cost_limit(TokenRateLimitScope.USER, period_hours=48),
    ]
    monkeypatch.setattr(
        ee_token_limit, "fetch_all_user_token_rate_limits", lambda **_: limits
    )
    monkeypatch.setattr(ee_token_limit, "_fetch_user_usage", _fail_token_query)

    _record_cost(db_session, user, 50.0)
    _record_cost(db_session, other_user, 1_000.0)
    ee_token_limit._user_is_rate_limited(user.id)

    _record_cost(db_session, user, 50.0)
    with pytest.raises(OnyxError) as exc_info:
        ee_token_limit._user_is_rate_limited(user.id)
    _assert_cost_rate_limited(
        exc_info.value,
        TokenRateLimitScope.USER,
        period_hours=48,
    )


def _create_group(db_session: Session, name: str) -> UserGroup:
    group = UserGroup(name=f"{name}-{uuid4().hex}", is_up_to_date=True)
    db_session.add(group)
    db_session.flush()
    return group


def _add_group_limit(
    db_session: Session, group: UserGroup, period_hours: int = 1
) -> None:
    limit = _cost_limit(TokenRateLimitScope.USER_GROUP, period_hours)
    db_session.add(limit)
    db_session.flush()
    db_session.add(
        TokenRateLimit__UserGroup(
            rate_limit_id=limit.id,
            user_group_id=group.id,
        )
    )


def test_group_blocks_only_when_every_group_is_over_budget(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = create_test_user(db_session, "group_budget_user")
    spender = create_test_user(db_session, "group_budget_spender")
    over_budget_group = _create_group(db_session, "over-budget")
    under_budget_group = _create_group(db_session, "under-budget")
    db_session.add_all(
        [
            User__UserGroup(user_id=user.id, user_group_id=over_budget_group.id),
            User__UserGroup(user_id=user.id, user_group_id=under_budget_group.id),
            User__UserGroup(user_id=spender.id, user_group_id=over_budget_group.id),
        ]
    )
    _add_group_limit(db_session, over_budget_group, period_hours=48)
    _add_group_limit(db_session, under_budget_group, period_hours=24)
    db_session.commit()
    _record_cost(db_session, spender, 150.0)
    monkeypatch.setattr(ee_token_limit, "_fetch_user_group_usage", _fail_token_query)

    ee_token_limit._user_is_rate_limited_by_group(user.id)

    db_session.execute(
        delete(User__UserGroup).where(
            User__UserGroup.user_id == user.id,
            User__UserGroup.user_group_id == under_budget_group.id,
        )
    )
    db_session.commit()
    with pytest.raises(OnyxError) as exc_info:
        ee_token_limit._user_is_rate_limited_by_group(user.id)
    _assert_cost_rate_limited(
        exc_info.value,
        TokenRateLimitScope.USER_GROUP,
        period_hours=48,
    )


def test_user_token_limit_behavior_is_unchanged(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = create_test_user(db_session, "token_budget_user")
    limit = TokenRateLimit(
        enabled=True,
        token_budget=1,
        cost_budget_cents=None,
        period_hours=2,
        scope=TokenRateLimitScope.USER,
    )
    monkeypatch.setattr(
        ee_token_limit,
        "fetch_all_user_token_rate_limits",
        lambda **_: [limit],
    )
    monkeypatch.setattr(
        ee_token_limit,
        "_fetch_user_usage",
        lambda *_: [
            TokenUsageBucket(
                window_start=datetime.now(timezone.utc),
                tokens=1_000,
            )
        ],
    )

    with pytest.raises(OnyxError) as exc_info:
        ee_token_limit._user_is_rate_limited(user.id)
    _assert_rate_limited(exc_info.value, TokenRateLimitScope.USER)
    assert exc_info.value.extra is not None
    assert datetime.fromisoformat(str(exc_info.value.extra["reset_at"])) == (
        get_token_window_reset(
            datetime.now(timezone.utc),
            2,
        )
    )
