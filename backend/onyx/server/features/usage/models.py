from datetime import datetime

from pydantic import BaseModel
from pydantic import Field

from onyx.db.models import ModelCostOverride


class CostOverrideUpsertRequest(BaseModel):
    # Negotiated rates in USD per million tokens (matches the stored columns).
    # cache_read is optional; null bills cache reads at the input rate. Rates are
    # non-negative — a negative rate would credit usage and corrupt budgets.
    # Non-empty: a "" model would persist an override that never matches a lookup.
    model: str = Field(min_length=1)
    # "" = provider-agnostic; set to price the same model per provider.
    provider: str = ""
    # Finite + non-negative: inf/nan would corrupt downstream cost/budget math.
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


class ResetUsageRequest(BaseModel):
    """Admin request to clear a user's current-window usage (lift a budget block)."""

    user_email: str


class ModelPrice(BaseModel):
    """USD per 1M tokens for the user's selected chat model; null if unpriced."""

    model: str
    provider: str | None
    input_per_mtok: float | None
    output_per_mtok: float | None


class UserUsageResponse(BaseModel):
    per_day_by_model: list[UsageDayModel]
    window_cost_cents: float
    # The user's effective cost budget for the current window, what's left, and
    # the window length (hours) so the UI can say "per week/day/hour". All null
    # when no cost limit applies to the user.
    budget_cents: float | None
    budget_remaining_cents: float | None
    budget_period_hours: int | None = None
    # null when no default chat model is configured tenant-wide.
    selected_model_price: ModelPrice | None
