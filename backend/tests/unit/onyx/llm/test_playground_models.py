"""The playground's price rule: which models it offers, and each provider's
default."""

from collections.abc import Iterator
from datetime import datetime, timezone
from typing import Any
from unittest.mock import patch

import pytest

from onyx.llm import playground_models
from onyx.llm.playground_models import (
    is_offered_on_playground,
    playground_default_model,
)
from onyx.llm.well_known_providers.auto_update_models import (
    LLMProviderRecommendation,
    LLMRecommendations,
)
from onyx.llm.well_known_providers.models import SimpleKnownModel

# USD per million output tokens. None: no catalog price.
_OUTPUT_COST: dict[str, float | None] = {
    "sol": 10.0,
    "astra": 40.0,
    "luna": 0.5,
    "opus": 20.0,
    "sonnet": 10.0,
    "haiku": 0.5,
    "fable": 40.0,
    "unpriced": None,
    "pricey-default": 30.0,
    "mid": 15.0,
}

_RECOMMENDATIONS = LLMRecommendations(
    version="test",
    updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    providers={
        "openai": LLMProviderRecommendation(
            default_model=SimpleKnownModel(name="sol"),
            additional_visible_models=[
                SimpleKnownModel(name="astra"),
                SimpleKnownModel(name="luna"),
            ],
        ),
        "anthropic": LLMProviderRecommendation(
            default_model=SimpleKnownModel(name="opus"),
            additional_visible_models=[
                SimpleKnownModel(name="sonnet"),
                SimpleKnownModel(name="haiku"),
                SimpleKnownModel(name="fable"),
                SimpleKnownModel(name="unpriced"),
            ],
        ),
        "expensive": LLMProviderRecommendation(
            default_model=SimpleKnownModel(name="pricey-default"),
            additional_visible_models=[SimpleKnownModel(name="mid")],
        ),
    },
)


def _fake_cost(_provider: str, model_name: str) -> dict[str, Any] | None:
    output = _OUTPUT_COST.get(model_name)
    return None if output is None else {"input": 1.0, "output": output}


@pytest.fixture(autouse=True)
def _catalog_prices() -> Iterator[None]:
    with patch.object(playground_models, "find_model_cost", side_effect=_fake_cost):
        yield


@pytest.mark.parametrize(
    ("provider", "model", "offered"),
    [
        ("openai", "sol", True),
        ("openai", "luna", True),
        ("openai", "astra", False),  # over the price ceiling
        ("anthropic", "opus", True),  # exactly at the ceiling
        ("anthropic", "fable", False),  # over the price ceiling
        ("anthropic", "unpriced", False),  # no catalog price
        ("openai", "not-recommended", False),
        ("unknown-provider", "sol", False),
    ],
)
def test_offers_recommended_priced_models_under_the_ceiling(
    provider: str, model: str, offered: bool
) -> None:
    assert is_offered_on_playground(provider, model, _RECOMMENDATIONS) is offered


def test_keeps_the_recommended_default_when_it_is_cheap_enough() -> None:
    assert playground_default_model("openai", _RECOMMENDATIONS) == "sol"


def test_picks_the_most_expensive_model_under_the_budget_otherwise() -> None:
    """Opus costs more than the default budget, so Sonnet is the default."""
    assert playground_default_model("anthropic", _RECOMMENDATIONS) == "sonnet"


def test_has_no_default_when_no_model_is_cheap_enough() -> None:
    assert playground_default_model("expensive", _RECOMMENDATIONS) is None
    assert playground_default_model("unknown-provider", _RECOMMENDATIONS) is None


def test_the_price_limits_are_settings() -> None:
    """Raising the ceiling offers the more expensive models, and raising the
    default budget lets the recommended default stay."""
    with (
        patch.object(playground_models, "PLAYGROUND_MAX_OUTPUT_COST_PER_MTOK", 40.0),
        patch.object(
            playground_models, "PLAYGROUND_DEFAULT_MAX_OUTPUT_COST_PER_MTOK", 20.0
        ),
    ):
        assert is_offered_on_playground("anthropic", "fable", _RECOMMENDATIONS)
        assert playground_default_model("anthropic", _RECOMMENDATIONS) == "opus"
