"""Resetting a spending limit's usage against real rows: after a reset, a limit
counts exactly the usage recorded after it (per pool, or per user for per-user
limits), stays enforced, keeps its reset and baselines across a card replace,
and stays exact when a member leaves the pool or an admin deletes a user's
usage. The group route resets only a pool of a group the caller manages; the
route permissions themselves are pinned in route_contract_manifest.json."""

from collections.abc import Callable, Generator
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

import ee.onyx.server.query_and_chat.token_limit as ee_token_limit
from ee.onyx.db.token_limit import replace_card_token_rate_limits
from ee.onyx.server.spending_limits.api import (
    _card,
    reset_group_pool_limit_usage,
    reset_spending_limit_usage,
)
from ee.onyx.server.spending_limits.models import SpendingLimitRequest
from onyx.configs.constants import TokenRateLimitPeriod, TokenRateLimitScope
from onyx.db.llm_usage import LLMUsageRecord
from onyx.db.models import (
    TokenRateLimit,
    TokenRateLimitUsageBaseline,
    User,
    User__UserGroup,
    UserGroup,
    UserUsage,
)
from onyx.db.user_usage import (
    get_usage_bucket_start,
    record_user_usage,
    reset_user_usage,
)
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.tracing.flows import LLMFlow
from tests.external_dependency_unit.conftest import create_test_user, delete_test_user

pytestmark = pytest.mark.usefixtures("tenant_context")

_MODEL_NAME = "spend-limit-usage-reset-model"
_POOL = TokenRateLimitScope.USER_GROUP
_MEMBER = TokenRateLimitScope.USER_GROUP_MEMBER
DAILY = TokenRateLimitPeriod.DAILY
WEEKLY = TokenRateLimitPeriod.WEEKLY


class _Created:
    def __init__(self) -> None:
        self.users: list[User] = []
        self.group_ids: list[int] = []
        self.limit_ids: list[int] = []


@pytest.fixture
def created(db_session: Session) -> Generator[_Created, None, None]:
    created = _Created()
    yield created
    db_session.rollback()
    db_session.execute(
        delete(TokenRateLimit).where(
            TokenRateLimit.id.in_(created.limit_ids)
            | TokenRateLimit.user_group_id.in_(created.group_ids)
        )
    )
    db_session.execute(delete(UserUsage).where(UserUsage.model == _MODEL_NAME))
    db_session.execute(
        delete(User__UserGroup).where(
            User__UserGroup.user_group_id.in_(created.group_ids)
        )
    )
    db_session.execute(delete(UserGroup).where(UserGroup.id.in_(created.group_ids)))
    delete_test_user(db_session, *created.users)
    db_session.commit()


def _user(db_session: Session, created: _Created, is_admin: bool = False) -> User:
    user = create_test_user(
        db_session, f"spend-limit-reset-{uuid4().hex[:8]}", is_admin=is_admin
    )
    created.users.append(user)
    return user


def _group(
    db_session: Session, created: _Created, manager: User, *members: User
) -> int:
    group = UserGroup(name=f"spend-limit-reset-{uuid4().hex}", is_up_to_date=True)
    db_session.add(group)
    db_session.flush()
    created.group_ids.append(group.id)
    db_session.add(
        User__UserGroup(user_id=manager.id, user_group_id=group.id, is_manager=True)
    )
    for member in members:
        db_session.add(User__UserGroup(user_id=member.id, user_group_id=group.id))
    manager.is_group_manager = True
    db_session.commit()
    return group.id


def _limit(
    db_session: Session,
    created: _Created,
    scope: TokenRateLimitScope,
    group_id: int | None,
    usage_reset_at: datetime | None = None,
) -> int:
    limit = TokenRateLimit(
        enabled=True,
        cost_budget_cents=100,
        period=DAILY,
        scope=scope,
        user_group_id=group_id,
        usage_reset_at=usage_reset_at,
    )
    db_session.add(limit)
    db_session.commit()
    created.limit_ids.append(limit.id)
    return limit.id


def _spend(db_session: Session, user: User, cost_cents: float) -> None:
    record_user_usage(
        db_session=db_session,
        user_id=str(user.id),
        usage=LLMUsageRecord(
            model=_MODEL_NAME,
            flow=LLMFlow.CHAT_RESPONSE.value,
            provider="spend-limit-usage-reset-provider",
            model_configuration_id=None,
            input_tokens=1,
            output_tokens=1,
            cache_read_tokens=0,
            cost_cents=cost_cents,
            window_start=get_usage_bucket_start(datetime.now(timezone.utc)),
        ),
    )
    db_session.commit()


