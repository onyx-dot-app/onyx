"""Enterprise user and group budget enforcement against the usage ledger."""

from collections.abc import Generator
from datetime import datetime, timezone
from typing import NoReturn
from uuid import uuid4

import pytest
from sqlalchemy import delete
from sqlalchemy.orm import Session

import ee.onyx.server.query_and_chat.token_limit as ee_token_limit
from onyx.configs.constants import TokenRateLimitPeriod, TokenRateLimitScope
from onyx.db.llm_usage import LLMUsageRecord
from onyx.db.models import (
    TokenRateLimit,
    User,
    User__UserGroup,
    UserGroup,
    UserUsage,
)
from onyx.db.user_usage import (
    TokenUsageBucket,
    get_period_window_reset,
    get_period_window_start,
    record_user_usage,
)
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.tracing.flows import LLMFlow
from tests.external_dependency_unit.conftest import create_test_user, delete_test_user

pytestmark = pytest.mark.usefixtures("tenant_context")

_TEST_MODEL = "cost-budget-test-model"

_created_users: list[User] = []
_created_group_ids: list[int] = []


@pytest.fixture(autouse=True)
def _remove_created_rows(db_session: Session) -> Generator[None, None, None]:
    """Budget checks read every row in the tenant's usage ledger and limit
    tables, so anything left here trips budget enforcement in later suites
    that share the database."""
    _created_users.clear()
    _created_group_ids.clear()
    yield
    db_session.rollback()
    db_session.execute(
        delete(TokenRateLimit).where(
            TokenRateLimit.user_group_id.in_(_created_group_ids)
        )
    )
    db_session.execute(
        delete(User__UserGroup).where(
            User__UserGroup.user_group_id.in_(_created_group_ids)
        )
    )
    db_session.execute(delete(UserGroup).where(UserGroup.id.in_(_created_group_ids)))
    db_session.execute(delete(UserUsage).where(UserUsage.model == _TEST_MODEL))
    delete_test_user(db_session, *_created_users)
    db_session.commit()


def _create_user(db_session: Session, email_prefix: str) -> User:
    user = create_test_user(db_session, email_prefix)
    _created_users.append(user)
    return user


def _cost_limit(
    scope: TokenRateLimitScope,
    period: TokenRateLimitPeriod = TokenRateLimitPeriod.DAILY,
) -> TokenRateLimit:
    return TokenRateLimit(
        enabled=True,
        token_budget=None,
        cost_budget_cents=100.0,
        period=period,
        scope=scope,
    )


def _record_cost(db_session: Session, user: User, cost_cents: float) -> None:
    window_start = get_period_window_start(
        datetime.now(timezone.utc), TokenRateLimitPeriod.DAILY
    )
    record_user_usage(
        db_session=db_session,
        user_id=str(user.id),
        usage=LLMUsageRecord(
            model=_TEST_MODEL,
            flow=LLMFlow.CHAT_RESPONSE.value,
            provider=None,
            model_configuration_id=None,
            input_tokens=1,
            output_tokens=1,
            cache_read_tokens=0,
            cost_cents=cost_cents,
            window_start=window_start,
        ),
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
    period: TokenRateLimitPeriod,
) -> None:
    _assert_rate_limited(error, scope)
    assert error.extra is not None
    assert datetime.fromisoformat(str(error.extra["reset_at"])) == (
        get_period_window_reset(datetime.now(timezone.utc), period)
    )


