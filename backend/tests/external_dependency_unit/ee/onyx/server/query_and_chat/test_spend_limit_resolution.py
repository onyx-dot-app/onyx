"""Spending limit resolution against real limit rows and usage: the largest
group allowance per (period, unit) with the workspace default filling gaps,
group pools that never block across groups, limits on one model, and
ALERT_ONLY rows that never block."""

from collections.abc import Generator
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import delete
from sqlalchemy.orm import Session

import ee.onyx.server.query_and_chat.token_limit as ee_token_limit
from onyx.configs.constants import (
    TokenRateLimitAction,
    TokenRateLimitPeriod,
    TokenRateLimitScope,
)
from onyx.db.llm_usage import LLMUsageRecord
from onyx.db.models import (
    LLMProvider,
    ModelConfiguration,
    TokenRateLimit,
    User,
    User__UserGroup,
    UserGroup,
    UserUsage,
)
from onyx.db.token_limit import (
    fetch_enforced_token_rate_limits,
    fetch_user_group_enforced_token_rate_limits,
)
from onyx.db.user_usage import get_period_window_start, record_user_usage
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.query_and_chat.token_limit import (
    BudgetUnit,
    _user_is_rate_limited_by_global,
    resolve_member_allowance,
)
from onyx.tracing.flows import LLMFlow
from tests.external_dependency_unit.conftest import create_test_user, delete_test_user

pytestmark = pytest.mark.usefixtures("tenant_context")

_MODEL_NAME = "spend-limit-resolution-model"
_PROVIDER_TYPE = "spend-limit-resolution-provider"

DAILY = TokenRateLimitPeriod.DAILY
WEEKLY = TokenRateLimitPeriod.WEEKLY
MONTHLY = TokenRateLimitPeriod.MONTHLY


class _Created:
    def __init__(self) -> None:
        self.users: list[User] = []
        self.group_ids: list[int] = []
        self.provider_ids: list[int] = []
        self.limit_ids: list[int] = []


@pytest.fixture
def created(db_session: Session) -> Generator[_Created, None, None]:
    """Limits apply tenant-wide, so every row a test adds goes before the next
    suite runs."""
    created = _Created()
    yield created
    db_session.rollback()
    db_session.execute(
        delete(TokenRateLimit).where(TokenRateLimit.id.in_(created.limit_ids))
    )
    db_session.execute(delete(UserUsage).where(UserUsage.model == _MODEL_NAME))
    db_session.execute(
        delete(User__UserGroup).where(
            User__UserGroup.user_group_id.in_(created.group_ids)
        )
    )
    db_session.execute(delete(UserGroup).where(UserGroup.id.in_(created.group_ids)))
    db_session.execute(
        delete(LLMProvider).where(LLMProvider.id.in_(created.provider_ids))
    )
    delete_test_user(db_session, *created.users)
    db_session.commit()


def _user(db_session: Session, created: _Created) -> User:
    user = create_test_user(db_session, f"spend-limit-{uuid4().hex[:8]}")
    created.users.append(user)
    return user


def _group(db_session: Session, created: _Created, *members: User) -> int:
    group = UserGroup(name=f"spend-limit-{uuid4().hex}", is_up_to_date=True)
    db_session.add(group)
    db_session.flush()
    created.group_ids.append(group.id)
    for member in members:
        db_session.add(User__UserGroup(user_id=member.id, user_group_id=group.id))
    db_session.commit()
    return group.id


def _model(db_session: Session, created: _Created) -> int:
    """A configuration on its own provider: two of these share (model, provider
    type) and differ only by id."""
    provider = LLMProvider(name=f"spend-limit-{uuid4().hex}", provider=_PROVIDER_TYPE)
    db_session.add(provider)
    db_session.flush()
    created.provider_ids.append(provider.id)
    model = ModelConfiguration(
        llm_provider_id=provider.id, name=_MODEL_NAME, is_visible=True
    )
    db_session.add(model)
    db_session.commit()
    return model.id


def _limit(
    db_session: Session,
    created: _Created,
    scope: TokenRateLimitScope,
    period: TokenRateLimitPeriod,
    cost_cents: float,
    *,
    group_id: int | None = None,
    model_configuration_id: int | None = None,
    action: TokenRateLimitAction = TokenRateLimitAction.BLOCK,
) -> None:
    limit = TokenRateLimit(
        enabled=True,
        cost_budget_cents=cost_cents,
        period=period,
        scope=scope,
        user_group_id=group_id,
        model_configuration_id=model_configuration_id,
        action=action,
    )
    db_session.add(limit)
    db_session.commit()
    created.limit_ids.append(limit.id)


def _spend(
    db_session: Session,
    user: User,
    cost_cents: float,
    model_configuration_id: int | None = None,
) -> None:
    record_user_usage(
        db_session=db_session,
        user_id=str(user.id),
        usage=LLMUsageRecord(
            model=_MODEL_NAME,
            flow=LLMFlow.CHAT_RESPONSE.value,
            provider=_PROVIDER_TYPE,
            model_configuration_id=model_configuration_id,
            input_tokens=1,
            output_tokens=1,
            cache_read_tokens=0,
            cost_cents=cost_cents,
            window_start=get_period_window_start(datetime.now(timezone.utc), DAILY),
        ),
    )
    db_session.commit()


