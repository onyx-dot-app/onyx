from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from onyx.auth.users import current_user
from onyx.db.engine.sql_engine import get_session
from onyx.db.models import TokenRateLimit, User
from onyx.db.token_limit import (
    fetch_all_global_token_rate_limits,
    fetch_all_user_token_rate_limits,
    fetch_user_group_token_rate_limits,
)
from onyx.db.user_usage import (
    TokenUsageBucket,
    get_token_window_start,
    get_total_token_buckets_since,
    get_user_token_buckets_since,
)
from onyx.server.query_and_chat.token_limit import TOKEN_BUDGET_UNIT

router = APIRouter(prefix="/token-budget", tags=["token-budget"])


class TokenBudgetResponse(BaseModel):
    tokens_used: int
    token_budget: int | None
    period_hours: int
    enabled: bool


def _sum_buckets(buckets: list[TokenUsageBucket], cutoff: datetime) -> int:
    return int(sum(b.tokens for b in buckets if b.window_start >= cutoff))


def _with_token_budget(limits: list[TokenRateLimit]) -> list[TokenRateLimit]:
    return [
        limit
        for limit in limits
        if limit.token_budget is not None and limit.token_budget > 0
    ]


@router.get("")
def get_token_budget_status(
    db_session: Session = Depends(get_session),
    user: User = Depends(current_user),
) -> TokenBudgetResponse:
    now = datetime.now(timezone.utc)
    user_id = str(user.id)

    group_limits_by_group = fetch_user_group_token_rate_limits(
        db_session=db_session, user_id=user.id, enabled_only=True
    )

    scopes = [
        (
            _with_token_budget(
                fetch_all_user_token_rate_limits(db_session, enabled_only=True)
            ),
            min,
            user_id,
        ),
        (
            _with_token_budget(
                [limit for limits in group_limits_by_group.values() for limit in limits]
            ),
            max,
            user_id,
        ),
        (
            _with_token_budget(
                fetch_all_global_token_rate_limits(db_session, enabled_only=True)
            ),
            min,
            None,
        ),
    ]

    for limits, pick, scope_user_id in scopes:
        if not limits:
            continue

        active_limit = pick(limits, key=lambda limit: limit.token_budget)
        cutoff = get_token_window_start(now, active_limit.period_hours)
        if scope_user_id:
            buckets = get_user_token_buckets_since(
                db_session=db_session, user_id=scope_user_id, cutoff=cutoff
            )
        else:
            buckets = get_total_token_buckets_since(
                db_session=db_session, cutoff=cutoff
            )

        return TokenBudgetResponse(
            tokens_used=_sum_buckets(buckets, cutoff),
            token_budget=active_limit.token_budget * TOKEN_BUDGET_UNIT,
            period_hours=active_limit.period_hours,
            enabled=True,
        )

    return TokenBudgetResponse(
        tokens_used=0,
        token_budget=None,
        period_hours=168,
        enabled=False,
    )
