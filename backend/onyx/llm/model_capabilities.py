"""Capability and token-limit lookups backed by the bundled model catalog.

This module is deliberately lightweight to import: no DB / SQLAlchemy
dependencies, and catalog data is only loaded on first use.
Keep it that way — API schema modules (e.g. `onyx.server.manage.llm.models`)
import from here at module scope.

Helpers that layer DB or `LLMProviderView` lookups on top of these live in
`onyx.llm.utils`.
"""

import re
from collections.abc import Sequence
from enum import Enum
from functools import lru_cache
from typing import Any

from onyx.configs.model_configs import (
    GEN_AI_MAX_TOKENS,
    GEN_AI_MODEL_FALLBACK_MAX_TOKENS,
    GEN_AI_NUM_RESERVED_OUTPUT_TOKENS,
)
from onyx.llm.api_surfaces import OPENAI_COMPATIBLE_SURFACES, LlmApiSurface
from onyx.llm.constants import BEDROCK_MODEL_TOKEN_LIMITS, LlmProviderNames
from onyx.llm.models import ReasoningEffort
from onyx.utils.logger import setup_logger

logger = setup_logger()

_TWELVE_LABS_PEGASUS_MODEL_NAMES = [
    "us.twelvelabs.pegasus-1-2-v1:0",
    "us.twelvelabs.pegasus-1-2-v1",
    "twelvelabs/us.twelvelabs.pegasus-1-2-v1:0",
    "twelvelabs/us.twelvelabs.pegasus-1-2-v1",
]
_TWELVE_LABS_PEGASUS_OUTPUT_TOKENS = max(512, GEN_AI_MODEL_FALLBACK_MAX_TOKENS // 4)
CUSTOM_MODEL_OVERRIDES: dict[str, dict[str, Any]] = {
    model_name: {
        "max_input_tokens": GEN_AI_MODEL_FALLBACK_MAX_TOKENS,
        "max_output_tokens": _TWELVE_LABS_PEGASUS_OUTPUT_TOKENS,
        "max_tokens": GEN_AI_MODEL_FALLBACK_MAX_TOKENS,
        "supports_reasoning": False,
        "supports_vision": False,
    }
    for model_name in _TWELVE_LABS_PEGASUS_MODEL_NAMES
}


@lru_cache(maxsize=1)
def get_model_map() -> dict[str, dict[str, Any]]:
    """Load the bundled models.dev catalog and Onyx display metadata.

    The snapshot keeps request handling independent of catalog network availability.
    Provider-qualified keys take precedence over unqualified aliases.
    """
    import gzip
    import json
    from pathlib import Path

    root = Path(__file__).parent
    with gzip.open(root / "model_catalog.json.gz", "rt") as source:
        model_map: dict[str, dict[str, Any]] = json.load(source)
    for key, metadata in list(model_map.items()):
        if key.startswith("vercel/"):
            model_map["vercel_ai_gateway/" + key.removeprefix("vercel/")] = (
                metadata.copy()
            )
    direct_providers = {
        "openai",
        "anthropic",
        "gemini",
        "cohere",
        "mistral",
        "deepseek",
        "xai",
    }
    entries = sorted(
        model_map.items(),
        key=lambda item: item[0].split("/", 1)[0] not in direct_providers,
    )
    for key, metadata in entries:
        model_map.setdefault(key.split("/", 1)[-1], metadata.copy())
    with (root / "model_metadata_enrichments.json").open() as source:
        enrichments: dict[str, dict[str, Any]] = json.load(source)
    for key, metadata in enrichments.items():
        model_map.setdefault(key, {}).update(metadata)
    for key, metadata in CUSTOM_MODEL_OVERRIDES.items():
        model_map.setdefault(key, metadata.copy())
    return model_map


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
            "Model '%s' not found in the model catalog. Falling back to %s tokens.",
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

    model_obj = find_model_obj(model_map, model_provider, model_name)

    if not model_obj:
        logger.warning(
            "Model '%s' not found in the model catalog. Falling back to %s output tokens.",
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
    model_catalog = get_model_map()

    input_toks = (
        llm_max_input_tokens(
            model_name=model_name,
            model_provider=model_provider,
            model_map=model_catalog,
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
    2. Check the model catalog
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

    # 2. Check the model catalog
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


def catalog_supports_image_input(model_name: str, model_provider: str) -> bool:
    """Generally should call `model_supports_image_input` unless you already know that
    `model_supports_image_input` from the DB is not set OR you need to avoid the performance
    hit of querying the DB."""
    try:
        model_obj = find_model_obj(get_model_map(), model_provider, model_name)
        if not model_obj:
            logger.warning(
                "No catalog entry found for %s/%s, this model may or may not support image input.",
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

        # Native profiles cover model families released after the catalog snapshot.
        from pydantic_ai.profiles.anthropic import anthropic_model_profile
        from pydantic_ai.profiles.google import google_model_profile
        from pydantic_ai.profiles.openai import openai_model_profile

        if model_provider == LlmProviderNames.ANTHROPIC:
            return bool(
                (anthropic_model_profile(model_name) or {}).get(
                    "supports_thinking", False
                )
            )
        if model_provider in {LlmProviderNames.GOOGLE, LlmProviderNames.VERTEX_AI}:
            return bool(
                (google_model_profile(model_name) or {}).get("supports_thinking", False)
            )
        if model_provider in {LlmProviderNames.OPENAI, LlmProviderNames.AZURE}:
            return bool(
                openai_model_profile(model_name).get("supports_thinking", False)
            )
        return False

    except Exception:
        logger.exception(
            "Failed to get model object for %s/%s", model_provider, model_name
        )
        return False


# OpenAI models that reject the reasoning-effort parameter on every API surface
# (chat completions and responses alike) — only their default effort works.
# Apply this restriction consistently across native and compatible endpoints.
_OPENAI_MODELS_REJECTING_REASONING_EFFORT = ("o1-mini", "o1-preview")


def openai_model_rejects_reasoning_effort(model_name: str) -> bool:
    """Deliberately name-only — no provider guard. These names are OpenAI
    models wherever they're hosted (Azure, LiteLLM proxy, OpenAI-compatible
    gateways), and a provider guard would reintroduce the 400 behind
    gateways. The asymmetry favors matching broadly: a false positive only
    omits an optional parameter, a false negative is a hard request failure.
    """
    base_model_name = model_name.lower().split("/")[-1]
    return base_model_name.startswith(_OPENAI_MODELS_REJECTING_REASONING_EFFORT)


# Omitting the reasoning parameter runs these at their medium default, so OFF
# must reach them as an explicit "none".
def openai_model_supports_reasoning_none(model_name: str) -> bool:
    """Name-only, like `openai_model_rejects_reasoning_effort`: the names are
    OpenAI's wherever they're hosted. Reads the catalog capability flag, which
    is false for gpt-5, gpt-5-mini, the pro and chat variants and GPT-6."""
    base_model_name = model_name.lower().split("/")[-1].removeprefix("openai.")
    try:
        model_map = get_model_map()
        entry = model_map.get(base_model_name) or model_map.get(
            f"{LlmProviderNames.OPENAI}/{base_model_name}"
        )
        return bool(entry) and entry.get("supports_none_reasoning_effort") is True
    except Exception:
        logger.exception("Failed to check %s for reasoning-none support", model_name)
        return False


# Providers that reach OpenAI models over OpenAI's own API shapes: a registry
# model uses the Responses API; other models use Chat Completions.
OPENAI_API_PROVIDERS = frozenset(
    {LlmProviderNames.OPENAI, LlmProviderNames.LITELLM_PROXY, LlmProviderNames.AZURE}
)


def is_true_openai_model(model_provider: str, model_name: str) -> bool:
    """
    Determines if a model is a true OpenAI model or just using OpenAI-compatible API.

    An OpenAI-compatible endpoint can serve models from other providers.
    Check the model catalog before selecting the Responses API.

    This function is used primarily to determine if we should use the responses API.
    OpenAI models from OpenAI and Azure should use responses.
    """

    if model_provider not in OPENAI_API_PROVIDERS:
        return False

    model_map = get_model_map()

    def _check_if_model_name_is_openai_provider(model_name: str) -> bool:
        if model_name not in model_map:
            return False
        return model_map[model_name].get("model_provider") == LlmProviderNames.OPENAI

    try:
        # Check if any model exists in the model catalog with openai prefix
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


def is_openai_registry_model_name(model_name: str) -> bool:
    """Name-only OpenAI-registry check, with any gateway vendor prefix removed.

    Aggregators address models as "vendor/model" ("openai/gpt-5.1"), so the raw
    name never matches the registry. Unlike `is_true_openai_model` this asks
    only "whose model is this", not "do we reach it over OpenAI's own API" —
    keep the two apart, since the latter also decides responses-API routing.
    """
    base_model_name = model_name.split("/")[-1]
    if not base_model_name:
        return False

    try:
        model_map = get_model_map()
        if f"{LlmProviderNames.OPENAI}/{base_model_name}" in model_map:
            return True
        entry = model_map.get(base_model_name)
        return bool(entry) and entry.get("model_provider") == LlmProviderNames.OPENAI
    except Exception:
        logger.exception("Failed to check %s against the OpenAI registry", model_name)
        return False


def openai_chat_variant_rejects_reasoning(model_name: str) -> bool:
    """True for the GPT-5 "-chat" registry variants, which reject reasoning
    params on every surface despite being reasoning models (an OpenAI bug).
    Registry-gated so a name merely containing "-chat" doesn't false-positive."""
    return "-chat" in model_name and is_openai_registry_model_name(model_name)


# GPT-5.4+ refuse function tools over chat completions unless reasoning_effort
# is explicitly "none", and omitting it fails the same way. gpt-5.2 and earlier
# accept tools with reasoning. Version-gated so new releases need no code change.
_OPENAI_CHAT_TOOLS_REQUIRE_REASONING_NONE_MIN_VERSION = (5, 4)

# Tolerates vendor prefixes ("openai.gpt-5.6-sol") and alias suffixes
# ("gpt-5.6-sol-01-ptu") so gateway and Azure deployment names match, while the
# boundary keeps "chatgpt-4o-latest" out.
_OPENAI_GPT_VERSION_PATTERN = re.compile(r"(?:^|[^a-z0-9])gpt-(\d+)(?:\.(\d+))?")


def parse_openai_gpt_version(model_name: str) -> tuple[int, int] | None:
    """(major, minor) from a GPT model name, minor 0 when absent and Azure's
    dotless "gpt-35" read as (3, 5). None for any other name."""
    match = _OPENAI_GPT_VERSION_PATTERN.search(model_name.lower())
    if match is None:
        return None
    major, minor = match.group(1), match.group(2)
    if minor is None and len(major) > 1:
        return (int(major[0]), int(major[1:]))
    return (int(major), int(minor or 0))


def openai_chat_tools_require_reasoning_none(model_name: str) -> bool:
    """True for gpt-5.4 and later, by name alone: the names are OpenAI's wherever
    they're hosted, and a registry-unknown alias must still match or its tool
    calls fail outright."""
    version = parse_openai_gpt_version(model_name)
    return (
        version is not None
        and version >= _OPENAI_CHAT_TOOLS_REQUIRE_REASONING_NONE_MIN_VERSION
    )


# ---------------------------------------------------------------------------
# Reasoning effort
# ---------------------------------------------------------------------------

# Named tiers spanning Claude's naming schemes, including the Claude 5 line whose
# version digit can precede or follow the tier ("claude-sonnet-5" vs
# "claude-5-sonnet").
_ANTHROPIC_MODEL_TIERS = ("opus", "sonnet", "haiku", "fable", "mythos")
_ANTHROPIC_VERSION_PATTERN = r"\d+(?:[.-]\d+)?"

# Claude Opus 4.7+ (and later releases by version) requires adaptive thinking
# and rejects a non-default temperature with a 400. Version-gated, not listed,
# so new releases need no code change.
_ANTHROPIC_ADAPTIVE_THINKING_MIN_VERSION = (4, 7)

# Extended thinking landed in Claude 3.7. Parsing the version off the name
# keeps aliased deployments (gateways, custom model names) reasoning even when
# the model catalog doesn't recognize the string.
_ANTHROPIC_THINKING_MIN_VERSION = (3, 7)

# Tiers that always think. They answer thinking.type=disabled with a 400, so
# "off" is not a level they can be asked for.
_ANTHROPIC_ALWAYS_THINKING_TIERS = ("fable", "mythos")


def _normalize_anthropic_name(model_name: str) -> str | None:
    """A Claude name cut down to the part that carries tier and version.
    None when the name is not a Claude model at all."""
    name = model_name.lower()
    if "claude" not in name:
        return None
    # Drop any provider prefix (e.g. "anthropic/", "bedrock/anthropic.").
    name = name[name.index("claude") :]
    # Drop date/snapshot suffixes ("@20260101", "-20241022") so their digits
    # can't be mistaken for a version.
    return re.sub(r"\d{6,}", "", name.split("@")[0])


def _anthropic_tier(model_name: str) -> str | None:
    """The tier word that comes first in the name, so one carrying two
    ("claude-opus-4-7-mythos") resolves to the one that leads it."""
    name = _normalize_anthropic_name(model_name)
    if name is None:
        return None
    found = [
        (name.index(tier), tier) for tier in _ANTHROPIC_MODEL_TIERS if tier in name
    ]
    return min(found)[1] if found else None


def parse_anthropic_model_version(model_name: str) -> tuple[int, int] | None:
    """Extract the (major, minor) version from a Claude model name.

    Handles the naming variants sent to providers: tier-first
    ("claude-opus-4-8"), version-first ("claude-4-8-opus"), dot-separated
    ("claude-opus-4.8"), the named Claude 5 tiers ("claude-fable-5",
    "claude-5-sonnet"), legacy names ("claude-3-5-sonnet-20241022"), and
    provider-prefixed / date-snapshot forms. Returns None when the name is not a
    Claude model or carries no parseable version.
    """
    name = _normalize_anthropic_name(model_name)
    if name is None:
        return None

    tier = _anthropic_tier(model_name)
    if tier is not None:
        # The version can sit on either side of the tier depending on scheme.
        match = re.search(
            rf"{tier}[.-]?({_ANTHROPIC_VERSION_PATTERN})", name
        ) or re.search(rf"({_ANTHROPIC_VERSION_PATTERN})[.-]?{tier}", name)
        version_str = match.group(1) if match else None
    else:
        match = re.search(_ANTHROPIC_VERSION_PATTERN, name)
        version_str = match.group(0) if match else None

    if not version_str:
        return None
    parts = re.split(r"[.-]", version_str)
    major = int(parts[0])
    minor = int(parts[1]) if len(parts) > 1 else 0
    return (major, minor)


def _anthropic_meets_version(model_name: str, min_version: tuple[int, int]) -> bool:
    version = parse_anthropic_model_version(model_name)
    return version is not None and version >= min_version


def anthropic_uses_adaptive_thinking(model_name: str) -> bool:
    return _anthropic_meets_version(
        model_name, _ANTHROPIC_ADAPTIVE_THINKING_MIN_VERSION
    )


def anthropic_supports_thinking(model_name: str) -> bool:
    return _anthropic_meets_version(model_name, _ANTHROPIC_THINKING_MIN_VERSION)


def anthropic_identity_is_always_thinking(model_names: Sequence[str]) -> bool:
    """The deployment alias, listed last by model_identity_names, is what
    reaches the provider, so it decides whenever it names a Claude version."""
    claude_names = [
        name for name in model_names if parse_anthropic_model_version(name) is not None
    ]
    return bool(claude_names) and anthropic_thinking_is_always_on(claude_names[-1])


def anthropic_thinking_is_always_on(model_name: str) -> bool:
    """True for the tiers that reason no matter what. Adaptive thinking is
    checked first so a tier word elsewhere ("fable-writer-v2") can't match."""
    return (
        anthropic_uses_adaptive_thinking(model_name)
        and _anthropic_tier(model_name) in _ANTHROPIC_ALWAYS_THINKING_TIERS
    )


def anthropic_omits_sampling_params(model_name: str) -> bool:
    return _anthropic_meets_version(
        model_name, _ANTHROPIC_ADAPTIVE_THINKING_MIN_VERSION
    )


_GEMINI_FLASH_NO_MINIMAL_MIN_VERSION = (3, 7)

_GEMINI_VERSION_PATTERN = re.compile(r"gemini-(\d+)(?:\.(\d+))?")


def parse_gemini_version(model_name: str) -> tuple[int, int] | None:
    match = _GEMINI_VERSION_PATTERN.search(model_name.lower())
    if match is None:
        return None
    return (int(match.group(1)), int(match.group(2) or 0))


def gemini_lowest_thinking_level_is_low(model_name: str) -> bool:
    name = model_name.lower().split("/")[-1]
    if "flash" not in name or "lite" in name:
        return False
    version = parse_gemini_version(name)
    return version is not None and version >= _GEMINI_FLASH_NO_MINIMAL_MIN_VERSION


def model_identity_names(model_name: str, deployment_name: str | None) -> list[str]:
    """Every string that could carry a model's identity: model_name, plus a
    custom provider's deployment alias when set (e.g. Azure AI Foundry, where
    the alias is the string actually sent to the provider)."""
    return [name for name in (model_name, deployment_name) if name]


class ReasoningParamStyle(str, Enum):
    """The shape of the reasoning parameters a model accepts."""

    # reasoning={"effort": ..., "summary": "auto"} — OpenAI's own wire format,
    # and the one OpenAI-shaped gateways translate from.
    OPENAI = "openai"
    # thinking={"type": "adaptive"} + output_config={"effort": ...}
    ANTHROPIC_ADAPTIVE = "anthropic_adaptive"
    # thinking={"type": "enabled", "budget_tokens": ...}
    ANTHROPIC_BUDGET = "anthropic_budget"
    # Provider-specific reasoning effort.
    PROVIDER_EFFORT = "provider_effort"


def resolve_reasoning_param_style(
    model_provider: str,
    model_names: Sequence[str],
    api_surface: LlmApiSurface | None,
) -> ReasoningParamStyle:
    """Pick the reasoning wire format for a model.

    Custom providers (e.g. Azure AI Foundry) may carry the model identity only
    in the deployment alias, so callers pass every name that could identify the
    model.
    """
    openai_compatible_surface = api_surface in OPENAI_COMPATIBLE_SURFACES
    is_claude_model = any("claude" in name.lower() for name in model_names)

    # An OpenAI model reached over OpenAI's own API, and one reached through a
    # gateway that speaks OpenAI, take the same parameters. So does Claude
    # behind such a gateway: the format follows the surface, not the vendor.
    if any(is_true_openai_model(model_provider, name) for name in model_names):
        return ReasoningParamStyle.OPENAI
    if openai_compatible_surface and (
        is_claude_model
        or any(is_openai_registry_model_name(name) for name in model_names)
    ):
        return ReasoningParamStyle.OPENAI

    if is_claude_model:
        if any(anthropic_uses_adaptive_thinking(name) for name in model_names):
            return ReasoningParamStyle.ANTHROPIC_ADAPTIVE
        return ReasoningParamStyle.ANTHROPIC_BUDGET

    return ReasoningParamStyle.PROVIDER_EFFORT


# Styles that carry XHIGH to the provider. Elsewhere it's indistinct from HIGH:
# Native provider mappings use HIGH for unsupported XHIGH settings.
_XHIGH_REASONING_STYLES = frozenset(
    {ReasoningParamStyle.OPENAI, ReasoningParamStyle.ANTHROPIC_ADAPTIVE}
)


def supported_reasoning_efforts(
    model_provider: str,
    model_names: Sequence[str],
    api_surface: LlmApiSurface | None,
) -> list[ReasoningEffort]:
    """The effort levels a reasoning model tells apart, in ascending order.

    Callers gate on their own reasoning-support answer first; this only narrows
    the range. An empty list means the model reasons but takes no effort
    parameter at all.

    Both this function and the chat request builder (`onyx.llm.provider_model`)
    derive their answer from `resolve_reasoning_param_style`, so a greyed-out
    slider stop and a dropped request parameter should never disagree.

    One stop still does: Claude behind an OpenAI-compatible gateway offers off
    while the builder sends nothing for it, because the gateway owns the
    translation back to Anthropic's params and has not been measured.
    """
    if any(
        openai_model_rejects_reasoning_effort(name)
        or openai_chat_variant_rejects_reasoning(name)
        for name in model_names
    ):
        return []

    style = resolve_reasoning_param_style(model_provider, model_names, api_surface)
    # A model that always thinks honors no off on any route, gateway included,
    # so offering the level would promise a saving that never arrives.
    always_thinking = anthropic_identity_is_always_thinking(model_names) or any(
        gemini_lowest_thinking_level_is_low(name) for name in model_names
    )
    efforts = [] if always_thinking else [ReasoningEffort.OFF]
    efforts += [ReasoningEffort.LOW, ReasoningEffort.MEDIUM, ReasoningEffort.HIGH]
    if (
        style in _XHIGH_REASONING_STYLES
        and model_provider != LlmProviderNames.OPENROUTER
    ):
        efforts.append(ReasoningEffort.XHIGH)
    return efforts
