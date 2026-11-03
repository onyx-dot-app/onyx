"""Queries for admin per-model cost overrides, one per model configuration."""

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from onyx.db.models import ModelConfiguration, ModelCostOverride


def _check_rates(*rates: float | None) -> None:
    # Defense in depth behind the request model's ge=0: a negative rate would
    # credit usage and corrupt budget enforcement.
    if any(rate is not None and rate < 0 for rate in rates):
        raise ValueError("cost override rates must be non-negative")


def fetch_cost_overrides(db_session: Session) -> list[ModelCostOverride]:
    """All overrides, with their model configuration and provider loaded,
    ordered by model name."""
    return list(
        db_session.execute(
            select(ModelCostOverride)
            .join(ModelCostOverride.model_configuration)
            .options(
                selectinload(ModelCostOverride.model_configuration).selectinload(
                    ModelConfiguration.llm_provider
                )
            )
            .order_by(ModelConfiguration.name, ModelCostOverride.id)
        )
        .scalars()
        .all()
    )


def fetch_cost_override(
    db_session: Session, model_configuration_id: int
) -> ModelCostOverride | None:
    return db_session.execute(
        select(ModelCostOverride).where(
            ModelCostOverride.model_configuration_id == model_configuration_id
        )
    ).scalar_one_or_none()


def create_cost_override(
    db_session: Session,
    model_configuration_id: int,
    input_cost_per_mtok: float,
    output_cost_per_mtok: float,
    cache_read_cost_per_mtok: float | None = None,
) -> ModelCostOverride:
    """Adds an override. The caller checks the configuration exists and has no
    override yet, then commits and invalidates the override cache."""
    _check_rates(input_cost_per_mtok, output_cost_per_mtok, cache_read_cost_per_mtok)
    row = ModelCostOverride(
        model_configuration_id=model_configuration_id,
        input_cost_per_mtok=input_cost_per_mtok,
        output_cost_per_mtok=output_cost_per_mtok,
        cache_read_cost_per_mtok=cache_read_cost_per_mtok,
    )
    db_session.add(row)
    db_session.flush()
    return row


def update_cost_override(
    db_session: Session,
    model_configuration_id: int,
    input_cost_per_mtok: float,
    output_cost_per_mtok: float,
    cache_read_cost_per_mtok: float | None = None,
    new_model_configuration_id: int | None = None,
) -> ModelCostOverride | None:
    """Sets an existing override's rates, and moves it to
    `new_model_configuration_id` when given; None if the configuration has no
    override. The caller checks the target, commits and invalidates the
    override cache."""
    _check_rates(input_cost_per_mtok, output_cost_per_mtok, cache_read_cost_per_mtok)
    row = fetch_cost_override(db_session, model_configuration_id)
    if row is None:
        return None
    if new_model_configuration_id is not None:
        row.model_configuration_id = new_model_configuration_id
    row.input_cost_per_mtok = input_cost_per_mtok
    row.output_cost_per_mtok = output_cost_per_mtok
    row.cache_read_cost_per_mtok = cache_read_cost_per_mtok
    db_session.flush()
    return row


def delete_cost_override(db_session: Session, model_configuration_id: int) -> bool:
    """Removes the configuration's override; False if there was none."""
    row = fetch_cost_override(db_session, model_configuration_id)
    if row is None:
        return False
    db_session.delete(row)
    db_session.flush()
    return True
