"""Live behavior test for Ollama streaming through LiteLLM.

`_patch_ollama_chunk_parser` (in `monkey_patches.py`) ensures reasoning
tokens are routed to `Delta.reasoning_content` and visible answer tokens
land on `Delta.content`, for both native `thinking` field chunks and
legacy `<think>...</think>`-tagged content chunks. Unit tests in
`backend/tests/unit/onyx/llm/test_litellm_monkey_patches.py` cover the
state machine against crafted chunk dicts; this test exercises the same
path against Ollama Cloud's live wire format so we catch upstream
protocol drift.
"""

import pytest

from onyx.llm.constants import LlmProviderNames
from onyx.llm.models import ChatCompletionMessage
from onyx.llm.models import UserMessage
from onyx.llm.multi_llm import LitellmLLM
from tests.utils.secret_names import TestSecret

pytestmark = pytest.mark.nightly

# gpt-oss:120b-cloud emits native `thinking` tokens and is included in the
# nightly Ollama Cloud matrix, so the credential already has access.
_THINKING_MODEL = "gpt-oss:120b-cloud"


@pytest.mark.secrets(TestSecret.OLLAMA_API_KEY)
def test_streaming_separates_reasoning_content_from_visible_content(
    test_secrets: dict[TestSecret, str],
) -> None:
    """A thinking-capable Ollama model must stream its chain-of-thought on
    `Delta.reasoning_content` and its final answer on `Delta.content`, and
    every thinking chunk must surface (not just the first two). A single
    chunk may legitimately carry both fields — Ollama emits transition
    chunks with both `thinking` and `content` populated, and the patch
    routes them to their respective Delta fields rather than dropping
    either.

    Without `_patch_ollama_chunk_parser`, LiteLLM's Ollama transformer
    silently drops reasoning_content from the third chunk onwards
    (transformation.py:504-510 only branches for the first two thinking
    chunks). This test guards against regression in either the patch or
    upstream Ollama chunk shape.
    """
    llm = LitellmLLM(
        api_key=test_secrets[TestSecret.OLLAMA_API_KEY],
        model_provider=LlmProviderNames.OLLAMA_CHAT,
        model_name=_THINKING_MODEL,
        api_base="https://ollama.com",
        max_input_tokens=8192,
        timeout=120,
    )

    prompt: list[ChatCompletionMessage] = [
        UserMessage(
            role="user",
            content=(
                "Think briefly about what 12 * 7 is, then respond with just "
                "the number."
            ),
        )
    ]

    reasoning_parts: list[str] = []
    content_parts: list[str] = []
    for chunk in llm.stream(prompt=prompt):
        delta = chunk.choice.delta
        rc = delta.reasoning_content
        content = delta.content
        if rc:
            reasoning_parts.append(rc)
        if content:
            content_parts.append(content)

    full_reasoning = "".join(reasoning_parts)
    full_content = "".join(content_parts)

    assert full_content.strip(), (
        f"Model produced reasoning but no visible answer tokens. "
        f"reasoning={full_reasoning!r}"
    )
    # Upstream LiteLLM only emits reasoning on the first two thinking chunks
    # then silently drops the rest. A thinking model on a non-trivial prompt
    # should always stream more than two reasoning chunks, so anything <= 2
    # means the patch is missing or upstream regressed.
    assert len(reasoning_parts) > 2, (
        f"Expected more than 2 reasoning chunks (upstream bug drops chunks "
        f"3+), got {len(reasoning_parts)}. reasoning_parts={reasoning_parts!r}"
    )
    assert (
        "<think>" not in full_content and "</think>" not in full_content
    ), f"Raw <think> tags leaked into visible content: {full_content!r}"
    assert (
        "<think>" not in full_reasoning and "</think>" not in full_reasoning
    ), f"Raw <think> tags leaked into reasoning_content: {full_reasoning!r}"
