"""LLM cost calculation utilities."""

from sqlalchemy.orm import Session

from onyx.configs.app_configs import (
    DEFAULT_IMAGE_COST_CENTS,
    DEFAULT_LLM_INPUT_COST_PER_MTOK,
    DEFAULT_LLM_OUTPUT_COST_PER_MTOK,
)
from onyx.llm import cost_overrides
from onyx.tracing.flows import IMAGE_FLOWS, LLMFlow
from onyx.utils.logger import setup_logger

logger = setup_logger()


def get_model_price_per_million(
    model: str,
    provider: str | None,
    db_session: Session | None = None,
) -> tuple[float | None, float | None]:
    """Override-aware USD/Mtok for UI; (None, None) if unpriced; never raises."""
    if db_session is not None:
        try:
            rates = cost_overrides.get_override(db_session, model, provider or "")
        except Exception:
            logger.exception("Override lookup failed for model %s", model)
            rates = None
        if rates is not None:
            return rates.input_cost_per_mtok, rates.output_cost_per_mtok

    try:
        import litellm

        # custom_llm_provider disambiguates non-self-identifying names so the
        # same model resolves the same way it does for billing.
        entry = litellm.get_model_info(model=model, custom_llm_provider=provider)
        input_per_tok = entry.get("input_cost_per_token")
        output_per_tok = entry.get("output_cost_per_token")
        return (
            float(input_per_tok) * 1_000_000 if input_per_tok is not None else None,
            float(output_per_tok) * 1_000_000 if output_per_tok is not None else None,
        )
    except Exception:
        logger.debug("No price-per-million for model %s (provider %s)", model, provider)
        return None, None


def _image_cost_cents(model: str, provider: str | None) -> float:
    """Per-image cents from litellm, else DEFAULT_IMAGE_COST_CENTS."""
    try:
        import litellm

        try:
            entry = litellm.get_model_info(model=model, custom_llm_provider=provider)
        except Exception:
            entry = litellm.model_cost.get(model) or {}
        # litellm prices images per-image under either of these keys. Use an
        # explicit None check so a genuinely free (0.0) model is billed 0, not
        # silently bumped to the flat fallback.
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
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int,
) -> tuple[float, float]:
    """Apply admin per-Mtok rates. Cache reads bill at the admin cache rate when
    set, otherwise at the input rate. Cache cost is folded into the input half."""
    input_per_mtok = rates.input_cost_per_mtok
    output_per_mtok = rates.output_cost_per_mtok
    cache_per_mtok = rates.cache_read_cost_per_mtok
    cache_rate = cache_per_mtok if cache_per_mtok is not None else input_per_mtok
    input_cents = (
        input_tokens / 1_000_000 * input_per_mtok * 100
        + cache_read_tokens / 1_000_000 * cache_rate * 100
    )
    output_cents = output_tokens / 1_000_000 * output_per_mtok * 100
    return input_cents, output_cents


def compute_cost_cents(
    model: str,
    provider: str | None,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int = 0,
    flow: LLMFlow | str | None = None,
    image_count: int = 1,
    db_session: Session | None = None,
) -> tuple[float, float]:
    """Return (input_cost_cents, output_cost_cents) for an LLM call.

    Resolution order: image pricing → admin override → litellm → default
    fallback rates (0 unless set). Never raises (usage hot path)."""
    if flow in IMAGE_FLOWS:
        return 0.0, _image_cost_cents(model, provider) * max(image_count, 1)

    if db_session is not None:
        try:
            rates = cost_overrides.get_override(db_session, model, provider or "")
        except Exception:
            logger.exception("Override lookup failed for model %s", model)
            rates = None
        if rates is not None:
            return _override_cost_cents(
                rates, input_tokens, output_tokens, cache_read_tokens
            )

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
        # Unpriced model: configurable default rates; debug log distinguishes
        # transient litellm failure from a genuinely unpriced model.
        logger.debug(
            "litellm pricing failed for model %s (provider %s); using default rates",
            model,
            provider,
            exc_info=True,
        )
        billed_input = input_tokens + cache_read_tokens
        input_cents = billed_input / 1_000_000 * DEFAULT_LLM_INPUT_COST_PER_MTOK * 100
        output_cents = (
            output_tokens / 1_000_000 * DEFAULT_LLM_OUTPUT_COST_PER_MTOK * 100
        )
        if not (DEFAULT_LLM_INPUT_COST_PER_MTOK or DEFAULT_LLM_OUTPUT_COST_PER_MTOK):
            logger.warning(
                "No price for model %s (provider %s); recording 0 cost.",
                model,
                provider,
            )
        return input_cents, output_cents
