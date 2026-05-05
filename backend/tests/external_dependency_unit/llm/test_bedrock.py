"""Live behavior tests for AWS Bedrock through LiteLLM.

Covers:
- Nova models on Bedrock do NOT leak `<thinking>...</thinking>` tags into
  visible content. Issue #10090 reports these tags rendering as plain text
  in the chat UI; the fix should route the inner-tag tokens to
  `Delta.reasoning_content` and only ship the post-`</thinking>` answer
  on `Delta.content`. This test stays xfail until that lands.

The auth-error path lives at the API surface in
`backend/tests/integration/tests/llm/test_bedrock_auth.py` (it asserts the
`/admin/llm/test` endpoint shape that the UI actually consumes).
"""

import pytest

from onyx.llm.constants import LlmProviderNames
from onyx.llm.models import ChatCompletionMessage
from onyx.llm.models import UserMessage
from onyx.llm.multi_llm import LitellmLLM
from tests.utils.secret_names import TestSecret

pytestmark = pytest.mark.nightly

_NOVA_THINKING_MODEL = "us.amazon.nova-2-lite-v1:0"
_BEDROCK_REGION = "us-west-2"


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Issue #10090: Nova thinking tags currently leak into visible "
        "content. Remove this xfail once the Bedrock chunk parser routes "
        "<thinking>...</thinking> tokens to reasoning_content."
    ),
)
@pytest.mark.secrets(TestSecret.BEDROCK_API_KEY)
def test_nova_streaming_does_not_leak_thinking_tags(
    test_secrets: dict[TestSecret, str],
) -> None:
    """Nova's `<thinking>...</thinking>` tags must not surface in `content`.

    When Nova on Bedrock reasons about a problem, it emits its
    chain-of-thought wrapped in `<thinking>` / `</thinking>` tags. Without a
    Bedrock-side analog of `_patch_ollama_chunk_parser`, those tags are
    streamed as plain content and render literally in the UI.

    The prompt explicitly instructs the model to use `<thinking>` tags so
    the leak is reliably reproducible — we don't want this to be flaky on
    prompts where Nova happens to skip the tags.
    """
    llm = LitellmLLM(
        api_key=test_secrets[TestSecret.BEDROCK_API_KEY],
        model_provider=LlmProviderNames.BEDROCK,
        model_name=_NOVA_THINKING_MODEL,
        max_input_tokens=128_000,
        timeout=60,
        custom_config={"AWS_REGION_NAME": _BEDROCK_REGION},
    )

    prompt: list[ChatCompletionMessage] = [
        UserMessage(
            role="user",
            content=(
                "Solve this step by step. Wrap your reasoning in "
                "<thinking>...</thinking> tags first, then give the final "
                "numeric answer on its own line. Question: what is 17 * 23?"
            ),
        )
    ]

    content_parts: list[str] = []
    reasoning_parts: list[str] = []
    for chunk in llm.stream(prompt=prompt):
        delta = chunk.choice.delta
        if delta.content:
            content_parts.append(delta.content)
        if delta.reasoning_content:
            reasoning_parts.append(delta.reasoning_content)

    full_content = "".join(content_parts)
    full_reasoning = "".join(reasoning_parts)

    assert (
        full_content.strip()
    ), f"Model produced no visible content. reasoning={full_reasoning!r}"
    assert (
        "<thinking>" not in full_content and "</thinking>" not in full_content
    ), f"Raw <thinking> tags leaked into visible content: {full_content!r}"
