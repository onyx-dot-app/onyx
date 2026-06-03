"""LLM cost calculation utilities."""

from sqlalchemy.orm import Session

from onyx.configs.app_configs import DEFAULT_IMAGE_COST_CENTS
from onyx.llm import cost_overrides
from onyx.tracing.flows import LLMFlow
from onyx.utils.logger import setup_logger

logger = setup_logger()

_IMAGE_FLOWS = {LLMFlow.IMAGE_GENERATION, LLMFlow.IMAGE_EDIT}


def calculate_llm_cost_cents(
    model_name: str,
    prompt_tokens: int,
    completion_tokens: int,
) -> float:
    """
    Calculate the cost in cents for an LLM API call.

    Uses litellm's cost_per_token function to get current pricing.
    Returns 0 if the model is not found or on any error.
    """
    try:
        import litellm

        # cost_per_token returns (prompt_cost, completion_cost) in USD
        prompt_cost_usd, completion_cost_usd = litellm.cost_per_token(
            model=model_name,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )

        # Convert to cents (multiply by 100)
        total_cost_cents = (prompt_cost_usd + completion_cost_usd) * 100
        return total_cost_cents

    except Exception as e:
        # Log but don't fail - unknown models or errors shouldn't block usage
        logger.debug(
            "Could not calculate cost for model %s: %s. Assuming cost is 0.",
            model_name,
            e,
        )
        return 0.0


def _image_cost_cents(model: str) -> float:
    """Per-image cost in cents from litellm, falling back to a flat constant."""
    try:
        import litellm

        entry = litellm.model_cost.get(model) or {}
        # litellm prices images per-image under either of these keys.
        per_image_usd = entry.get("output_cost_per_image") or entry.get(
            "input_cost_per_image"
        )
        if per_image_usd:
            return float(per_image_usd) * 100
    except Exception:
        logger.exception("Image price lookup failed for model %s", model)
    return DEFAULT_IMAGE_COST_CENTS


def _override_cost_cents(
    rates: tuple[float, float],
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int,
) -> tuple[float, float]:
    """Apply admin per-Mtok rates; cache reads bill at the input rate."""
    input_per_mtok, output_per_mtok = rates
    billed_input = input_tokens + cache_read_tokens
    input_cents = billed_input / 1_000_000 * input_per_mtok * 100
    output_cents = output_tokens / 1_000_000 * output_per_mtok * 100
    return input_cents, output_cents


def compute_cost_cents(
    model: str,
    provider: str | None,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int = 0,
    flow: LLMFlow | str | None = None,
    db_session: Session | None = None,
) -> tuple[float, float]:
    """Return (input_cost_cents, output_cost_cents) for an LLM call.

    Resolution order: admin override (negotiated rates win) → image pricing for
    image flows → litellm token pricing. Unknown/unpriced models yield (0, 0)
    plus a warning; this function never raises (it runs in the usage hot path).
    """
    # Admin override beats everything, including image pricing.
    if db_session is not None:
        try:
            rates = cost_overrides.get_override(db_session, model)
        except Exception:
            logger.exception("Override lookup failed for model %s", model)
            rates = None
        if rates is not None:
            return _override_cost_cents(
                rates, input_tokens, output_tokens, cache_read_tokens
            )

    if flow in _IMAGE_FLOWS:
        # Image generation isn't priced per token; attribute the whole cost
        # to the output (generated-image) half.
        return 0.0, _image_cost_cents(model)

    try:
        import litellm

        # custom_llm_provider is required for non-self-identifying model names
        # (bedrock/vertex/anthropic-plain) — without it litellm raises and we'd
        # record $0 for entire provider classes.
        # input_tokens are non-cached; cache reads are additional prompt tokens
        # billed at the model's (discounted) cache-read rate, never as output.
        prompt_cost_usd, completion_cost_usd = litellm.cost_per_token(
            model=model,
            custom_llm_provider=provider,
            prompt_tokens=input_tokens + cache_read_tokens,
            completion_tokens=output_tokens,
            cache_read_input_tokens=cache_read_tokens,
        )
        return prompt_cost_usd * 100, completion_cost_usd * 100
    except Exception:
        logger.warning(
            "No price for model %s (provider %s); recording 0 cost.",
            model,
            provider,
        )
        return 0.0, 0.0
