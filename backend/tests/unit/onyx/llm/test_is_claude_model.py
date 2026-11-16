import pytest

from onyx.llm.model_capabilities import is_claude_model, model_identity_names


@pytest.mark.parametrize(
    ("model_name", "deployment_name", "claude"),
    [
        ("claude-sonnet-4-5-20250929", None, True),
        ("bedrock/us.anthropic.claude-sonnet-4-5-20250929-v1:0", None, True),
        ("vertex_ai/claude-opus-4-1@20250805", None, True),
        ("openrouter/anthropic/claude-sonnet-4.5", None, True),
        # Names without a parseable version are Claude too.
        ("claude-sonnet-latest", None, True),
        ("my-claude", None, True),
        # A gateway alias whose deployment is a Claude model.
        ("team-default", "anthropic/claude-opus-4-5", True),
        ("gpt-5.1", None, False),
        ("gemini-3-pro-preview", None, False),
    ],
)
def test_is_claude_model(
    model_name: str, deployment_name: str | None, claude: bool
) -> None:
    assert is_claude_model(model_identity_names(model_name, deployment_name)) is claude
