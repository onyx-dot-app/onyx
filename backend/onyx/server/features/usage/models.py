from datetime import datetime

from pydantic import BaseModel

from onyx.db.models import ModelCostOverride


class CostOverrideUpsertRequest(BaseModel):
    # Negotiated rates in USD per million tokens (matches the stored columns).
    # cache_read is optional; null bills cache reads at the input rate.
    model: str
    input_cost_per_mtok: float
    output_cost_per_mtok: float
    cache_read_cost_per_mtok: float | None = None


class CostOverride(BaseModel):
    model: str
    input_cost_per_mtok: float
    output_cost_per_mtok: float
    cache_read_cost_per_mtok: float | None
    updated_at: datetime | None

    @classmethod
    def from_db(cls, row: ModelCostOverride) -> "CostOverride":
        return cls(
            model=row.model,
            input_cost_per_mtok=row.input_cost_per_mtok,
            output_cost_per_mtok=row.output_cost_per_mtok,
            cache_read_cost_per_mtok=row.cache_read_cost_per_mtok,
            updated_at=row.updated_at,
        )


class UsageDayModel(BaseModel):
    day: str  # YYYY-MM-DD (UTC)
    model: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cost_cents: float


class UsageExportRecord(BaseModel):
    """One (model x window-day) bucket for a user in the admin export."""

    model: str
    day: str  # YYYY-MM-DD — the usage window's start day (see UsageExportUser)
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
    """Cursor-style company GenAI report, nested per user.

    `start`/`end` echo the queried half-open range [start, end). Day granularity
    follows the configured usage window (weekly by default), so each record's
    `day` is the window's start day rather than the calendar day of every call.
    """

    start: str
    end: str
    users: list[UsageExportUser]


class ModelPrice(BaseModel):
    """USD per 1M tokens for the user's selected chat model; null if unpriced."""

    model: str
    provider: str | None
    input_per_mtok: float | None
    output_per_mtok: float | None


class UserUsageResponse(BaseModel):
    per_day_by_model: list[UsageDayModel]
    window_cost_cents: float
    # Budget enforcement (P5) is unbuilt; fields are present for forward-compat.
    budget_cents: float | None
    budget_remaining_cents: float | None
    # null when no default chat model is configured tenant-wide.
    selected_model_price: ModelPrice | None
