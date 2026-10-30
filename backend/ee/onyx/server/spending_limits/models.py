from datetime import datetime
from typing import Self

from pydantic import BaseModel, Field, model_validator

from onyx.configs.constants import (
    TokenRateLimitAction,
    TokenRateLimitPeriod,
    TokenRateLimitScope,
)
from onyx.server.query_and_chat.token_limit import BudgetUnit
from onyx.server.token_rate_limits.models import MAX_TOKEN_BUDGET_THOUSANDS


class SpendingLimitRequest(BaseModel):
    """One limit on a card. A BLOCK row or an absolute ALERT_ONLY row sets a
    token budget (thousands), a cost budget, or both; a percentage ALERT_ONLY
    row sets only `threshold_percent`."""

    period: TokenRateLimitPeriod
    # None: the limit counts usage of every model.
    model_configuration_id: int | None = None
    token_budget: int | None = Field(default=None, ge=1, le=MAX_TOKEN_BUDGET_THOUSANDS)
    cost_budget_cents: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    action: TokenRateLimitAction = TokenRateLimitAction.BLOCK
    threshold_percent: int | None = Field(default=None, ge=1, le=100)

    @model_validator(mode="after")
    def validate_budgets(self) -> Self:
        has_budget = self.token_budget is not None or self.cost_budget_cents is not None
        if self.threshold_percent is not None:
            if self.action != TokenRateLimitAction.ALERT_ONLY:
                raise ValueError("Only an alert-only limit can use a percentage")
            if has_budget:
                raise ValueError("Set a percentage or budgets, not both")
        elif not has_budget:
            raise ValueError("Set a token budget, a cost budget, or both")
        return self


class SpendingLimitCardRequest(BaseModel):
    """Replaces every limit on one card."""

    enabled: bool
    limits: list[SpendingLimitRequest]

    @model_validator(mode="after")
    def validate_unique_buckets(self) -> Self:
        keys = [
            (
                limit.model_configuration_id,
                limit.period,
                limit.action,
                limit.threshold_percent,
            )
            for limit in self.limits
        ]
        if len(keys) != len(set(keys)):
            raise ValueError(
                "Each model and period can have only one limit of each kind"
            )
        return self


class SpendingLimitView(BaseModel):
    id: int
    period: TokenRateLimitPeriod
    model_configuration_id: int | None
    model_name: str | None
    token_budget: int | None
    cost_budget_cents: float | None
    action: TokenRateLimitAction
    threshold_percent: int | None
    reset_at: datetime
    # Pool cards only: what the pool has used in the current period.
    used_tokens: int | None = None
    used_cost_cents: float | None = None


class SpendingLimitCard(BaseModel):
    enabled: bool
    limits: list[SpendingLimitView]


class GroupSpendingLimitCards(BaseModel):
    pool: SpendingLimitCard
    per_member: SpendingLimitCard


class GroupSpendingLimits(GroupSpendingLimitCards):
    user_group_id: int
    group_name: str
    member_count: int


class SpendingLimitsResponse(BaseModel):
    workspace_pool: SpendingLimitCard
    workspace_per_user: SpendingLimitCard
    groups: list[GroupSpendingLimits]


class EffectiveSpendingLimit(BaseModel):
    """One budget a user is held to, and where it comes from."""

    model_configuration_id: int | None
    model_name: str | None
    period: TokenRateLimitPeriod
    unit: BudgetUnit
    # Tokens or cents.
    budget: float
    scope: TokenRateLimitScope
    user_group_id: int | None
    group_name: str | None


class EffectiveSpendingLimitsResponse(BaseModel):
    user_id: str
    # The per-user allowance, resolved per (model, period, unit).
    allowances: list[EffectiveSpendingLimit]
    # Pool budgets that also apply. Group pools never block across groups:
    # the user passes while any of their groups' pools has room.
    pools: list[EffectiveSpendingLimit]
