"""LLM cost calculation utilities."""

from pydantic import BaseModel
from sqlalchemy.orm import Session

from onyx.configs.app_configs import (
    DEFAULT_IMAGE_COST_CENTS,
    DEFAULT_LLM_INPUT_COST_PER_MTOK,
    DEFAULT_LLM_OUTPUT_COST_PER_MTOK,
)
from onyx.llm import cost_overrides
from onyx.llm.constants import LlmProviderNames
from onyx.tracing.flows import IMAGE_FLOWS, LLMFlow
from onyx.utils.logger import setup_logger

logger = setup_logger()

_LOCALLY_HOSTED_PROVIDERS = frozenset(
    {
        LlmProviderNames.OLLAMA_CHAT.value,
        LlmProviderNames.LM_STUDIO.value,
        LlmProviderNames.OLLAMA.value,
    }
)
# Ollama Cloud serves hosted, billable inference under the same provider names
# as local Ollama, distinguished by this suffix on the model name.
_OLLAMA_CLOUD_MODEL_SUFFIX = "-cloud"


def _is_locally_hosted(model: str, provider: str | None) -> bool:
    """Whether inference runs on the deployment's own hardware.

    Self-hosted inference has no per-token vendor charge, so zero is the real
    price rather than a missing one. Hosted models served by these providers
    are billable and must price normally.
    """
    if provider not in _LOCALLY_HOSTED_PROVIDERS:
        return False
    return not model.endswith(_OLLAMA_CLOUD_MODEL_SUFFIX)


def _catalog_entry(model: str, provider: str | None) -> dict:
    from onyx.llm.model_capabilities import get_model_map

    catalog = get_model_map()
    if provider:
        return catalog.get(f"{provider}/{model}", {})
    return catalog.get(model, {})


def _has_catalog_token_price(model: str, provider: str | None) -> bool:
    entry = _catalog_entry(model, provider)
    return (
        entry.get("input_cost_per_token") is not None
        or entry.get("output_cost_per_token") is not None
    )


def _default_rate_cents(
    model: str,
    provider: str | None,
    prompt_tokens: int,
    completion_tokens: int,
) -> tuple[float, float]:
    """Configured fallback rates for a model without a published price."""
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


class ModelPrice(BaseModel):
    model: str
    provider: str | None
    input_per_mtok: float | None
    output_per_mtok: float | None
    cache_per_mtok: float | None


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
        if not _has_catalog_token_price(model, provider):
            raise ValueError("no stated token price for this model")
        entry = _catalog_entry(model, provider)
        input_per_tok = entry.get("input_cost_per_token")
        output_per_tok = entry.get("output_cost_per_token")
        cache_per_tok = entry.get("cache_read_input_token_cost")
        return ModelPrice(
            model=model,
            provider=provider,
            input_per_mtok=(
                float(input_per_tok) * 1_000_000 if input_per_tok is not None else None
            ),
            output_per_mtok=(
                float(output_per_tok) * 1_000_000
                if output_per_tok is not None
                else None
            ),
            cache_per_mtok=(
                float(cache_per_tok) * 1_000_000 if cache_per_tok is not None else None
            ),
        )
    except Exception:
        logger.debug("No price-per-million for model %s (provider %s)", model, provider)
        return ModelPrice(
            model=model,
            provider=provider,
            input_per_mtok=None,
            output_per_mtok=None,
            cache_per_mtok=None,
        )


def _image_cost_cents(model: str, provider: str | None) -> float:
    """Per-image cents from the model catalog, else DEFAULT_IMAGE_COST_CENTS."""
    try:
        entry = _catalog_entry(model, provider)
        per_image_usd = entry.get("output_cost_per_image")
        if per_image_usd is None:
            per_image_usd = entry.get("input_cost_per_image")
        if per_image_usd is not None:
            return float(per_image_usd) * 100
    except Exception:
        logger.exception("Image price lookup failed for model %s", model)
    return DEFAULT_IMAGE_COST_CENTS


def _override_cost_cents(
    rates: cost_overrides.CostOverrideRates,
    prompt_tokens: int,
    completion_tokens: int,
    cache_read_tokens: int,
) -> tuple[float, float]:
    """Apply admin per-Mtok rates. Cache reads bill at the admin cache rate when
    set, otherwise at the input rate. Cache cost is folded into the input half.

    There is no admin cache-write rate, so cache writes bill at the input
    rate."""
    input_per_mtok = rates.input_cost_per_mtok
    output_per_mtok = rates.output_cost_per_mtok
    cache_per_mtok = rates.cache_read_cost_per_mtok
    cache_rate = cache_per_mtok if cache_per_mtok is not None else input_per_mtok
    non_cached_prompt = max(prompt_tokens - cache_read_tokens, 0)
    input_cents = (
        non_cached_prompt / 1_000_000 * input_per_mtok * 100
        + cache_read_tokens / 1_000_000 * cache_rate * 100
    )
    output_cents = completion_tokens / 1_000_000 * output_per_mtok * 100
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

    Resolution order: image pricing → admin override → local inference →
    genai-prices → model catalog → configured fallback rates (0 unless set)."""
    if flow in IMAGE_FLOWS:
        return 0.0, _image_cost_cents(model, provider) * max(image_count, 1)

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
            )

    if _is_locally_hosted(model, provider):
        return 0.0, 0.0

    from genai_prices import Usage, calc_price

    provider_id = {
        "bedrock": "aws",
        "vertex_ai": "google",
        "gemini": "google",
        "together_ai": "together",
        "fireworks_ai": "fireworks",
        "xai": "x-ai",
    }.get(provider or "", provider)
    try:
        price = calc_price(
            Usage(
                input_tokens=prompt_tokens,
                output_tokens=completion_tokens,
                cache_read_tokens=min(cache_read_tokens, prompt_tokens),
                cache_write_tokens=min(
                    cache_creation_tokens, max(prompt_tokens - cache_read_tokens, 0)
                ),
            ),
            model,
            provider_id=provider_id,
        )
        return float(price.input_price) * 100, float(price.output_price) * 100
    except LookupError:
        entry = _catalog_entry(model, provider)
        if _has_catalog_token_price(model, provider):
            input_rate = float(entry.get("input_cost_per_token") or 0)
            output_rate = float(entry.get("output_cost_per_token") or 0)
            read_rate = float(entry.get("cache_read_input_token_cost", input_rate))
            write_rate = float(entry.get("cache_creation_input_token_cost", input_rate))
            read_tokens = min(cache_read_tokens, prompt_tokens)
            write_tokens = min(
                cache_creation_tokens, max(prompt_tokens - read_tokens, 0)
            )
            input_cost = (prompt_tokens - read_tokens - write_tokens) * input_rate
            return (
                input_cost + read_tokens * read_rate + write_tokens * write_rate
            ) * 100, completion_tokens * output_rate * 100
        logger.debug("No catalog price for model %s (provider %s)", model, provider)

    return _default_rate_cents(model, provider, prompt_tokens, completion_tokens)
