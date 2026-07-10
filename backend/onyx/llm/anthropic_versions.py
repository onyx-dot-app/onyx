"""Version-gated behavior of Anthropic Claude models.

Claude 4.6 (e.g. Sonnet 4.6) introduced the adaptive thinking API
(thinking.type.adaptive + output_config.effort) alongside the legacy
thinking.type.enabled + budget_tokens. Starting with Claude Opus 4.7,
Anthropic *requires* adaptive thinking and rejects any non-default sampling
parameter (temperature/top_p/top_k) with a 400 invalid_request_error. Every
later model — Opus 4.8, the Claude 5 line (fable/mythos/sonnet), and beyond —
inherits both behaviors, so we gate on the parsed model version rather than an
explicit list. This lets new releases be handled without a code change, and
avoids relying on LiteLLM's drop_params (unreliable here, since AnthropicConfig
still advertises temperature as supported).
"""

import re

# Named tiers spanning Claude's naming schemes, including the Claude 5 line whose
# version digit can precede or follow the tier ("claude-sonnet-5" vs
# "claude-5-sonnet").
_ANTHROPIC_MODEL_TIERS = ("opus", "sonnet", "haiku", "fable", "mythos")
_ANTHROPIC_VERSION_PATTERN = r"\d+(?:[.-]\d+)?"

# 4.6+ accepts thinking.type.adaptive; older models only accept
# thinking.type.enabled + budget_tokens.
_ANTHROPIC_ADAPTIVE_THINKING_SUPPORTED_MIN_VERSION = (4, 6)
# Opus 4.7+ rejects the legacy thinking config and non-default sampling params.
_ANTHROPIC_ADAPTIVE_THINKING_REQUIRED_MIN_VERSION = (4, 7)


def parse_anthropic_model_version(model_name: str) -> tuple[int, int] | None:
    """Extract the (major, minor) version from a Claude model name.

    Handles the naming variants that reach LiteLLM: tier-first
    ("claude-opus-4-8"), version-first ("claude-4-8-opus"), dot-separated
    ("claude-opus-4.8"), the named Claude 5 tiers ("claude-fable-5",
    "claude-5-sonnet"), legacy names ("claude-3-5-sonnet-20241022"), and
    provider-prefixed / date-snapshot forms. Returns None when the name is not a
    Claude model or carries no parseable version.
    """
    name = model_name.lower()
    if "claude" not in name:
        return None
    # Drop any provider prefix (e.g. "anthropic/", "bedrock/anthropic.").
    name = name[name.index("claude") :]
    # Drop date/snapshot suffixes ("@20260101", "-20241022") so their digits
    # can't be mistaken for a version.
    name = name.split("@")[0]
    name = re.sub(r"\d{6,}", "", name)

    tier = next((t for t in _ANTHROPIC_MODEL_TIERS if t in name), None)
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


def _version_at_least(model_name: str, min_version: tuple[int, int]) -> bool:
    version = parse_anthropic_model_version(model_name)
    return version is not None and version >= min_version


def anthropic_supports_adaptive_thinking(model_name: str) -> bool:
    """True for Claude models that accept thinking.type.adaptive (4.6+)."""
    return _version_at_least(
        model_name, _ANTHROPIC_ADAPTIVE_THINKING_SUPPORTED_MIN_VERSION
    )


def anthropic_requires_adaptive_thinking(model_name: str) -> bool:
    """True for Claude models that reject the legacy thinking config (4.7+)."""
    return _version_at_least(
        model_name, _ANTHROPIC_ADAPTIVE_THINKING_REQUIRED_MIN_VERSION
    )


def anthropic_omits_sampling_params(model_name: str) -> bool:
    """True for Claude models that reject non-default temperature/top_p/top_k
    (4.7+)."""
    return _version_at_least(
        model_name, _ANTHROPIC_ADAPTIVE_THINKING_REQUIRED_MIN_VERSION
    )
