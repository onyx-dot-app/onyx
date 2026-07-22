from pydantic import BaseModel, Field, model_validator

from onyx.db.models import TokenRateLimit
from onyx.db.user_usage import (
    TOKEN_BUDGET_PERIOD_ERROR,
    normalize_token_period_hours,
)


class TokenRateLimitArgs(BaseModel):
    enabled: bool
    # Null side exempt. ge/gt=0 — zero/NaN budgets silently disable or break the gate.
    token_budget: int | None = Field(default=None, ge=1)
    period_hours: int = Field(gt=0)
    cost_budget_cents: float | None = Field(default=None, gt=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def validate_budget_set(self) -> "TokenRateLimitArgs":
        if self.token_budget is None and self.cost_budget_cents is None:
            raise ValueError("Either token_budget or cost_budget_cents must be set")
        if (
            self.token_budget is not None
            and self.period_hours != normalize_token_period_hours(self.period_hours)
        ):
            raise ValueError(TOKEN_BUDGET_PERIOD_ERROR)
        return self


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