def _blocked(check: Callable[[UUID, int | None], None], user_id: UUID) -> bool:
    try:
        check(user_id, None)
    except OnyxError as e:
        assert e.error_code is OnyxErrorCode.RATE_LIMITED
        return True
    return False


def _pool_used(db_session: Session, group_id: int) -> float | None:
    return _card(db_session, _POOL, group_id).limits[0].used_cost_cents


def _baselines(db_session: Session, limit_id: int) -> dict[UUID, float]:
    return {
        baseline.user_id: baseline.cost_cents
        for baseline in db_session.scalars(
            select(TokenRateLimitUsageBaseline).where(
                TokenRateLimitUsageBaseline.token_rate_limit_id == limit_id
            )
        )
    }


def _card_limit(
    db_session: Session, scope: TokenRateLimitScope, group_id: int
) -> dict[TokenRateLimitPeriod, TokenRateLimit]:
    db_session.expire_all()
    return {
        limit.period: limit
        for limit in db_session.scalars(
            select(TokenRateLimit).where(
                TokenRateLimit.scope == scope,
                TokenRateLimit.user_group_id == group_id,
            )
        )
    }


def test_pool_counts_only_usage_after_reset(
    db_session: Session, created: _Created
) -> None:
    manager = _user(db_session, created)
    group_id = _group(db_session, created, manager)
    limit_id = _limit(db_session, created, _POOL, group_id)
    by_group = ee_token_limit._user_is_rate_limited_by_group
    _spend(db_session, manager, 150)
    assert _blocked(by_group, manager.id)

    card = reset_group_pool_limit_usage(
        group_id=group_id, limit_id=limit_id, user=manager, db_session=db_session
    )
    assert card.limits[0].used_cost_cents == 0
    assert not _blocked(by_group, manager.id)

    _spend(db_session, manager, 60)
    assert _pool_used(db_session, group_id) == 60
    assert not _blocked(by_group, manager.id)

    # The daily limit stays enforced once usage after the reset fills it.
    _spend(db_session, manager, 40)
    assert _pool_used(db_session, group_id) == 100
    assert _blocked(by_group, manager.id)
    # Usage rows stay for history and exports.
    assert (
        db_session.scalar(
            select(UserUsage.cost_cents).where(UserUsage.user_id == manager.id)
        )
        == 250
    )


def test_pool_still_counts_after_a_member_leaves(
    db_session: Session, created: _Created
) -> None:
    manager = _user(db_session, created)
    leaver = _user(db_session, created)
    group_id = _group(db_session, created, manager, leaver)
    limit_id = _limit(db_session, created, _POOL, group_id)
    by_group = ee_token_limit._user_is_rate_limited_by_group
    _spend(db_session, leaver, 100)
    reset_group_pool_limit_usage(
        group_id=group_id, limit_id=limit_id, user=manager, db_session=db_session
    )

    # The leaver's usage and baseline both leave the pool.
    db_session.execute(
        delete(User__UserGroup).where(
            User__UserGroup.user_id == leaver.id,
            User__UserGroup.user_group_id == group_id,
        )
    )
    db_session.commit()
    _spend(db_session, manager, 60)
    assert _pool_used(db_session, group_id) == 60
    _spend(db_session, manager, 40)
    assert _blocked(by_group, manager.id)


def test_deleting_usage_drops_the_users_baselines(
    db_session: Session, created: _Created
) -> None:
    admin = _user(db_session, created, is_admin=True)
    member = _user(db_session, created)
    group_id = _group(db_session, created, admin, member)
    limit_id = _limit(db_session, created, _MEMBER, group_id)
    per_user = ee_token_limit._user_is_rate_limited
    _spend(db_session, member, 150)
    reset_spending_limit_usage(limit_id=limit_id, _=admin, db_session=db_session)

    reset_user_usage(
        db_session,
        str(member.id),
        get_usage_bucket_start(datetime.now(timezone.utc)),
    )
    db_session.commit()
    assert _baselines(db_session, limit_id) == {}

    # The deleted usage is not subtracted a second time from new usage.
    _spend(db_session, member, 100)
    assert _blocked(per_user, member.id)


