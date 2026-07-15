"""Tests for the shared Anthropic model-version parser and its gates.

The parser is the single source of truth for both the chat path
(``multi_llm.py``: adaptive thinking required + sampling params rejected,
Opus 4.7+) and the Craft sandbox path (``opencode_config.py``: adaptive
thinking supported, 4.6+).
"""

import pytest

from onyx.llm.model_capabilities import anthropic_omits_sampling_params
from onyx.llm.model_capabilities import anthropic_requires_adaptive_thinking
from onyx.llm.model_capabilities import anthropic_supports_adaptive_thinking
from onyx.llm.model_capabilities import parse_anthropic_model_version


@pytest.mark.parametrize(
    "model_name, expected",
    [
        # Tier-first, hyphenated
        ("claude-opus-4-8", (4, 8)),
        ("claude-opus-4-7", (4, 7)),
        ("claude-sonnet-4-6", (4, 6)),
        ("claude-sonnet-4-5", (4, 5)),
        # Tier-first, dot-separated
        ("claude-opus-4.8", (4, 8)),
        ("claude-opus-4.7", (4, 7)),
        # Version-first (litellm_proxy / reversed schemes)
        ("claude-4-8-opus", (4, 8)),
        ("claude-4.8-opus", (4, 8)),
        ("claude-4-7-opus", (4, 7)),
        ("claude-4.7-opus", (4, 7)),
        # Claude 5 named tiers, version digit on either side
        ("claude-sonnet-5", (5, 0)),
        ("claude-5-sonnet", (5, 0)),
        ("claude-fable-5", (5, 0)),
        ("claude-5-fable", (5, 0)),
        ("claude-mythos-5", (5, 0)),
        ("claude-5-mythos", (5, 0)),
        # Date/snapshot suffixes stripped
        ("claude-opus-4-8@20260101", (4, 8)),
        ("claude-sonnet-5@20260203", (5, 0)),
        ("claude-opus-4-5@20251101", (4, 5)),
        ("claude-3-5-sonnet-20241022", (3, 5)),
        # Legacy naming
        ("claude-3-7-sonnet", (3, 7)),
        # Provider-prefixed
        ("anthropic/claude-opus-4-8", (4, 8)),
        ("bedrock/anthropic.claude-opus-4-7", (4, 7)),
        # Non-Claude models parse to None
        ("gpt-5.2", None),
        ("gemini-2.5-pro", None),
    ],
)
def test_parse_anthropic_model_version(
    model_name: str, expected: tuple[int, int] | None
) -> None:
    assert parse_anthropic_model_version(model_name) == expected


@pytest.mark.parametrize(
    "model_name, supports, requires",
    [
        # Sonnet 4.6 introduced adaptive thinking but still accepts the
        # legacy config — the two thresholds diverge exactly here.
        ("claude-sonnet-4-6", True, False),
        ("claude-opus-4-6", True, False),
        # Opus 4.7 is where adaptive becomes mandatory.
        ("claude-opus-4-7", True, True),
        ("claude-opus-4-8", True, True),
        # The Claude 5 line inherits the requirement.
        ("claude-fable-5", True, True),
        ("claude-5-mythos", True, True),
        ("claude-sonnet-5", True, True),
        # Pre-4.6 models only support the legacy config.
        ("claude-haiku-4-5", False, False),
        ("claude-sonnet-4-5", False, False),
        ("claude-3-5-sonnet-20241022", False, False),
        # Non-Claude models never match.
        ("gpt-5.2", False, False),
    ],
)
def test_adaptive_thinking_gates(
    model_name: str, supports: bool, requires: bool
) -> None:
    assert anthropic_supports_adaptive_thinking(model_name) is supports
    assert anthropic_requires_adaptive_thinking(model_name) is requires
    # Sampling-param rejection arrived with the adaptive requirement (Opus
    # 4.7+) and tracks the same threshold.
    assert anthropic_omits_sampling_params(model_name) is requires
