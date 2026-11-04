from typing import Self

from pydantic import BaseModel, Field, model_validator

from onyx.configs.constants import TokenRateLimitPeriod
from onyx.db.models import TokenRateLimit

# 1T tokens; stored in thousands so the ceiling stays inside the int32 column.
MAX_TOKEN_BUDGET_THOUSANDS = 1_000_000_000


class _TokenRateLimitArgsBase(BaseModel):
    enabled: bool
    token_budget: int | None = Field(default=None, ge=1)
    period: TokenRateLimitPeriod
    cost_budget_cents: float | None = Field(default=None, gt=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def validate_budget_set(self) -> Self:
        if self.token_budget is None and self.cost_budget_cents is None:
            raise ValueError("Either token_budget or cost_budget_cents must be set")
        return self


class TokenRateLimitArgs(_TokenRateLimitArgsBase):
    token_budget: int | None = Field(default=None, ge=1, le=MAX_TOKEN_BUDGET_THOUSANDS)


class TokenRateLimitUpdateArgs(_TokenRateLimitArgsBase):
    pass


class TokenRateLimitDisplay(BaseModel):
    token_id: int
    enabled: bool
    token_budget: int | None
    period: TokenRateLimitPeriod
    cost_budget_cents: float | None

    @classmethod
    def from_db(cls, token_rate_limit: TokenRateLimit) -> "TokenRateLimitDisplay":
        return cls(
            token_id=token_rate_limit.id,
            enabled=token_rate_limit.enabled,
            token_budget=token_rate_limit.token_budget,
            period=token_rate_limit.period,
            cost_budget_cents=token_rate_limit.cost_budget_cents,
        )