def _blocked_scope(
    user: User, model_configuration_id: int | None = None
) -> TokenRateLimitScope | None:
    """The scope that blocks the user, or None. Runs the three checks in turn
    so a test sees which one fired."""
    checks = [
        lambda: ee_token_limit._user_is_rate_limited(user.id, model_configuration_id),
        lambda: ee_token_limit._user_is_rate_limited_by_group(
            user.id, model_configuration_id
        ),
        lambda: _user_is_rate_limited_by_global(model_configuration_id),
    ]
    for check in checks:
        try:
            check()
        except OnyxError as e:
            assert e.error_code is OnyxErrorCode.RATE_LIMITED
            assert e.extra is not None
            return TokenRateLimitScope(e.extra["scope"])
    return None


def test_largest_group_allowance_wins_per_bucket(
    db_session: Session, created: _Created
) -> None:
    user = _user(db_session, created)
    group_a = _group(db_session, created, user)
    group_b = _group(db_session, created, user)
    member = TokenRateLimitScope.USER_GROUP_MEMBER
    _limit(db_session, created, member, DAILY, 10, group_id=group_a)
    _limit(db_session, created, member, MONTHLY, 200, group_id=group_a)
    _limit(db_session, created, member, MONTHLY, 300, group_id=group_b)
    _limit(db_session, created, TokenRateLimitScope.USER, DAILY, 5)
    _limit(db_session, created, TokenRateLimitScope.USER, WEEKLY, 50)

    allowance = resolve_member_allowance(
        list(fetch_enforced_token_rate_limits(db_session, TokenRateLimitScope.USER)),
        fetch_user_group_enforced_token_rate_limits(db_session, user.id, member),
    )
    budgets = {
        window.period: (window.budget, window.user_group_id)
        for window in allowance
        if window.unit == BudgetUnit.COST
    }
    assert budgets == {
        DAILY: (10, group_a),
        WEEKLY: (50, None),
        MONTHLY: (300, group_b),
    }

    # The group's daily 10 replaces the default's 5, up and not only down.
    _spend(db_session, user, 9)
    assert _blocked_scope(user) is None
    _spend(db_session, user, 1)
    assert _blocked_scope(user) == member


def test_group_allowance_below_the_default_still_overrides_it(
    db_session: Session, created: _Created
) -> None:
    user = _user(db_session, created)
    group = _group(db_session, created, user)
    _limit(db_session, created, TokenRateLimitScope.USER, DAILY, 100)
    member = TokenRateLimitScope.USER_GROUP_MEMBER
    _limit(db_session, created, member, DAILY, 10, group_id=group)

    _spend(db_session, user, 10)
    assert _blocked_scope(user) == member


def test_group_pools_never_block_across_groups(
    db_session: Session, created: _Created
) -> None:
    user = _user(db_session, created)
    teammate = _user(db_session, created)
    pool = TokenRateLimitScope.USER_GROUP
    exhausted = _group(db_session, created, user, teammate)
    roomy = _group(db_session, created, user)
    model_only = _group(db_session, created, user)
    model_id = _model(db_session, created)
    _limit(db_session, created, pool, DAILY, 10, group_id=exhausted)
    _limit(db_session, created, pool, DAILY, 100, group_id=roomy)
    # Has no all-models pool, so it has no say in the all-models check.
    _limit(
        db_session,
        created,
        pool,
        DAILY,
        1,
        group_id=model_only,
        model_configuration_id=model_id,
    )

    _spend(db_session, teammate, 50)
    assert _blocked_scope(user) is None

    _spend(db_session, user, 100)
    assert _blocked_scope(user) == pool


def test_model_limit_blocks_only_its_model(
    db_session: Session, created: _Created
) -> None:
    user = _user(db_session, created)
    limited = _model(db_session, created)
    # Same model name and provider type, different configuration.
    twin = _model(db_session, created)
    _limit(
        db_session,
        created,
        TokenRateLimitScope.GLOBAL,
        DAILY,
        10,
        model_configuration_id=limited,
    )

    _spend(db_session, user, 50, model_configuration_id=twin)
    assert _blocked_scope(user, limited) is None

    _spend(db_session, user, 10, model_configuration_id=limited)
    with pytest.raises(OnyxError) as exc_info:
        _user_is_rate_limited_by_global(limited)
    assert exc_info.value.extra is not None
    assert exc_info.value.extra["model"] == _MODEL_NAME
    assert _blocked_scope(user, twin) is None
    assert _blocked_scope(user) is None


def test_model_usage_counts_toward_all_models_limits(
    db_session: Session, created: _Created
) -> None:
    user = _user(db_session, created)
    model_id = _model(db_session, created)
    _limit(db_session, created, TokenRateLimitScope.USER, DAILY, 10)

    _spend(db_session, user, 10, model_configuration_id=model_id)
    assert _blocked_scope(user) == TokenRateLimitScope.USER


def test_alert_only_limits_never_block_or_win(
    db_session: Session, created: _Created
) -> None:
    user = _user(db_session, created)
    group = _group(db_session, created, user)
    alert = TokenRateLimitAction.ALERT_ONLY
    member = TokenRateLimitScope.USER_GROUP_MEMBER
    _limit(db_session, created, TokenRateLimitScope.USER, DAILY, 1, action=alert)
    _limit(db_session, created, member, DAILY, 10, group_id=group)
    _limit(db_session, created, member, DAILY, 1_000, group_id=group, action=alert)

    _spend(db_session, user, 5)
    assert _blocked_scope(user) is None

    # The alert row's larger value does not lift the group's block limit.
    _spend(db_session, user, 5)
    assert _blocked_scope(user) == member
