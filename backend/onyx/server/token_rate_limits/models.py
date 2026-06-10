from pydantic import BaseModel

from onyx.db.models import TokenRateLimit


class TokenRateLimitArgs(BaseModel):
    enabled: bool
    # Nullable so a limit can be token-only, cost-only, or both (see the schema
    # check constraint). At least one of the two budgets must be set.
    token_budget: int | None = None
    period_hours: int
    cost_budget_cents: float | None = None


class TokenRateLimitDisplay(BaseModel):
    token_id: int
    enabled: bool
    token_budget: int | None
    period_hours: int
    cost_budget_cents: float | None = None

    @classmethod
    def from_db(cls, token_rate_limit: TokenRateLimit) -> "TokenRateLimitDisplay":
        return cls(
            token_id=token_rate_limit.id,
            enabled=token_rate_limit.enabled,
            token_budget=token_rate_limit.token_budget,
            period_hours=token_rate_limit.period_hours,
            cost_budget_cents=token_rate_limit.cost_budget_cents,
        )
