"""LLM cost calculation utilities."""

from onyx.utils.logger import setup_logger

logger = setup_logger()


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
            f"Could not calculate cost for model {model_name}: {e}. "
            "Assuming cost is 0."
        )
        return 0.0