def test_user_cost_isolated_and_longest_window_reported(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = _create_user(db_session, "cost_budget_user")
    other_user = _create_user(db_session, "cost_budget_other")
    limits = [
        _cost_limit(TokenRateLimitScope.USER, TokenRateLimitPeriod.DAILY),
        _cost_limit(TokenRateLimitScope.USER, TokenRateLimitPeriod.WEEKLY),
    ]
    monkeypatch.setattr(
        ee_token_limit, "fetch_enforced_token_rate_limits", lambda *_: limits
    )
    monkeypatch.setattr(
        ee_token_limit, "get_user_token_buckets_since", _fail_token_query
    )

    _record_cost(db_session, user, 50.0)
    _record_cost(db_session, other_user, 1_000.0)
    ee_token_limit._user_is_rate_limited(user.id, None)

    _record_cost(db_session, user, 50.0)
    with pytest.raises(OnyxError) as exc_info:
        ee_token_limit._user_is_rate_limited(user.id, None)
    _assert_cost_rate_limited(
        exc_info.value,
        TokenRateLimitScope.USER,
        period=TokenRateLimitPeriod.WEEKLY,
    )


def _create_group(db_session: Session, name: str) -> UserGroup:
    group = UserGroup(name=f"{name}-{uuid4().hex}", is_up_to_date=True)
    db_session.add(group)
    db_session.flush()
    _created_group_ids.append(group.id)
    return group


def _add_group_limit(
    db_session: Session, group: UserGroup, period: TokenRateLimitPeriod
) -> None:
    limit = _cost_limit(TokenRateLimitScope.USER_GROUP, period)
    limit.user_group_id = group.id
    db_session.add(limit)


def test_group_blocks_only_when_every_group_is_over_budget(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = _create_user(db_session, "group_budget_user")
    spender = _create_user(db_session, "group_budget_spender")
    over_budget_group = _create_group(db_session, "over-budget")
    under_budget_group = _create_group(db_session, "under-budget")
    db_session.add_all(
        [
            User__UserGroup(user_id=user.id, user_group_id=over_budget_group.id),
            User__UserGroup(user_id=user.id, user_group_id=under_budget_group.id),
            User__UserGroup(user_id=spender.id, user_group_id=over_budget_group.id),
        ]
    )
    _add_group_limit(db_session, over_budget_group, TokenRateLimitPeriod.WEEKLY)
    _add_group_limit(db_session, under_budget_group, TokenRateLimitPeriod.DAILY)
    db_session.commit()
    _record_cost(db_session, spender, 150.0)
    monkeypatch.setattr(
        ee_token_limit, "get_group_token_buckets_since", _fail_token_query
    )

    ee_token_limit._user_is_rate_limited_by_group(user.id, None)

    db_session.execute(
        delete(User__UserGroup).where(
            User__UserGroup.user_id == user.id,
            User__UserGroup.user_group_id == under_budget_group.id,
        )
    )
    db_session.commit()
    with pytest.raises(OnyxError) as exc_info:
        ee_token_limit._user_is_rate_limited_by_group(user.id, None)
    _assert_cost_rate_limited(
        exc_info.value,
        TokenRateLimitScope.USER_GROUP,
        period=TokenRateLimitPeriod.WEEKLY,
    )


def test_user_token_limit_resets_at_window_end(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = _create_user(db_session, "token_budget_user")
    limit = TokenRateLimit(
        enabled=True,
        token_budget=1,
        cost_budget_cents=None,
        period=TokenRateLimitPeriod.DAILY,
        scope=TokenRateLimitScope.USER,
    )
    monkeypatch.setattr(
        ee_token_limit,
        "fetch_enforced_token_rate_limits",
        lambda *_: [limit],
    )
    monkeypatch.setattr(
        ee_token_limit,
        "get_user_token_buckets_since",
        lambda *_: [
            TokenUsageBucket(
                window_start=datetime.now(timezone.utc),
                tokens=1_000,
            )
        ],
    )

    with pytest.raises(OnyxError) as exc_info:
        ee_token_limit._user_is_rate_limited(user.id, None)
    _assert_rate_limited(exc_info.value, TokenRateLimitScope.USER)
    assert exc_info.value.extra is not None
    assert datetime.fromisoformat(str(exc_info.value.extra["reset_at"])) == (
        get_period_window_reset(datetime.now(timezone.utc), TokenRateLimitPeriod.DAILY)
    )
