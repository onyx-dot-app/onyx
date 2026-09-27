"""Unit tests for `onyx.llm.utils` helpers that must consider a custom
provider's deployment alias, not just the stored model name, when resolving
model identity (e.g. Azure AI Foundry, where the alias is the string
actually sent to LiteLLM).
"""

from onyx.llm.utils import model_needs_formatting_reenabled, model_supports_image_input


def test_model_supports_image_input_via_deployment_alias() -> None:
    """The model row's own name is opaque; only the deployment alias reveals
    a real vision-capable model. This is what the live chat path
    (llm_step.py, llm_loop.py) checks before dropping images from history."""
    assert (
        model_supports_image_input(
            "friendly-deploy-8", "azure", deployment_name="gpt-5.1"
        )
        is True
    )


def test_model_supports_image_input_false_without_alias() -> None:
    """Without the alias, an opaque name correctly resolves to no vision
    support rather than silently guessing."""
    assert model_supports_image_input("friendly-deploy-8", "azure") is False


def test_model_needs_formatting_reenabled_via_deployment_alias() -> None:
    """Same identity gap: the reasoning-model markdown-formatting fix must
    also fire when the real model name lives only in the deployment alias."""
    assert (
        model_needs_formatting_reenabled("friendly-deploy-9", deployment_name="gpt-5.1")
        is True
    )


def test_model_needs_formatting_reenabled_false_without_alias() -> None:
    assert model_needs_formatting_reenabled("friendly-deploy-9") is False
