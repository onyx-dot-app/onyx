from datetime import datetime

from pydantic import BaseModel, Field

from onyx.db.enums import SystemUsageAttribution
from onyx.db.models import ModelCostOverride
from onyx.db.user_usage import UserUsageByDay as UsageDayModel
from onyx.llm.cost import ModelPrice


class CostOverrideRatesRequest(BaseModel):
    # USD/Mtok; null cache → input rate. Negative rates would credit usage.
    input_cost_per_mtok: float = Field(ge=0, allow_inf_nan=False)
    output_cost_per_mtok: float = Field(ge=0, allow_inf_nan=False)
    cache_read_cost_per_mtok: float | None = Field(
        default=None, ge=0, allow_inf_nan=False
    )


class CostOverrideCreateRequest(CostOverrideRatesRequest):
    model_configuration_id: int


class CostOverrideUpdateRequest(CostOverrideRatesRequest):
    # Moves the override to another model configuration; None keeps its model.
    model_configuration_id: int | None = None


class CostOverride(BaseModel):
    model_configuration_id: int
    # The model's API name, and the name the admin UI shows.
    model_name: str
    model_display_name: str
    llm_provider_id: int
    # The provider's own name (null when unnamed) and its type ("openai").
    llm_provider_name: str | None
    provider: str
    input_cost_per_mtok: float
    output_cost_per_mtok: float
    cache_read_cost_per_mtok: float | None
    updated_at: datetime | None

    @classmethod
    def from_db(cls, row: ModelCostOverride) -> "CostOverride":
        model_configuration = row.model_configuration
        llm_provider = model_configuration.llm_provider
        return cls(
            model_configuration_id=row.model_configuration_id,
            model_name=model_configuration.name,
            model_display_name=(
                model_configuration.custom_display_name
                or model_configuration.display_name
                or model_configuration.name
            ),
            llm_provider_id=llm_provider.id,
            llm_provider_name=llm_provider.name,
            provider=llm_provider.provider,
            input_cost_per_mtok=row.input_cost_per_mtok,
            output_cost_per_mtok=row.output_cost_per_mtok,
            cache_read_cost_per_mtok=row.cache_read_cost_per_mtok,
            updated_at=row.updated_at,
        )


class UsageExportRecord(BaseModel):
    model: str
    flow: str
    provider: str
    incognito: bool
    day: str  # YYYY-MM-DD
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_creation_tokens: int
    cost_cents: float


class UsageExportTotals(BaseModel):
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_creation_tokens: int
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


class SystemUsageRecord(BaseModel):
    attribution: SystemUsageAttribution
    model: str
    flow: str
    provider: str
    day: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_creation_tokens: int
    cost_cents: float


class SystemUsageCategory(BaseModel):
    category: str
    totals: UsageExportTotals
    records: list[SystemUsageRecord]


class SystemUsageResponse(BaseModel):
    start: str
    end: str
    categories: list[SystemUsageCategory]


class ResetUsageRequest(BaseModel):
    user_email: str = Field(min_length=1)


class ResetUsageResponse(BaseModel):
    reset_rows: int = Field(ge=0)


class EffectiveCostBudget(BaseModel):
    """One cost limit after applying current usage (cents + period)."""

    budget_cents: float
    remaining_cents: float
    period_hours: int
    reset_at: datetime


class UserUsageResponse(BaseModel):
    per_day_by_model: list[UsageDayModel]
    window_cost_cents: float
    # Effective cost cap + remainder + period (hours); null if no cost limit.
    budget_cents: float | None
    budget_remaining_cents: float | None
    budget_period_hours: int | None = None
    budget_reset_at: datetime | None = None
    selected_model_price: ModelPrice | None
    available_model_prices: list[ModelPrice] = Field(default_factory=list)
