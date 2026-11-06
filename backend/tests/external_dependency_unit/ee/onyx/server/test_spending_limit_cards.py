"""Spending limit cards against real rows: a card replace on a missing group
returns NOT_FOUND, a card with mixed enabled rows reads as enabled and lists
only its enabled rows, and cost budgets stay inside what the column stores."""

from collections.abc import Generator
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import delete
from sqlalchemy.orm import Session

from ee.onyx.db.token_limit import replace_card_token_rate_limits
from ee.onyx.server.spending_limits.api import _card
from ee.onyx.server.spending_limits.models import (
    MAX_COST_BUDGET_CENTS,
    MIN_COST_BUDGET_CENTS,
    SpendingLimitRequest,
)
from onyx.configs.constants import TokenRateLimitPeriod, TokenRateLimitScope
from onyx.db.models import TokenRateLimit, UserGroup
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError

pytestmark = pytest.mark.usefixtures("tenant_context")

_MEMBER = TokenRateLimitScope.USER_GROUP_MEMBER


@pytest.fixture
def group_id(db_session: Session) -> Generator[int, None, None]:
    group = UserGroup(name=f"spending-limit-card-{uuid4().hex}", is_up_to_date=True)
    db_session.add(group)
    db_session.commit()
    yield group.id
    db_session.rollback()
    db_session.execute(
        delete(TokenRateLimit).where(TokenRateLimit.user_group_id == group.id)
    )
    db_session.execute(delete(UserGroup).where(UserGroup.id == group.id))
    db_session.commit()


def _add(
    db_session: Session, group_id: int, period: TokenRateLimitPeriod, enabled: bool
) -> None:
    db_session.add(
        TokenRateLimit(
            enabled=enabled,
            cost_budget_cents=100,
            period=period,
            scope=_MEMBER,
            user_group_id=group_id,
        )
    )
    db_session.commit()


def test_replace_card_on_missing_group_is_not_found(
    db_session: Session, group_id: int
) -> None:
    with pytest.raises(OnyxError) as exc_info:
        replace_card_token_rate_limits(
            db_session,
            _MEMBER,
            group_id + 1_000_000,
            True,
            [
                SpendingLimitRequest(
                    period=TokenRateLimitPeriod.DAILY, cost_budget_cents=100
                )
            ],
        )
    assert exc_info.value.error_code is OnyxErrorCode.NOT_FOUND


def test_card_with_any_enabled_row_lists_only_enabled_rows(
    db_session: Session, group_id: int
) -> None:
    _add(db_session, group_id, TokenRateLimitPeriod.DAILY, enabled=False)
    _add(db_session, group_id, TokenRateLimitPeriod.WEEKLY, enabled=False)
    card = _card(db_session, _MEMBER, group_id)
    assert not card.enabled
    assert len(card.limits) == 2

    _add(db_session, group_id, TokenRateLimitPeriod.MONTHLY, enabled=True)
    card = _card(db_session, _MEMBER, group_id)
    assert card.enabled
    assert [limit.period for limit in card.limits] == [TokenRateLimitPeriod.MONTHLY]


@pytest.mark.parametrize(
    "cost_budget_cents", [MIN_COST_BUDGET_CENTS / 2, MAX_COST_BUDGET_CENTS * 2]
)
def test_cost_budget_outside_stored_range_is_rejected(
    cost_budget_cents: float,
) -> None:
    with pytest.raises(ValidationError):
        SpendingLimitRequest(
            period=TokenRateLimitPeriod.DAILY, cost_budget_cents=cost_budget_cents
        )
