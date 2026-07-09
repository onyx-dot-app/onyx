from pydantic import BaseModel
from pydantic import model_validator

from onyx.db.models import TokenRateLimit


class TokenRateLimitArgs(BaseModel):
    enabled: bool
    token_budget: int | None = None
    cost_budget_cents: float | None = None
    period_hours: int

    @model_validator(mode="after")
    def validate_budget_set(self) -> "TokenRateLimitArgs":
        if self.token_budget is None and self.cost_budget_cents is None:
            raise ValueError("Either token_budget or cost_budget_cents must be set")
        return self


class TokenRateLimitDisplay(BaseModel):
    token_id: int
    enabled: bool
    token_budget: int | None
    cost_budget_cents: float | None
    period_hours: int

    @classmethod
    def from_db(cls, token_rate_limit: TokenRateLimit) -> "TokenRateLimitDisplay":
        return cls(
            token_id=token_rate_limit.id,
            enabled=token_rate_limit.enabled,
            token_budget=token_rate_limit.token_budget,
            cost_budget_cents=token_rate_limit.cost_budget_cents,
            period_hours=token_rate_limit.period_hours,
        )
