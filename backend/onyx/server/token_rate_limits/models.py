from typing import Self

from pydantic import BaseModel, Field, model_validator

from onyx.db.models import TokenRateLimit
from onyx.db.user_usage import (
    COST_BUDGET_PERIOD_HOURS,
    TOKEN_BUDGET_PERIOD_ERROR,
    normalize_token_period_hours,
)

# 1T tokens; stored in thousands so the ceiling stays inside the int32 column.
MAX_TOKEN_BUDGET_THOUSANDS = 1_000_000_000


class _TokenRateLimitArgsBase(BaseModel):
    enabled: bool
    token_budget: int | None = Field(default=None, ge=1)
    period_hours: int = Field(gt=0)
    cost_budget_cents: float | None = Field(default=None, gt=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def validate_budget_set(self) -> Self:
        if self.token_budget is None and self.cost_budget_cents is None:
            raise ValueError("Either token_budget or cost_budget_cents must be set")
        if (
            self.token_budget is not None
            and self.period_hours != normalize_token_period_hours(self.period_hours)
        ):
            raise ValueError(TOKEN_BUDGET_PERIOD_ERROR)
        if (
            self.cost_budget_cents is not None
            and self.period_hours not in COST_BUDGET_PERIOD_HOURS
        ):
            raise ValueError(
                "Cost budget periods must be daily (1), weekly (7), or monthly (30) days"
            )
        return self


class TokenRateLimitArgs(_TokenRateLimitArgsBase):
    token_budget: int | None = Field(default=None, ge=1, le=MAX_TOKEN_BUDGET_THOUSANDS)


class TokenRateLimitUpdateArgs(_TokenRateLimitArgsBase):
    pass


class TokenRateLimitDisplay(BaseModel):
    token_id: int
    enabled: bool
    token_budget: int | None
    period_hours: int
    cost_budget_cents: float | None

    @classmethod
    def from_db(cls, token_rate_limit: TokenRateLimit) -> "TokenRateLimitDisplay":
        period_hours = token_rate_limit.period_hours
        if token_rate_limit.token_budget is not None:
            period_hours = normalize_token_period_hours(period_hours)
        return cls(
            token_id=token_rate_limit.id,
            enabled=token_rate_limit.enabled,
            token_budget=token_rate_limit.token_budget,
            period_hours=period_hours,
            cost_budget_cents=token_rate_limit.cost_budget_cents,
        )
