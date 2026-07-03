"""Resolution of Anthropic thinking/sampling API contracts.

Newer Anthropic models (Opus 4.7+, Sonnet 5, Fable 5 / Mythos 5) removed the
legacy manual thinking API (thinking.type=enabled + budget_tokens) and reject
non-default sampling params (temperature / top_p / top_k) with a 400.

Resolution order for every helper in this module:

1. Capability flags from litellm's model registry (``litellm.model_cost``).
   The registry updates day-0 for new Anthropic releases, so future models
   resolve correctly without an Onyx code change.
2. Hardcoded fallback tuples for models the registry can't positively
   identify — proxy aliases (e.g. ``litellm_proxy/...`` deployments where the
   admin named the model something custom), dated/regional variants absent
   from the map, and airgapped deployments running a stale bundled map.
3. Anything still unknown defaults to the legacy behavior, so existing
   deployments see no silent behavior shift.

An explicit registry answer (True or False) is definitive in both directions;
the fallback tuples only fill silence — a flag that is absent (None) never
downgrades a model that the tuples match, and an explicit flag is never
overridden by a colliding tuple substring.
"""

from typing import Any

from onyx.utils.logger import setup_logger

logger = setup_logger()

# Fallback: models that require adaptive thinking AND reject sampling params
# (both removals shipped together from Opus 4.7 onward). Substring match to
# cover proxy/Vertex naming variants (e.g. "claude-4.7-opus" via
# litellm_proxy). LiteLLM's drop_params can't handle the sampling-param
# rejection because AnthropicConfig still lists temperature as supported.
_ANTHROPIC_NEW_CONTRACT_MODELS = (
    "claude-opus-4-7",
    "claude-opus-4.7",
    "claude-4-7-opus",
    "claude-4.7-opus",
    "claude-opus-4-8",
    "claude-opus-4.8",
    "claude-4-8-opus",
    "claude-4.8-opus",
    "claude-fable-5",
    "claude-5-fable",
    "claude-mythos-5",
    "claude-5-mythos",
    "claude-sonnet-5",
    "claude-5-sonnet",
)

# Fallback: Anthropic models that ACCEPT the adaptive thinking API. Superset
# of the new-contract list — Sonnet 4.6 supports adaptive but still accepts
# the legacy thinking API and sampling params, so it belongs here only.
_ANTHROPIC_SUPPORTS_ADAPTIVE_THINKING_MODELS = (
    *_ANTHROPIC_NEW_CONTRACT_MODELS,
    "claude-sonnet-4-6",
    "claude-4-6-sonnet",
)


def _matches_fallback(model_name: str, fallback_models: tuple[str, ...]) -> bool:
    normalized_model_name = model_name.lower()
    return any(
        fallback_model in normalized_model_name for fallback_model in fallback_models
    )


def _litellm_capability_flags(model_name: str) -> tuple[bool | None, bool | None]:
    """Look up (supports_adaptive_thinking, supports_sampling_params) in
    litellm's model registry. Returns (None, None) when the model isn't in
    the registry or the lookup fails — callers then use the fallback tuples.

    Deliberately uncached: litellm can refresh its model map at runtime, and
    the lookup is a handful of dict reads.
    """
    try:
        from onyx.llm.litellm_singleton import litellm

        model_cost: dict[str, dict[str, Any]] = litellm.model_cost
        entry = model_cost.get(model_name) or model_cost.get(model_name.lower())
        if entry is None and "/" in model_name:
            # Strip the provider prefix, e.g.
            # "litellm_proxy/claude-sonnet-5" -> "claude-sonnet-5".
            stripped = model_name.split("/", 1)[-1]
            entry = model_cost.get(stripped) or model_cost.get(stripped.lower())
        if entry is None:
            return (None, None)

        adaptive = entry.get("supports_adaptive_thinking")
        sampling = entry.get("supports_sampling_params")
        return (
            adaptive if isinstance(adaptive, bool) else None,
            sampling if isinstance(sampling, bool) else None,
        )
    except Exception:
        logger.warning(
            "litellm capability lookup failed for model %r; "
            "falling back to the hardcoded model lists",
            model_name,
            exc_info=True,
        )
        return (None, None)


def anthropic_requires_adaptive_thinking(model_name: str) -> bool:
    """True when the model rejects the legacy thinking.type=enabled API and
    must be sent thinking.type=adaptive + output_config.effort.
    """
    adaptive, sampling = _litellm_capability_flags(model_name)
    # The registry has no direct "rejects legacy thinking" flag. The models
    # that removed legacy thinking are exactly those that also removed
    # sampling params (Opus 4.7+, Sonnet 5, Fable 5) — requiring both signals
    # excludes Sonnet 4.6, which supports adaptive but still accepts legacy.
    if adaptive is True and sampling is False:
        return True
    # An explicit contradiction of the new contract is definitive — don't let
    # a colliding fallback substring override it.
    if adaptive is False or sampling is True:
        return False
    return _matches_fallback(model_name, _ANTHROPIC_NEW_CONTRACT_MODELS)


def anthropic_supports_adaptive_thinking(model_name: str) -> bool:
    """True when the model accepts the adaptive thinking API (superset of
    :func:`anthropic_requires_adaptive_thinking` — includes Sonnet 4.6).
    """
    adaptive, _ = _litellm_capability_flags(model_name)
    if adaptive is not None:
        return adaptive
    return _matches_fallback(model_name, _ANTHROPIC_SUPPORTS_ADAPTIVE_THINKING_MODELS)


def anthropic_omits_sampling_params(model_name: str) -> bool:
    """True when the model rejects non-default temperature/top_p/top_k and
    the params must be omitted from the request entirely.
    """
    _, sampling = _litellm_capability_flags(model_name)
    if sampling is not None:
        return sampling is False
    return _matches_fallback(model_name, _ANTHROPIC_NEW_CONTRACT_MODELS)
