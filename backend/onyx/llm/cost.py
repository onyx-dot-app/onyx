"""LLM cost calculation utilities.

Pricing comes from the vendored model catalog (see `onyx.llm.model_catalog`),
which the weekly sync aggregates from models.dev, litellm's cost map, and
OpenRouter. litellm's model_cost table is not consulted at runtime.
Catalog rates are USD per million tokens.
"""

from typing import Any

from pydantic import BaseModel
from sqlalchemy.orm import Session

from onyx.configs.app_configs import (
    DEFAULT_IMAGE_COST_CENTS,
    DEFAULT_LLM_INPUT_COST_PER_MTOK,
    DEFAULT_LLM_OUTPUT_COST_PER_MTOK,
)
from onyx.llm import cost_overrides
from onyx.llm.constants import LlmProviderNames
from onyx.llm.model_catalog import find_model_cost
from onyx.tracing.flows import IMAGE_FLOWS, LLMFlow
from onyx.utils.logger import setup_logger

logger = setup_logger()

# Catalog cost blocks carry a context_over_200k tier when a provider charges
# more past a large-context threshold. The threshold is always 200k tokens.
_LONG_CONTEXT_THRESHOLD_TOKENS = 200_000

_LOCALLY_HOSTED_PROVIDERS = frozenset(
    {
        LlmProviderNames.OLLAMA_CHAT.value,
        LlmProviderNames.LM_STUDIO.value,
        LlmProviderNames.OLLAMA.value,
    }
)
# Ollama Cloud serves hosted, billable inference under the same provider names
# as local Ollama, distinguished only by a "-cloud" or ":cloud" tag on the model.
_OLLAMA_CLOUD_MODEL_SUFFIXES = ("-cloud", ":cloud")


def _is_locally_hosted(model: str, provider: str | None) -> bool:
    """Whether inference runs on the deployment's own hardware.

    Self-hosted inference has no per-token vendor charge, so zero is the real
    price rather than a missing one. Hosted models served by these providers
    are billable and must price normally.
    """
    if provider not in _LOCALLY_HOSTED_PROVIDERS:
        return False
    return not model.endswith(_OLLAMA_CLOUD_MODEL_SUFFIXES)


class ModelPrice(BaseModel):
    model: str
    provider: str | None
    input_per_mtok: float | None
    output_per_mtok: float | None
    cache_per_mtok: float | None
    cache_write_per_mtok: float | None = None


def get_model_price_per_million(
    model: str,
    provider: str | None,
    db_session: Session | None = None,
) -> ModelPrice:
    """Return override-aware USD per million tokens without raising."""
    if db_session is not None:
        try:
            rates = cost_overrides.get_override(db_session, model, provider or "")
        except Exception:
            logger.exception("Override lookup failed for model %s", model)
            rates = None
        if rates is not None:
            return ModelPrice(
                model=model,
                provider=provider,
                input_per_mtok=rates.input_cost_per_mtok,
                output_per_mtok=rates.output_cost_per_mtok,
                cache_per_mtok=rates.cache_read_cost_per_mtok,
            )

    if _is_locally_hosted(model, provider):
        return ModelPrice(
            model=model,
            provider=provider,
            input_per_mtok=0.0,
            output_per_mtok=0.0,
            cache_per_mtok=None,
        )

    try:
        cost = find_model_cost(provider or "", model)
    except Exception:
        logger.exception("Catalog lookup failed for model %s", model)
        cost = None
    if cost is None:
        return ModelPrice(
            model=model,
            provider=provider,
            input_per_mtok=None,
            output_per_mtok=None,
            cache_per_mtok=None,
        )

    def _to_float(value: Any) -> float | None:
        return float(value) if value is not None else None

    return ModelPrice(
        model=model,
        provider=provider,
        input_per_mtok=_to_float(cost.get("input")),
        output_per_mtok=_to_float(cost.get("output")),
        cache_per_mtok=_to_float(cost.get("cache_read")),
        cache_write_per_mtok=_to_float(cost.get("cache_write")),
    )


def _image_cost_cents(model: str, provider: str | None, image_count: int) -> float:
    """Per-image pricing comes from the catalog (litellm-derived `image`/`image_input`
    cost fields, USD per image); models without one bill the configured flat rate."""
    try:
        cost = find_model_cost(provider or "", model)
    except Exception:
        logger.exception("Catalog lookup failed for model %s", model)
        cost = None
    if cost:
        per_image = cost.get("image") or cost.get("image_input")
        if per_image is not None:
            return float(per_image) * max(image_count, 1) * 100
    return DEFAULT_IMAGE_COST_CENTS * max(image_count, 1)


