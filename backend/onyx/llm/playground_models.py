"""Which models the playground offers, and which one each provider defaults to.

The playground runs every tenant on Onyx's keys, so the models it offers are
bounded by price, not by name: a rule keeps working when new models are
released. A model is offered when it is in the recommended list, has a catalog
price, and costs at most PLAYGROUND_MAX_OUTPUT_COST_PER_MTOK per million output
tokens. A provider's default is its recommended default if that costs at most
PLAYGROUND_DEFAULT_MAX_OUTPUT_COST_PER_MTOK, otherwise the most expensive
offered model under that. Both limits are env settings (shared_configs).

Only the playground uses these rules. Cloud keeps the recommended list as is.
"""

from onyx.llm.model_catalog import find_model_cost
from onyx.llm.well_known_providers.auto_update_models import LLMRecommendations
from shared_configs.configs import (
    PLAYGROUND_DEFAULT_MAX_OUTPUT_COST_PER_MTOK,
    PLAYGROUND_MAX_OUTPUT_COST_PER_MTOK,
)


def _output_cost_per_mtok(provider: str, model_name: str) -> float | None:
    cost = find_model_cost(provider, model_name)
    if not cost:
        return None
    output = cost.get("output")
    return float(output) if isinstance(output, int | float) else None


def is_offered_on_playground(
    provider: str, model_name: str, recommendations: LLMRecommendations
) -> bool:
    """Whether the playground offers this model."""
    recommended = {model.name for model in recommendations.get_visible_models(provider)}
    if model_name not in recommended:
        return False
    output_cost = _output_cost_per_mtok(provider, model_name)
    return (
        output_cost is not None and output_cost <= PLAYGROUND_MAX_OUTPUT_COST_PER_MTOK
    )


def playground_default_model(
    provider: str,
    recommendations: LLMRecommendations,
    candidates: set[str] | None = None,
) -> str | None:
    """The model a provider defaults to on the playground, or None if it offers
    none cheap enough. With ``candidates``, it chooses only among those models,
    such as the ones a tenant has visible."""
    within_budget: list[tuple[float, str]] = []
    for model in recommendations.get_visible_models(provider):
        if candidates is not None and model.name not in candidates:
            continue
        output_cost = _output_cost_per_mtok(provider, model.name)
        if (
            output_cost is not None
            and output_cost <= PLAYGROUND_DEFAULT_MAX_OUTPUT_COST_PER_MTOK
            and is_offered_on_playground(provider, model.name, recommendations)
        ):
            within_budget.append((output_cost, model.name))

    recommended_default = recommendations.get_default_model(provider)
    if recommended_default is not None and recommended_default.name in {
        name for _, name in within_budget
    }:
        return recommended_default.name
    if not within_budget:
        return None
    # The most expensive model under the budget, as the closest to the
    # recommended default.
    return max(within_budget)[1]
