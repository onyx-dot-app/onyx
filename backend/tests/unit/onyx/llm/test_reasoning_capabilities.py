import pytest

from onyx.llm.api_surfaces import LlmApiSurface
from onyx.llm.constants import LlmProviderNames
from onyx.llm.model_capabilities import (
    ReasoningParamStyle,
    is_openai_registry_model_name,
    parse_anthropic_model_version,
    resolve_reasoning_param_style,
    supported_reasoning_efforts,
)
from onyx.llm.models import ReasoningEffort

CHAT_COMPLETIONS = LlmApiSurface.OPENAI_CHAT_COMPLETIONS
RESPONSES = LlmApiSurface.OPENAI_RESPONSES


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
        ("claude-opus-5", (5, 0)),
        ("claude-5-opus", (5, 0)),
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
        # Bedrock inference profiles carry a region prefix and a version suffix
        ("us.anthropic.claude-opus-4-7-20260101-v1:0", (4, 7)),
        ("global.anthropic.claude-opus-4-8-20260301-v1:0", (4, 8)),
        ("anthropic.claude-sonnet-4-20250514-v1:0", (4, 0)),
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
    "model_name, expected",
    [
        ("gpt-5.1", True),
        ("o3", True),
        # Aggregators address models as "vendor/model"
        ("openai/gpt-5.1", True),
        ("openai/o3", True),
        ("anthropic/claude-opus-4-7", False),
        ("google/gemini-3-pro", False),
        ("llama3.1", False),
        ("", False),
    ],
)
def test_is_openai_registry_model_name(model_name: str, expected: bool) -> None:
    assert is_openai_registry_model_name(model_name) is expected


@pytest.mark.parametrize(
    "provider, model_name, api_surface, expected_style",
    [
        # OpenAI reached over OpenAI's own API.
        (LlmProviderNames.OPENAI, "gpt-5.1", None, ReasoningParamStyle.OPENAI),
        (LlmProviderNames.AZURE, "gpt-5.1", None, ReasoningParamStyle.OPENAI),
        (
            LlmProviderNames.LITELLM_PROXY,
            "gpt-5.1",
            None,
            ReasoningParamStyle.OPENAI,
        ),
        # OpenAI behind a gateway that speaks OpenAI, under either mode.
        (
            LlmProviderNames.BIFROST,
            "openai/gpt-5.1",
            CHAT_COMPLETIONS,
            ReasoningParamStyle.OPENAI,
        ),
        (
            LlmProviderNames.BIFROST,
            "openai/gpt-5.1",
            RESPONSES,
            ReasoningParamStyle.OPENAI,
        ),
        (
            LlmProviderNames.OPENAI_COMPATIBLE,
            "gpt-5.1",
            CHAT_COMPLETIONS,
            ReasoningParamStyle.OPENAI,
        ),
        # Claude behind such a gateway: format follows the surface, not the vendor.
        (
            LlmProviderNames.BIFROST,
            "anthropic/claude-opus-4-7",
            CHAT_COMPLETIONS,
            ReasoningParamStyle.OPENAI,
        ),
        # Native Anthropic, on both sides of the adaptive-thinking cutover.
        (
            LlmProviderNames.ANTHROPIC,
            "claude-opus-4-7",
            None,
            ReasoningParamStyle.ANTHROPIC_ADAPTIVE,
        ),
        (
            LlmProviderNames.BEDROCK,
            "us.anthropic.claude-opus-4-7-20260101-v1:0",
            None,
            ReasoningParamStyle.ANTHROPIC_ADAPTIVE,
        ),
        (
            LlmProviderNames.ANTHROPIC,
            "claude-3-7-sonnet",
            None,
            ReasoningParamStyle.ANTHROPIC_BUDGET,
        ),
        (
            LlmProviderNames.BEDROCK,
            "anthropic.claude-sonnet-4-20250514-v1:0",
            None,
            ReasoningParamStyle.ANTHROPIC_BUDGET,
        ),
        # Everything else falls back to LiteLLM's own mapping.
        (
            LlmProviderNames.VERTEX_AI,
            "gemini-3-pro",
            None,
            ReasoningParamStyle.LITELLM_EFFORT,
        ),
        (
            LlmProviderNames.BIFROST,
            "google/gemini-3-pro",
            CHAT_COMPLETIONS,
            ReasoningParamStyle.LITELLM_EFFORT,
        ),
        (
            LlmProviderNames.OPENROUTER,
            "openai/gpt-5.1",
            None,
            ReasoningParamStyle.LITELLM_EFFORT,
        ),
    ],
)
def test_resolve_reasoning_param_style(
    provider: str,
    model_name: str,
    api_surface: LlmApiSurface | None,
    expected_style: ReasoningParamStyle,
) -> None:
    assert (
        resolve_reasoning_param_style(provider, [model_name], api_surface)
        == expected_style
    )


