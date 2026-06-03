from datetime import datetime

from pydantic import BaseModel

from onyx.db.models import ModelCostOverride


class CostOverrideUpsertRequest(BaseModel):
    # Negotiated rates in USD per million tokens (matches the stored columns).
    model: str
    input_cost_per_mtok: float
    output_cost_per_mtok: float


class CostOverride(BaseModel):
    model: str
    input_cost_per_mtok: float
    output_cost_per_mtok: float
    updated_at: datetime | None

    @classmethod
    def from_db(cls, row: ModelCostOverride) -> "CostOverride":
        return cls(
            model=row.model,
            input_cost_per_mtok=row.input_cost_per_mtok,
            output_cost_per_mtok=row.output_cost_per_mtok,
            updated_at=row.updated_at,
        )
