from pydantic import BaseModel
from pydantic import Field
from pydantic import model_validator

from onyx.db.models import TokenRateLimit


class TokenRateLimitArgs(BaseModel):
    enabled: bool
    # A limit may be token-only, cost-only, or both; a null side is exempt from
    # that gate. At least one must be set (a row with neither enforces nothing).
    # ge=1: a 0/negative budget is silently treated as token-exempt by the gate
    # (skips token_budget <= 0), so the admin's limit would enforce nothing.
    token_budget: int | None = Field(default=None, ge=1)
    period_hours: int
    # gt=0 + finite: a 0/NaN budget would otherwise trip the gate on the first
    # request (cost >= 0 always true; cost >= NaN always false), bypassing real
    # enforcement.
    cost_budget_cents: float | None = Field(default=None, gt=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def _require_a_budget(self) -> "TokenRateLimitArgs":
        if self.token_budget is None and self.cost_budget_cents is None:
            raise ValueError("Set a token budget, a cost budget, or both.")
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
