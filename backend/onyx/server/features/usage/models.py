from datetime import datetime

from pydantic import BaseModel, Field

from onyx.db.models import ModelCostOverride
from onyx.db.user_usage import UserUsageByDay as UsageDayModel


class CostOverrideUpsertRequest(BaseModel):
    # USD/Mtok; null cache → input rate. Negative rates would credit usage.
    model: str = Field(min_length=1)
    # "" = provider-agnostic; set to price the same model per provider.
    provider: str = ""
    input_cost_per_mtok: float = Field(ge=0, allow_inf_nan=False)
    output_cost_per_mtok: float = Field(ge=0, allow_inf_nan=False)
    cache_read_cost_per_mtok: float | None = Field(
        default=None, ge=0, allow_inf_nan=False
    )


class CostOverride(BaseModel):
    model: str
    provider: str
    input_cost_per_mtok: float
    output_cost_per_mtok: float
    cache_read_cost_per_mtok: float | None
    updated_at: datetime | None

    @classmethod
    def from_db(cls, row: ModelCostOverride) -> "CostOverride":
        return cls(
            model=row.model,
            provider=row.provider,
            input_cost_per_mtok=row.input_cost_per_mtok,
            output_cost_per_mtok=row.output_cost_per_mtok,
            cache_read_cost_per_mtok=row.cache_read_cost_per_mtok,
            updated_at=row.updated_at,
        )


class UsageExportRecord(BaseModel):
    model: str
    day: str  # YYYY-MM-DD
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cost_cents: float


class UsageExportTotals(BaseModel):
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cost_cents: float


class UsageExportUser(BaseModel):
    email: str
    totals: UsageExportTotals
    records: list[UsageExportRecord]


class UsageExportResponse(BaseModel):
    """Nested per-user daily usage export."""

    start: str
    end: str
    users: list[UsageExportUser]


class ResetUsageRequest(BaseModel):
    user_email: str


class ResetUsageResponse(BaseModel):
    reset_rows: int


class ModelPrice(BaseModel):
    """USD per 1M tokens for the user's selected chat model; null if unpriced."""

    model: str
    provider: str | None
    input_per_mtok: float | None
    output_per_mtok: float | None


class EffectiveCostBudget(BaseModel):
    """One cost limit after applying current usage (cents + period)."""

    budget_cents: float
    remaining_cents: float
    period_hours: int


class UserUsageResponse(BaseModel):
    per_day_by_model: list[UsageDayModel]
    window_cost_cents: float
    # Effective cost cap + remainder + period (hours); null if no cost limit.
    budget_cents: float | None
    budget_remaining_cents: float | None
    budget_period_hours: int | None = None
    selected_model_price: ModelPrice | None
