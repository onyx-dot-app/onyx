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
# as local Ollama, distinguished only by this suffix on the model. See the
# `-cloud` entries in onyx/llm/litellm_singleton/config.py.
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


def _has_litellm_token_price(model: str, provider: str | None) -> bool:
    """Whether litellm's cost map states a token price for this model.

    A zero from litellm is not evidence of a free model. When every exact
    lookup misses, litellm resolves the model from capability generalization
    rules, which carry no pricing, then coerces the missing rates to 0 rather
    than raising. Gateway providers hit this on their usual `vendor/model`
    names. Entries can also be metadata-only, including the ones Onyx
    registers itself through its model metadata enrichments, so requiring a
    cost-map hit is not enough. An explicit 0.0 is a real price and stays valid.
    """
    try:
        import litellm

        key = litellm.get_model_info(model=model, custom_llm_provider=provider).get(
            "key"
        )
        entry = litellm.model_cost.get(key) if isinstance(key, str) else None
    except Exception:
        return False
    if entry is None:
        return False
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
    """Configured fallback rates for a model litellm cannot price."""
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
        import litellm

        if not _has_litellm_token_price(model, provider):
            raise ValueError("no stated token price for this model")
        entry = litellm.get_model_info(model=model, custom_llm_provider=provider)
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

    Resolution order: image pricing → admin override → litellm → default
    fallback rates (0 unless set). Never raises (usage hot path)."""
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

    try:
        import litellm

        # custom_llm_provider is required for non-self-identifying model names
        # (bedrock/vertex/anthropic-plain) — without it litellm raises and we'd
        # record $0 for entire provider classes.
        # litellm re-prices the cache subsets of prompt_tokens at the model's own
        # cache rates (reads discounted, writes at a premium), never as output.
        prompt_cost_usd, completion_cost_usd = litellm.cost_per_token(
            model=model,
            custom_llm_provider=provider,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cache_read_input_tokens=cache_read_tokens,
            cache_creation_input_tokens=cache_creation_tokens,
        )
        if prompt_cost_usd or completion_cost_usd:
            return prompt_cost_usd * 100, completion_cost_usd * 100
        # Zero is only trustworthy from a mapped model; otherwise litellm
        # invented it for a model it cannot price.
        if _has_litellm_token_price(model, provider):
            return 0.0, 0.0
        logger.debug(
            "litellm priced model %s (provider %s) at 0 without a stated token "
            "price; using default rates",
            model,
            provider,
        )
    except Exception:
        # Unpriced model: configurable default rates; debug log distinguishes
        # transient litellm failure from a genuinely unpriced model.
        logger.debug(
            "litellm pricing failed for model %s (provider %s); using default rates",
            model,
            provider,
            exc_info=True,
        )

    return _default_rate_cents(model, provider, prompt_tokens, completion_tokens)
