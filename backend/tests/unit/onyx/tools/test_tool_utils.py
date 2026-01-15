import pytest

from onyx.llm.constants import LlmProviderNames
from onyx.tools.utils import explicit_tool_calling_supported


@pytest.mark.parametrize(
    "model_provider, model_name, expected_result",
    [
        (LlmProviderNames.ANTHROPIC, "claude-4-sonnet-20250514", True),
        (
            "another-provider",
            "claude-3-haiku-20240307",
            True,
        ),
        (
            LlmProviderNames.ANTHROPIC,
            "claude-3-sonnet-20240229",
            False,
        ),
        (
            LlmProviderNames.BEDROCK,
            "amazon.titan-text-express-v1",
            False,
        ),
        (LlmProviderNames.OPENAI, "gpt-4o", True),
        (LlmProviderNames.OPENAI, "gpt-3.5-turbo-instruct", False),
    ],
)
def test_explicit_tool_calling_supported(
    model_provider: str,
    model_name: str,
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
    actual_result = explicit_tool_calling_supported(model_provider, model_name)
    assert actual_result == expected_result
