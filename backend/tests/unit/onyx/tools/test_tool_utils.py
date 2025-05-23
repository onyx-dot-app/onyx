from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from onyx.llm.llm_provider_options import ANTHROPIC_PROVIDER_NAME
from onyx.llm.llm_provider_options import BEDROCK_PROVIDER_NAME
from onyx.tools.utils import explicit_tool_calling_supported


@pytest.mark.parametrize(
    "model_provider, model_name, mock_model_supports_fc, mock_litellm_anthropic_models, expected_result",
    [
        # === Anthropic Scenarios (expected False due to override) ===
        # Provider is Anthropic, base model claims FC support
        (ANTHROPIC_PROVIDER_NAME, "claude-3-opus-20240229", True, [], False),
        # Model name in litellm.anthropic_models, base model claims FC support
        (
            "another-provider",
            "claude-3-haiku-20240307",
            True,
            ["claude-3-haiku-20240307"],
            False,
        ),
        # Both provider is Anthropic AND model name in litellm.anthropic_models, base model claims FC support
        (
            ANTHROPIC_PROVIDER_NAME,
            "claude-3-sonnet-20240229",
            True,
            ["claude-3-sonnet-20240229"],
            False,
        ),
        # === Anthropic Scenarios (expected False due to base support being False) ===
        # Provider is Anthropic, base model does NOT claim FC support
        (ANTHROPIC_PROVIDER_NAME, "claude-2.1", False, [], False),
        # === Bedrock Scenarios ===
        # Bedrock provider with model name containing anthropic model name as substring -> False
        (
            BEDROCK_PROVIDER_NAME,
            "anthropic.claude-3-opus-20240229-v1:0",
            True,
            ["claude-3-opus-20240229"],
            False,
        ),
        # Bedrock provider with model name containing different anthropic model name as substring -> False
        (
            BEDROCK_PROVIDER_NAME,
            "aws-anthropic-claude-3-haiku-20240307",
            True,
            ["claude-3-haiku-20240307"],
            False,
        ),
        # Bedrock provider with model name NOT containing any anthropic model name as substring -> True
        (
            BEDROCK_PROVIDER_NAME,
            "amazon.titan-text-express-v1",
            True,
            ["claude-3-opus-20240229", "claude-3-haiku-20240307"],
            True,
        ),
        # Bedrock provider with model name NOT containing any anthropic model
        # name as substring, but base model doesn't support FC -> False
        (
            BEDROCK_PROVIDER_NAME,
            "amazon.titan-text-express-v1",
            False,
            ["claude-3-opus-20240229", "claude-3-haiku-20240307"],
            False,
        ),
        # === Non-Anthropic Scenarios ===
        # Non-Anthropic provider, base model claims FC support -> True
        ("openai", "gpt-4o", True, [], True),
        # Non-Anthropic provider, base model does NOT claim FC support -> False
        ("openai", "gpt-3.5-turbo-instruct", False, [], False),
        # Non-Anthropic provider, model name happens to be in litellm list (should still be True if provider isn't Anthropic)
        (
            "yet-another-provider",
            "model-also-in-anthropic-list",
            True,
            ["model-also-in-anthropic-list"],
            False,
        ),
        # Control for the above: Non-Anthropic provider, model NOT in litellm list, supports FC -> True
        (
            "yet-another-provider",
            "some-other-model",
            True,
            ["model-NOT-this-one"],
            True,
        ),
    ],
)
@patch("onyx.tools.utils.find_model_obj")
@patch("onyx.tools.utils.litellm")
def test_explicit_tool_calling_supported(
    mock_litellm: MagicMock,
    mock_find_model_obj: MagicMock,
    model_provider: str,
    model_name: str,
    mock_model_supports_fc: bool,
    mock_litellm_anthropic_models: list[str],
    expected_result: bool,
) -> None:
    """
    Anthropic models support tool calling, but
    a) will raise an error if you provide any tool messages and don't provide a list of tools.
    b) will send text before and after generating tool calls.
    We don't want to provide that list of tools because our UI doesn't support sequential
    tool calling yet for (a) and just looks bad for (b), so for now we just treat anthropic
    models as non-tool-calling.

    Additionally, for Bedrock provider, any model containing an anthropic model name as a
    substring should also return False for the same reasons.
    """
    mock_find_model_obj.return_value = {
        "supports_function_calling": mock_model_supports_fc
    }
    mock_litellm.anthropic_models = mock_litellm_anthropic_models

    # get_model_map is called inside explicit_tool_calling_supported before find_model_obj,
    # but its return value doesn't affect the mocked find_model_obj.
    # So, no need to mock get_model_map separately if find_model_obj is fully mocked.

    actual_result = explicit_tool_calling_supported(model_provider, model_name)
    assert actual_result == expected_result
