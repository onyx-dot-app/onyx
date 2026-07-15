"""Capability and token-limit lookups backed by the LiteLLM model map.

This module is deliberately lightweight to import: no DB / SQLAlchemy
dependencies, and `litellm` itself is only imported lazily at call time.
Keep it that way — API schema modules (e.g. `onyx.server.manage.llm.models`)
import from here at module scope.

Helpers that layer DB or `LLMProviderView` lookups on top of these live in
`onyx.llm.utils`.
"""

import copy
import re
import threading
import time
from functools import lru_cache
from typing import Any
from typing import cast

from onyx.configs.model_configs import GEN_AI_MAX_TOKENS
from onyx.configs.model_configs import GEN_AI_MODEL_FALLBACK_MAX_TOKENS
from onyx.configs.model_configs import GEN_AI_NUM_RESERVED_OUTPUT_TOKENS
from onyx.llm.constants import BEDROCK_MODEL_TOKEN_LIMITS
from onyx.llm.constants import LlmProviderNames
from onyx.utils.logger import setup_logger
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()

_TWELVE_LABS_PEGASUS_MODEL_NAMES = [
    "us.twelvelabs.pegasus-1-2-v1:0",
    "us.twelvelabs.pegasus-1-2-v1",
    "twelvelabs/us.twelvelabs.pegasus-1-2-v1:0",
    "twelvelabs/us.twelvelabs.pegasus-1-2-v1",
]
_TWELVE_LABS_PEGASUS_OUTPUT_TOKENS = max(512, GEN_AI_MODEL_FALLBACK_MAX_TOKENS // 4)
CUSTOM_LITELLM_MODEL_OVERRIDES: dict[str, dict[str, Any]] = {
    model_name: {
        "max_input_tokens": GEN_AI_MODEL_FALLBACK_MAX_TOKENS,
        "max_output_tokens": _TWELVE_LABS_PEGASUS_OUTPUT_TOKENS,
        "max_tokens": GEN_AI_MODEL_FALLBACK_MAX_TOKENS,
        "supports_reasoning": False,
        "supports_vision": False,
    }
    for model_name in _TWELVE_LABS_PEGASUS_MODEL_NAMES
}


@lru_cache(maxsize=1)  # the copy.deepcopy is expensive, so we cache the result
def get_model_map() -> dict:
    import litellm

    DIVIDER = "/"

    original_map = cast(dict[str, dict], litellm.model_cost)
    starting_map = copy.deepcopy(original_map)
    for key in original_map:
        if DIVIDER in key:
            truncated_key = key.split(DIVIDER)[-1]
            # make sure not to overwrite an original key
            if truncated_key in original_map:
                continue

            # if there are multiple possible matches, choose the most "detailed"
            # one as a heuristic. "detailed" = the description of the model
            # has the most filled out fields.
            existing_truncated_value = starting_map.get(truncated_key)
            potential_truncated_value = original_map[key]
            if not existing_truncated_value or len(potential_truncated_value) > len(
                existing_truncated_value
            ):
                starting_map[truncated_key] = potential_truncated_value

    for model_name, model_metadata in CUSTOM_LITELLM_MODEL_OVERRIDES.items():
        if model_name in starting_map:
            continue
        starting_map[model_name] = copy.deepcopy(model_metadata)

    # NOTE: outside of the explicit CUSTOM_LITELLM_MODEL_OVERRIDES,
    # we avoid hard-coding additional models here. Ollama, for example,
    # allows the user to specify their desired max context window, and it's
    # unlikely to be standard across users even for the same model
    # (it heavily depends on their hardware). For those cases, we rely on
    # GEN_AI_MODEL_FALLBACK_MAX_TOKENS to cover this.
    # for model_name in [
    #     "llama3.2",
    #     "llama3.2:1b",
    #     "llama3.2:3b",
    #     "llama3.2:11b",
    #     "llama3.2:90b",
    # ]:
    #     starting_map[f"ollama/{model_name}"] = {
    #         "max_tokens": 128000,
    #         "max_input_tokens": 128000,
    #         "max_output_tokens": 128000,
    #     }

    return starting_map


def _strip_extra_provider_from_model_name(model_name: str) -> str:
    return model_name.split("/")[1] if "/" in model_name else model_name


def _strip_colon_from_model_name(model_name: str) -> str:
    return ":".join(model_name.split(":")[:-1]) if ":" in model_name else model_name


def find_model_obj(model_map: dict, provider: str, model_name: str) -> dict | None:
    stripped_model_name = _strip_extra_provider_from_model_name(model_name)

    model_names = [
        model_name,
        _strip_extra_provider_from_model_name(model_name),
        # Remove leading extra provider. Usually for cases where user has a
        # customer model proxy which appends another prefix
        # remove :XXXX from the end, if present. Needed for ollama.
        _strip_colon_from_model_name(model_name),
        _strip_colon_from_model_name(stripped_model_name),
    ]

    # Filter out None values and deduplicate model names
    filtered_model_names = [name for name in model_names if name]

    # First try all model names with provider prefix
    for model_name in filtered_model_names:
        model_obj = model_map.get(f"{provider}/{model_name}")
        if model_obj:
            return model_obj

    # Then try all model names without provider prefix
    for model_name in filtered_model_names:
        model_obj = model_map.get(model_name)
        if model_obj:
            return model_obj

    return None


def llm_max_input_tokens(
    model_map: dict,
    model_name: str,
    model_provider: str,
) -> int:
    """Best effort attempt to get the max input tokens for the LLM."""
    if GEN_AI_MAX_TOKENS:
        # This is an override, so always return this
        logger.info("Using override GEN_AI_MAX_TOKENS: %s", GEN_AI_MAX_TOKENS)
        return GEN_AI_MAX_TOKENS

    model_obj = find_model_obj(
        model_map,
        model_provider,
        model_name,
    )
    if not model_obj:
        logger.warning(
            "Model '%s' not found in LiteLLM. Falling back to %s tokens.",
            model_name,
            GEN_AI_MODEL_FALLBACK_MAX_TOKENS,
        )
        return GEN_AI_MODEL_FALLBACK_MAX_TOKENS

    max_input_tokens = model_obj.get("max_input_tokens")
    if max_input_tokens is not None:
        return max_input_tokens

    max_tokens = model_obj.get("max_tokens")
    if max_tokens is not None:
        return max_tokens

    logger.warning(
        "No max tokens found for '%s'. Falling back to %s tokens.",
        model_name,
        GEN_AI_MODEL_FALLBACK_MAX_TOKENS,
    )
    return GEN_AI_MODEL_FALLBACK_MAX_TOKENS


def get_llm_max_output_tokens(
    model_map: dict,
    model_name: str,
    model_provider: str,
) -> int:
    """Best effort attempt to get the max output tokens for the LLM."""
    default_output_tokens = int(GEN_AI_MODEL_FALLBACK_MAX_TOKENS)

    model_obj = model_map.get(f"{model_provider}/{model_name}")
    if not model_obj:
        model_obj = model_map.get(model_name)

    if not model_obj:
        logger.warning(
            "Model '%s' not found in LiteLLM. Falling back to %s output tokens.",
            model_name,
            default_output_tokens,
        )
        return default_output_tokens

    max_output_tokens = model_obj.get("max_output_tokens")
    if max_output_tokens is not None:
        return max_output_tokens

    # Fallback to a fraction of max_tokens if max_output_tokens is not specified
    max_tokens = model_obj.get("max_tokens")
    if max_tokens is not None:
        return int(max_tokens * 0.1)

    logger.warning(
        "No max output tokens found for '%s'. Falling back to %s output tokens.",
        model_name,
        default_output_tokens,
    )
    return default_output_tokens


def get_max_input_tokens(
    model_name: str,
    model_provider: str,
    output_tokens: int = GEN_AI_NUM_RESERVED_OUTPUT_TOKENS,
) -> int:
    # NOTE: we previously used `litellm.get_max_tokens()`, but despite the name, this actually
    # returns the max OUTPUT tokens. Under the hood, this uses the `litellm.model_cost` dict,
    # and there is no other interface to get what we want. This should be okay though, since the
    # `model_cost` dict is a named public interface:
    # https://litellm.vercel.app/docs/completion/token_usage#7-model_cost
    # model_map is  litellm.model_cost
    litellm_model_map = get_model_map()

    input_toks = (
        llm_max_input_tokens(
            model_name=model_name,
            model_provider=model_provider,
            model_map=litellm_model_map,
        )
        - output_tokens
    )

    if input_toks <= 0:
        return GEN_AI_MODEL_FALLBACK_MAX_TOKENS

    return input_toks


def get_bedrock_token_limit(model_id: str) -> int:
    """Look up token limit for a Bedrock model.

    AWS Bedrock API doesn't expose token limits directly. This function
    attempts to determine the limit from multiple sources.

    Lookup order:
    1. Parse from model ID suffix (e.g., ":200k" → 200000)
    2. Check LiteLLM's model_cost dictionary
    3. Fall back to our hardcoded BEDROCK_MODEL_TOKEN_LIMITS mapping
    4. Default to 32000 if not found anywhere
    """
    model_id_lower = model_id.lower()

    # 1. Try to parse context length from model ID suffix
    # Format: "model-name:version:NNNk" where NNN is the context length in thousands
    # Examples: ":200k", ":128k", ":1000k", ":8k", ":4k"
    context_match = re.search(r":(\d+)k\b", model_id_lower)
    if context_match:
        return int(context_match.group(1)) * 1000

    # 2. Check LiteLLM's model_cost dictionary
    try:
        model_map = get_model_map()
        # Try with bedrock/ prefix first, then without
        for key in [f"bedrock/{model_id}", model_id]:
            if key in model_map:
                model_info = model_map[key]
                max_input_tokens = model_info.get("max_input_tokens")
                if max_input_tokens is not None:
                    return max_input_tokens
                max_tokens = model_info.get("max_tokens")
                if max_tokens is not None:
                    return max_tokens
    except Exception:
        pass  # Fall through to mapping

    # 3. Try our hardcoded mapping (longest match first)
    for pattern, limit in sorted(
        BEDROCK_MODEL_TOKEN_LIMITS.items(), key=lambda x: -len(x[0])
    ):
        if pattern in model_id_lower:
            return limit

    # 4. Default fallback
    return GEN_AI_MODEL_FALLBACK_MAX_TOKENS


def litellm_thinks_model_supports_image_input(
    model_name: str, model_provider: str
) -> bool:
    """Generally should call `model_supports_image_input` unless you already know that
    `model_supports_image_input` from the DB is not set OR you need to avoid the performance
    hit of querying the DB."""
    try:
        model_obj = find_model_obj(get_model_map(), model_provider, model_name)
        if not model_obj:
            logger.warning(
                "No litellm entry found for %s/%s, this model may or may not support image input.",
                model_provider,
                model_name,
            )
            return False
        # The or False here is because sometimes the dict contains the key but the value is None
        return model_obj.get("supports_vision", False) or False
    except Exception:
        logger.exception(
            "Failed to get model object for %s/%s", model_provider, model_name
        )
        return False


_REASONING_PROBE_FAILURE_TTL_SECONDS = 300

# keyed per (tenant, model): tenants can define the same custom model name for
# different models, so probe results must never cross tenant boundaries.
# (result, expires_at): None expiry = permanent probe result (static metadata);
# float = failure placeholder that re-probes once the TTL passes
_LITELLM_SUPPORTS_REASONING_CACHE: dict[str, tuple[bool, float | None]] = {}

# per-(tenant, model) locks so concurrent cold misses probe once; a single
# shared lock would serialize unrelated models behind one slow host
_REASONING_PROBE_LOCKS: dict[str, threading.Lock] = {}
_REASONING_PROBE_LOCKS_GUARD = threading.Lock()


def _reasoning_cache_key(full_model_name: str) -> str:
    return f"{get_current_tenant_id()}:{full_model_name}"


def _cached_reasoning_result(cache_key: str) -> bool | None:
    entry = _LITELLM_SUPPORTS_REASONING_CACHE.get(cache_key)
    if entry is None:
        return None
    result, expires_at = entry
    if expires_at is None or time.monotonic() < expires_at:
        return result
    return None


def _litellm_supports_reasoning(full_model_name: str) -> bool:
    """Single-flight, process-lifetime, tenant-scoped cache around
    litellm.supports_reasoning, which can fetch model info over the network
    (e.g. Ollama hosts). Successful probes cache permanently; failures cache as
    False with a short TTL so an unreachable host isn't probed per-request but
    recovers without a restart (a stuck False silently downgrades reasoning
    models)."""
    cache_key = _reasoning_cache_key(full_model_name)
    cached = _cached_reasoning_result(cache_key)
    if cached is not None:
        return cached

    with _REASONING_PROBE_LOCKS_GUARD:
        key_lock = _REASONING_PROBE_LOCKS.setdefault(cache_key, threading.Lock())

    with key_lock:
        cached = _cached_reasoning_result(cache_key)
        if cached is not None:
            return cached

        import litellm

        expires_at = None
        try:
            result = bool(litellm.supports_reasoning(model=full_model_name))
        except Exception:
            logger.exception(
                "Failed to check if %s supports reasoning", full_model_name
            )
            result = False
            expires_at = time.monotonic() + _REASONING_PROBE_FAILURE_TTL_SECONDS
        _LITELLM_SUPPORTS_REASONING_CACHE[cache_key] = (result, expires_at)
        return result


def model_is_reasoning_model(model_name: str, model_provider: str) -> bool:
    model_map = get_model_map()
    try:
        model_obj = find_model_obj(
            model_map,
            model_provider,
            model_name,
        )
        if model_obj and "supports_reasoning" in model_obj:
            reasoning = model_obj["supports_reasoning"]
            if reasoning is not None:
                return reasoning
            logger.error(
                "Cannot find reasoning for name=%s and provider=%s",
                model_name,
                model_provider,
            )

        # Fallback for newer models missing from the local model map
        full_model_name = (
            f"{model_provider}/{model_name}"
            if model_provider not in model_name
            else model_name
        )
        return _litellm_supports_reasoning(full_model_name)

    except Exception:
        logger.exception(
            "Failed to get model object for %s/%s", model_provider, model_name
        )
        return False


def is_true_openai_model(model_provider: str, model_name: str) -> bool:
    """
    Determines if a model is a true OpenAI model or just using OpenAI-compatible API.

    LiteLLM uses the "openai" provider for any OpenAI-compatible server (e.g. vLLM, LiteLLM proxy),
    but this function checks if the model is actually from OpenAI's model registry.

    This function is used primarily to determine if we should use the responses API.
    OpenAI models from OpenAI and Azure should use responses.
    """

    if model_provider not in {
        LlmProviderNames.OPENAI,
        LlmProviderNames.LITELLM_PROXY,
        LlmProviderNames.AZURE,
    }:
        return False

    model_map = get_model_map()

    def _check_if_model_name_is_openai_provider(model_name: str) -> bool:
        if model_name not in model_map:
            return False
        return model_map[model_name].get("litellm_provider") == LlmProviderNames.OPENAI

    try:
        # Check if any model exists in litellm's registry with openai prefix
        # If it's registered as "openai/model-name", it's a real OpenAI model
        if f"{LlmProviderNames.OPENAI}/{model_name}" in model_map:
            return True

        if _check_if_model_name_is_openai_provider(model_name):
            return True

        if model_name.startswith(f"{LlmProviderNames.AZURE}/"):
            model_name_with_azure_removed = "/".join(model_name.split("/")[1:])
            if _check_if_model_name_is_openai_provider(model_name_with_azure_removed):
                return True

        return False

    except Exception:
        logger.exception(
            "Failed to determine if %s/%s is a true OpenAI model",
            model_provider,
            model_name,
        )
        return False