def _override_cost_cents(
    rates: cost_overrides.CostOverrideRates,
    prompt_tokens: int,
    completion_tokens: int,
    cache_read_tokens: int,
    cache_creation_tokens: int,
) -> tuple[float, float]:
    """Apply admin per-Mtok rates. Cache reads bill at the admin cache rate when
    set, otherwise at the input rate. Cache cost is folded into the input half.

    There is no admin cache-write rate, so cache writes bill at the input
    rate."""
    input_per_mtok = rates.input_cost_per_mtok
    output_per_mtok = rates.output_cost_per_mtok
    cache_per_mtok = rates.cache_read_cost_per_mtok
    cache_rate = cache_per_mtok if cache_per_mtok is not None else input_per_mtok
    non_cached_prompt = max(
        prompt_tokens - cache_read_tokens - cache_creation_tokens, 0
    )
    input_cents = (
        non_cached_prompt / 1_000_000 * input_per_mtok * 100
        + cache_read_tokens / 1_000_000 * cache_rate * 100
        + cache_creation_tokens / 1_000_000 * input_per_mtok * 100
    )
    output_cents = completion_tokens / 1_000_000 * output_per_mtok * 100
    return input_cents, output_cents


def _catalog_cost_cents(
    cost: dict[str, Any],
    prompt_tokens: int,
    completion_tokens: int,
    cache_read_tokens: int,
    cache_creation_tokens: int,
) -> tuple[float, float]:
    """Price a call from a catalog cost block (USD per million tokens).

    Cache reads bill at cache_read (missing rate = undiscounted, bills at
    input); cache writes bill at cache_write (missing rate = no write
    premium, bills at input). Providers charging a long-context premium get
    their context_over_200k rates applied to every bucket.
    """
    rates = cost
    if prompt_tokens > _LONG_CONTEXT_THRESHOLD_TOKENS:
        tier = cost.get("context_over_200k")
        if tier:
            rates = tier

    def _rate(key: str, fallback: float | None = None) -> float:
        value = rates.get(key)
        if value is None:
            value = cost.get(key)
        return float(value) if value is not None else (fallback or 0.0)

    input_rate = _rate("input")
    output_rate = _rate("output")
    read_rate = _rate("cache_read", input_rate)
    write_rate = _rate("cache_write", input_rate)

    non_cached_prompt = max(
        prompt_tokens - cache_read_tokens - cache_creation_tokens, 0
    )
    input_cents = (
        (
            non_cached_prompt * input_rate
            + cache_read_tokens * read_rate
            + cache_creation_tokens * write_rate
        )
        / 1_000_000
        * 100
    )
    output_cents = completion_tokens * output_rate / 1_000_000 * 100
    return input_cents, output_cents


def compute_cost_cents(
    model: str,
    provider: str | None,
    prompt_tokens: int,
    completion_tokens: int,
    *,
    cache_read_tokens: int = 0,
    cache_creation_tokens: int = 0,
    flow: LLMFlow | str | None = None,
    image_count: int = 1,
    db_session: Session | None = None,
) -> tuple[float, float]:
    """Return (input_cost_cents, output_cost_cents) for an LLM call.

    prompt_tokens is the cache-inclusive provider total; the cache counts are
    subsets of it, not additions to it.

    Resolution order: image pricing → admin override → model catalog → default
    fallback rates (0 unless set). Never raises (usage hot path)."""
    if flow in IMAGE_FLOWS:
        return 0.0, _image_cost_cents(model, provider, image_count)

    if cache_read_tokens + cache_creation_tokens > prompt_tokens:
        logger.warning(
            "Cache subsets exceed the reported prompt total for model %s "
            "(provider %s): %d read + %d write > %d prompt. Pricing the "
            "reported total; cost may be understated.",
            model,
            provider,
            cache_read_tokens,
            cache_creation_tokens,
            prompt_tokens,
        )

    if db_session is not None:
        try:
            rates = cost_overrides.get_override(db_session, model, provider or "")
        except Exception:
            logger.exception("Override lookup failed for model %s", model)
            rates = None
        if rates is not None:
            return _override_cost_cents(
                rates,
                prompt_tokens,
                completion_tokens,
                cache_read_tokens,
                cache_creation_tokens,
            )

    if _is_locally_hosted(model, provider):
        return 0.0, 0.0

    try:
        cost = find_model_cost(provider or "", model)
    except Exception:
        logger.exception("Catalog lookup failed for model %s", model)
        cost = None

    if cost is not None:
        return _catalog_cost_cents(
            cost,
            prompt_tokens,
            completion_tokens,
            cache_read_tokens,
            cache_creation_tokens,
        )

    # Unpriced model: configurable default rates; warning distinguishes a
    # genuinely unpriced model from a transient lookup failure above.
    input_cents = prompt_tokens / 1_000_000 * DEFAULT_LLM_INPUT_COST_PER_MTOK * 100
    output_cents = (
        completion_tokens / 1_000_000 * DEFAULT_LLM_OUTPUT_COST_PER_MTOK * 100
    )
    if not (DEFAULT_LLM_INPUT_COST_PER_MTOK or DEFAULT_LLM_OUTPUT_COST_PER_MTOK):
        logger.warning(
            "No price for model %s (provider %s); recording 0 cost.",
            model,
            provider,
        )
    return input_cents, output_cents