def test_per_member_reset_keeps_a_baseline_per_user(
    db_session: Session, created: _Created
) -> None:
    admin = _user(db_session, created, is_admin=True)
    heavy = _user(db_session, created)
    light = _user(db_session, created)
    group_id = _group(db_session, created, admin, heavy, light)
    limit_id = _limit(db_session, created, _MEMBER, group_id)
    per_user = ee_token_limit._user_is_rate_limited
    _spend(db_session, heavy, 150)
    _spend(db_session, light, 20)
    assert _blocked(per_user, heavy.id)

    reset_spending_limit_usage(limit_id=limit_id, _=admin, db_session=db_session)
    assert _baselines(db_session, limit_id) == {heavy.id: 150, light.id: 20}
    assert not _blocked(per_user, heavy.id)

    _spend(db_session, light, 90)
    assert not _blocked(per_user, light.id)
    _spend(db_session, light, 10)
    assert _blocked(per_user, light.id)
    _spend(db_session, heavy, 99)
    assert not _blocked(per_user, heavy.id)


def test_replace_keeps_current_reset_and_baselines(
    db_session: Session, created: _Created
) -> None:
    admin = _user(db_session, created, is_admin=True)
    member = _user(db_session, created)
    group_id = _group(db_session, created, admin, member)
    pool_id = _limit(db_session, created, _POOL, group_id)
    member_id = _limit(db_session, created, _MEMBER, group_id)
    _spend(db_session, member, 30)
    reset_spending_limit_usage(limit_id=pool_id, _=admin, db_session=db_session)
    reset_spending_limit_usage(limit_id=member_id, _=admin, db_session=db_session)
    reset_at = _card_limit(db_session, _POOL, group_id)[DAILY].usage_reset_at
    assert reset_at is not None

    for scope in (_POOL, _MEMBER):
        replace_card_token_rate_limits(
            db_session,
            scope,
            group_id,
            True,
            [
                SpendingLimitRequest(period=DAILY, cost_budget_cents=500),
                SpendingLimitRequest(period=WEEKLY, cost_budget_cents=900),
            ],
        )

    pool = _card_limit(db_session, _POOL, group_id)
    assert pool[DAILY].usage_reset_at == reset_at
    assert pool[DAILY].id != pool_id
    assert _baselines(db_session, pool[DAILY].id) == {member.id: 30}
    assert pool[WEEKLY].usage_reset_at is None
    members = _card_limit(db_session, _MEMBER, group_id)
    assert members[DAILY].id != member_id
    assert _baselines(db_session, members[DAILY].id) == {member.id: 30}
    assert _baselines(db_session, members[WEEKLY].id) == {}


def test_replace_drops_reset_from_earlier_period(
    db_session: Session, created: _Created
) -> None:
    manager = _user(db_session, created)
    group_id = _group(db_session, created, manager)
    today = get_usage_bucket_start(datetime.now(timezone.utc))
    _limit(db_session, created, _POOL, group_id, today - timedelta(hours=1))

    replace_card_token_rate_limits(
        db_session,
        _POOL,
        group_id,
        True,
        [SpendingLimitRequest(period=DAILY, cost_budget_cents=500)],
    )

    assert _card_limit(db_session, _POOL, group_id)[DAILY].usage_reset_at is None


def test_group_route_resets_only_the_managed_pool(
    db_session: Session, created: _Created
) -> None:
    manager = _user(db_session, created)
    other_manager = _user(db_session, created)
    group_id = _group(db_session, created, manager)
    other_group_id = _group(db_session, created, other_manager)
    member_limit_id = _limit(db_session, created, _MEMBER, group_id)
    other_pool_id = _limit(db_session, created, _POOL, other_group_id)

    # A per-member row is not part of the pool, even in the manager's group.
    with pytest.raises(OnyxError) as exc_info:
        reset_group_pool_limit_usage(
            group_id=group_id,
            limit_id=member_limit_id,
            user=manager,
            db_session=db_session,
        )
    assert exc_info.value.error_code is OnyxErrorCode.NOT_FOUND
    db_session.rollback()

    for path_group_id, error_code in (
        (other_group_id, OnyxErrorCode.INSUFFICIENT_PERMISSIONS),
        (group_id, OnyxErrorCode.NOT_FOUND),
    ):
        with pytest.raises(OnyxError) as exc_info:
            reset_group_pool_limit_usage(
                group_id=path_group_id,
                limit_id=other_pool_id,
                user=manager,
                db_session=db_session,
            )
        assert exc_info.value.error_code is error_code
        db_session.rollback()
    assert _card_limit(db_session, _POOL, other_group_id)[DAILY].usage_reset_at is None


def test_unknown_limit_is_not_found(db_session: Session, created: _Created) -> None:
    admin = _user(db_session, created, is_admin=True)
    with pytest.raises(OnyxError) as exc_info:
        reset_spending_limit_usage(
            limit_id=2_000_000_000, _=admin, db_session=db_session
        )
    assert exc_info.value.error_code is OnyxErrorCode.NOT_FOUND
