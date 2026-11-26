"""The Usage tab budget against real limit rows: it considers only the scopes
that hold the caller, so a service account in a pooled group sees the pool
and never a per-user allowance, while a person in the same group still sees
the most binding of allowance and pool."""

from collections.abc import Generator
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import delete
from sqlalchemy.orm import Session

from onyx.configs.constants import TokenRateLimitPeriod, TokenRateLimitScope
from onyx.db.enums import AccountType
from onyx.db.llm_usage import LLMUsageRecord
from onyx.db.models import (
    TokenRateLimit,
    User,
    User__UserGroup,
    UserGroup,
    UserUsage,
)
from onyx.db.user_usage import get_period_window_start, record_user_usage
from onyx.server.features.usage.api import _user_cost_budget, get_my_usage
from onyx.server.query_and_chat.token_limit import spend_limit_scopes
from onyx.tracing.flows import LLMFlow
from tests.external_dependency_unit.conftest import create_test_user, delete_test_user

pytestmark = pytest.mark.usefixtures("tenant_context")

_MODEL_NAME = "usage-budget-scopes-model"
DAILY = TokenRateLimitPeriod.DAILY

_POOL_CENTS = 100.0
_DEFAULT_CENTS = 5.0
_MEMBER_CENTS = 10.0


class _Pooled:
    def __init__(self, service: User, person: User) -> None:
        self.service = service
        self.person = person


def _limit(
    db_session: Session,
    limit_ids: list[int],
    scope: TokenRateLimitScope,
    cost_cents: float,
    group_id: int | None = None,
) -> None:
    limit = TokenRateLimit(
        enabled=True,
        cost_budget_cents=cost_cents,
        period=DAILY,
        scope=scope,
        user_group_id=group_id,
    )
    db_session.add(limit)
    db_session.commit()
    limit_ids.append(limit.id)


def _spend(db_session: Session, user: User, cost_cents: float) -> None:
    record_user_usage(
        db_session=db_session,
        user_id=str(user.id),
        usage=LLMUsageRecord(
            model=_MODEL_NAME,
            flow=LLMFlow.CHAT_RESPONSE.value,
            provider=None,
            model_configuration_id=None,
            input_tokens=1,
            output_tokens=1,
            cache_read_tokens=0,
            cost_cents=cost_cents,
            window_start=get_period_window_start(datetime.now(timezone.utc), DAILY),
        ),
    )
    db_session.commit()


@pytest.fixture
def pooled(db_session: Session) -> Generator[_Pooled, None, None]:
    """A service account and a person in one group with a cost pool, a
    per-member allowance, and a workspace per-user default. Limits apply
    tenant-wide, so every row added here is removed afterwards."""
    service = create_test_user(
        db_session,
        "usage-scopes-service",
        account_type=AccountType.SERVICE_ACCOUNT,
        assign_default_group=False,
    )
    person = create_test_user(db_session, "usage-scopes-person")
    group = UserGroup(name=f"usage-scopes-{uuid4().hex}", is_up_to_date=True)
    db_session.add(group)
    db_session.flush()
    for member in (service, person):
        db_session.add(User__UserGroup(user_id=member.id, user_group_id=group.id))
    db_session.commit()

    limit_ids: list[int] = []
    _limit(db_session, limit_ids, TokenRateLimitScope.USER_GROUP, _POOL_CENTS, group.id)
    _limit(
        db_session,
        limit_ids,
        TokenRateLimitScope.USER_GROUP_MEMBER,
        _MEMBER_CENTS,
        group.id,
    )
    _limit(db_session, limit_ids, TokenRateLimitScope.USER, _DEFAULT_CENTS)

    yield _Pooled(service, person)

    db_session.rollback()
    db_session.execute(delete(TokenRateLimit).where(TokenRateLimit.id.in_(limit_ids)))
    db_session.execute(delete(UserUsage).where(UserUsage.model == _MODEL_NAME))
    db_session.execute(
        delete(User__UserGroup).where(User__UserGroup.user_group_id == group.id)
    )
    db_session.execute(delete(UserGroup).where(UserGroup.id == group.id))
    delete_test_user(db_session, service, person)
    db_session.commit()


def test_service_account_sees_its_group_pool(
    db_session: Session, pooled: _Pooled
) -> None:
    # Over both the default and the member allowance; only the pool holds it.
    _spend(db_session, pooled.service, 20)

    budget = _user_cost_budget(
        db_session, str(pooled.service.id), spend_limit_scopes(pooled.service)
    )

    assert budget is not None
    assert (budget.budget_cents, budget.remaining_cents) == (_POOL_CENTS, 80)


def test_usage_endpoint_shows_a_service_account_its_pool(
    db_session: Session, pooled: _Pooled
) -> None:
    _spend(db_session, pooled.service, 20)

    usage = get_my_usage(
        days=None, start=None, end=None, user=pooled.service, db_session=db_session
    )

    assert (usage.budget_cents, usage.budget_remaining_cents) == (_POOL_CENTS, 80)


def test_workspace_pool_scope_alone_has_no_budget_without_a_workspace_pool(
    db_session: Session, pooled: _Pooled
) -> None:
    _spend(db_session, pooled.service, 20)

    budget = _user_cost_budget(
        db_session, str(pooled.service.id), frozenset({TokenRateLimitScope.GLOBAL})
    )

    assert budget is None


def test_person_in_the_group_sees_the_most_binding_budget(
    db_session: Session, pooled: _Pooled
) -> None:
    _spend(db_session, pooled.service, 20)
    _spend(db_session, pooled.person, 3)

    # The member allowance (10, 7 left) binds before the pool (100, 77 left).
    expected = (_MEMBER_CENTS, 7)
    for budget in (
        _user_cost_budget(db_session, str(pooled.person.id)),
        _user_cost_budget(
            db_session, str(pooled.person.id), spend_limit_scopes(pooled.person)
        ),
    ):
        assert budget is not None
        assert (budget.budget_cents, budget.remaining_cents) == expected