@pytest.mark.parametrize(
    "provider, model_name, api_surface, xhigh_supported",
    [
        (LlmProviderNames.OPENAI, "gpt-5.1", None, True),
        # The bug this replaced: an OpenAI model behind Bifrost was treated as
        # an unknown model, so xhigh was clamped away and greyed out.
        (LlmProviderNames.BIFROST, "openai/gpt-5.1", CHAT_COMPLETIONS, True),
        (LlmProviderNames.BIFROST, "anthropic/claude-opus-4-7", CHAT_COMPLETIONS, True),
        (LlmProviderNames.ANTHROPIC, "claude-opus-4-7", None, True),
        (LlmProviderNames.BEDROCK, "us.anthropic.claude-opus-4-8-v1:0", None, True),
        # Legacy Anthropic budgets make xhigh indistinguishable from high.
        (LlmProviderNames.ANTHROPIC, "claude-3-7-sonnet", None, False),
        # LiteLLM's per-provider mappings reject or drop xhigh.
        (LlmProviderNames.VERTEX_AI, "gemini-3-pro", None, False),
        (LlmProviderNames.OPENROUTER, "openai/gpt-5.1", None, False),
    ],
)
def test_supported_reasoning_efforts(
    provider: str,
    model_name: str,
    api_surface: LlmApiSurface | None,
    xhigh_supported: bool,
) -> None:
    efforts = supported_reasoning_efforts(provider, [model_name], api_surface)
    assert efforts[:4] == [
        ReasoningEffort.OFF,
        ReasoningEffort.LOW,
        ReasoningEffort.MEDIUM,
        ReasoningEffort.HIGH,
    ]
    assert (ReasoningEffort.XHIGH in efforts) is xhigh_supported


@pytest.mark.parametrize("model_name", ["o1-mini", "o1-preview", "o1-mini-2024-09-12"])
def test_models_rejecting_reasoning_effort_support_no_levels(model_name: str) -> None:
    """These models reason but take no effort parameter on any surface, so the
    picker must offer nothing rather than a slider that changes nothing."""
    assert supported_reasoning_efforts(LlmProviderNames.AZURE, [model_name], None) == []


@pytest.mark.parametrize("model_name", ["gpt-5-chat-latest", "gpt-5.1-chat-latest"])
def test_chat_variants_support_no_levels(model_name: str) -> None:
    """The request builder drops every reasoning param for GPT-5 "-chat"
    registry variants, so the picker must offer no levels either."""
    assert (
        supported_reasoning_efforts(LlmProviderNames.OPENAI, [model_name], None) == []
    )


def test_model_identity_taken_from_any_name() -> None:
    """Custom providers can carry the model identity only in the deployment
    alias, so every candidate name is considered."""
    assert (
        resolve_reasoning_param_style(
            LlmProviderNames.VERTEX_AI, ["prod-alias", "claude-opus-4-7"], None
        )
        is ReasoningParamStyle.ANTHROPIC_ADAPTIVE
    )
