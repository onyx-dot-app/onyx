from pydantic import BaseModel, model_validator
from pydantic import Field

from onyx.db.models import TokenRateLimit


class TokenRateLimitArgs(BaseModel):
    enabled: bool
    # Null side exempt. ge/gt=0 — zero/NaN budgets silently disable or break the gate.
    token_budget: int | None = Field(default=None, ge=1)
    period_hours: int
    cost_budget_cents: float | None = Field(default=None, gt=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def _require_a_budget(self) -> "TokenRateLimitArgs":
        if self.token_budget is None and self.cost_budget_cents is None:
            raise ValueError("Set a token budget, a cost budget, or both.")
        return self

    @model_validator(mode="after")
    def validate_budget_set(self) -> "TokenRateLimitArgs":
        if self.token_budget is None and self.cost_budget_cents is None:
            raise ValueError("Either token_budget or cost_budget_cents must be set")
        return self


class TokenRateLimitDisplay(BaseModel):
    token_id: int
    enabled: bool
    token_budget: int | None
    period_hours: int
    cost_budget_cents: float | None

    @classmethod
    def from_db(cls, token_rate_limit: TokenRateLimit) -> "TokenRateLimitDisplay":
        return cls(
            token_id=token_rate_limit.id,
            enabled=token_rate_limit.enabled,
            token_budget=token_rate_limit.token_budget,
            period_hours=token_rate_limit.period_hours,
            cost_budget_cents=token_rate_limit.cost_budget_cents,
        )
