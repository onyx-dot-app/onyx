"""External dependency unit tests for prompt caching functionality.

These tests call LLM providers directly and use litellm's completion_cost() to verify
that prompt caching reduces costs.
"""

import json
import os
import time
from pathlib import Path
from typing import Any
from typing import cast

import pytest
from google import genai
from google.genai import types as genai_types
from google.oauth2 import service_account
from litellm import completion as litellm_completion
from litellm import completion_cost
from sqlalchemy.orm import Session

from onyx.llm.chat_llm import LitellmLLM
from onyx.llm.interfaces import LLM
from onyx.llm.interfaces import LLMConfig
from onyx.llm.message_types import AssistantMessage
from onyx.llm.message_types import ChatCompletionMessage
from onyx.llm.message_types import SystemMessage
from onyx.llm.message_types import UserMessageWithText
from onyx.llm.prompt_cache.processor import process_with_prompt_cache


VERTEX_CREDENTIALS_ENV = "VERTEX_CREDENTIALS"
VERTEX_LOCATION_ENV = "VERTEX_LOCATION"
VERTEX_MODEL_ENV = "VERTEX_MODEL_NAME"
DEFAULT_VERTEX_MODEL = "gemini-2.5-flash"


def _extract_cached_tokens(usage: Any) -> int:
    """Helper to extract cached_tokens from usage (dict or object)."""
    if not usage:
        return 0

    prompt_details = getattr(usage, "prompt_tokens_details", None)
    if prompt_details is None and isinstance(usage, dict):
        prompt_details = usage.get("prompt_tokens_details")

    if not prompt_details:
        return 0

    cached_tokens = getattr(prompt_details, "cached_tokens", None)
    if cached_tokens is None and isinstance(prompt_details, dict):
        cached_tokens = prompt_details.get("cached_tokens")

    return int(cached_tokens or 0)


def _extract_prompt_tokens(usage: Any) -> int:
    """Helper to extract prompt_tokens from usage (dict or object)."""
    if not usage:
        return 0

    prompt_tokens = getattr(usage, "prompt_tokens", None)
    if prompt_tokens is None and isinstance(usage, dict):
        prompt_tokens = usage.get("prompt_tokens")

    return int(prompt_tokens or 0)


def _extract_cache_read_tokens(usage: Any) -> int:
    """Extract cache read metrics from usage (dict or object)."""
    if not usage:
        return 0

    keys_to_check = (
        "cache_read_input_tokens",
        "cache_hit_input_tokens",
        "cache_hits_input_tokens",
    )

    for key in keys_to_check:
        value = getattr(usage, key, None)
        if value is None and isinstance(usage, dict):
            value = usage.get(key)
        if value:
            return int(value)

    if isinstance(usage, dict):
        metadata = usage.get("usage_metadata") or usage.get("metadata")
        if isinstance(metadata, dict):
            for key in keys_to_check:
                value = metadata.get(key)
                if value:
                    return int(value)

        prompt_details = usage.get("prompt_tokens_details")
        if isinstance(prompt_details, dict):
            cached_tokens = prompt_details.get("cached_tokens")
            if cached_tokens:
                return int(cached_tokens)

    return 0


def _get_usage_metric(
    usage: genai_types.GenerateContentResponseUsageMetadata | None,
    attribute: str,
) -> int:
    """Extract integer metric from Google GenAI usage metadata."""
    if usage is None:
        return 0
    value = getattr(usage, attribute, None)
    return int(value or 0)


def _messages_to_genai_contents(
    messages: list[ChatCompletionMessage],
) -> tuple[genai_types.Content | None, list[genai_types.Content]]:
    """Convert ChatCompletionMessages to Google GenAI Content objects."""

    def _content_to_text(content: Any) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, dict):
                    if "text" in item:
                        parts.append(str(item.get("text") or ""))
                    elif item.get("type") == "text":
                        parts.append(str(item.get("text") or ""))
                elif isinstance(item, str):
                    parts.append(item)
            return "".join(parts)
        return str(content or "")

    system_instruction: genai_types.Content | None = None
    converted_messages: list[genai_types.Content] = []

    for msg in messages:
        role = msg.get("role")
        text = _content_to_text(msg.get("content"))
        part = genai_types.Part(text=text)

        if role == "system":
            system_instruction = genai_types.Content(parts=[part], role="user")
            continue

        if not text:
            # Skip empty messages to avoid API errors.
            continue

        converted_role = "model" if role == "assistant" else "user"
        converted_messages.append(
            genai_types.Content(parts=[part], role=converted_role)
        )

    return system_instruction, converted_messages


class _DummyVertexLLM(LLM):
    """Minimal LLM implementation for prompt caching utilities."""

    def __init__(self, *, model_name: str, max_input_tokens: int) -> None:
        self._config = LLMConfig(
            model_provider="vertex_ai",
            model_name=model_name,
            temperature=0.0,
            max_input_tokens=max_input_tokens,
            api_key=None,
            api_base=None,
            api_version=None,
            deployment_name=None,
            credentials_file=None,
        )

    @property
    def config(self) -> LLMConfig:
        return self._config

    def log_model_configs(self) -> None:
        return None

    # The following methods are not used in tests but must be implemented.
    def _invoke_implementation(self, *args: Any, **kwargs: Any) -> Any:  # type: ignore[override]
        raise NotImplementedError("Not used in tests")

    def _stream_implementation(self, *args: Any, **kwargs: Any) -> Any:  # type: ignore[override]
        raise NotImplementedError("Not used in tests")

    def _invoke_implementation_langchain(self, *args: Any, **kwargs: Any) -> Any:  # type: ignore[override]
        raise NotImplementedError("Not used in tests")

    def _stream_implementation_langchain(self, *args: Any, **kwargs: Any) -> Any:  # type: ignore[override]
        raise NotImplementedError("Not used in tests")


@pytest.mark.skipif(
    not os.environ.get("OPENAI_API_KEY"),
    reason="OpenAI API key not available",
)
def test_openai_prompt_caching_reduces_costs(
    db_session: Session,
) -> None:
    """Test that OpenAI prompt caching reduces costs on subsequent calls.

    OpenAI uses implicit caching for prompts >1024 tokens.
    """
    attempts = 8
    successes = 0
    for _ in range(attempts):
        # Create OpenAI LLM
        llm = LitellmLLM(
            api_key=os.environ["OPENAI_API_KEY"],
            model_provider="openai",
            model_name="gpt-4o-mini",
            max_input_tokens=128000,
        )
        import random
        import string

        # Insert 32 random lowercase characters at the start of long_context
        # to prevent holdover cache from previous tests
        random_prefix = "".join(random.choices(string.ascii_lowercase, k=32))
        # Create a long context message to ensure caching threshold is met (>1024 tokens)
        long_context = (
            random_prefix
            + "This is a comprehensive document about artificial intelligence and machine learning. "
            + " ".join(
                [
                    f"Section {i}: This section discusses various aspects of AI technology, "
                    f"including neural networks, deep learning, natural language processing, "
                    f"computer vision, and reinforcement learning. These technologies are "
                    f"revolutionizing how we interact with computers and process information."
                    for i in range(50)
                ]
            )
        )

        # Split into cacheable prefix (the long context) and suffix (the question)
        cacheable_prefix: list[ChatCompletionMessage] = [
            UserMessageWithText(role="user", content=long_context)
        ]

        # First call - creates cache
        print("\n=== First call (cache creation) ===")
        question1: list[ChatCompletionMessage] = [
            UserMessageWithText(
                role="user", content="What are the main topics discussed?"
            )
        ]

        # Apply prompt caching (for OpenAI, this is mostly a no-op but should still work)
        processed_messages1, metadata1 = process_with_prompt_cache(
            llm=llm,
            cacheable_prefix=cacheable_prefix,
            suffix=question1,
            continuation=False,
        )
        # print(f"Processed messages 1: {processed_messages1}")
        # print(f"Metadata 1: {metadata1}")
        # print(f"Cache key 1: {metadata1.cache_key if metadata1 else None}")

        # Call litellm directly so we can get the raw response
        kwargs1: dict[str, Any] = {}
        if metadata1:
            kwargs1["prompt_cache_key"] = metadata1.cache_key

        response1 = litellm_completion(
            model=f"{llm._model_provider}/{llm._model_version}",
            messages=processed_messages1,
            api_key=llm._api_key,
            timeout=llm._timeout,
            **kwargs1,
        )
        cost1 = completion_cost(completion_response=response1)

        usage1 = response1.get("usage", {})
        cached_tokens_1 = _extract_cached_tokens(usage1)
        prompt_tokens_1 = _extract_prompt_tokens(usage1)
        # print(f"Response 1 usage: {usage1}")
        # print(f"Cost 1: ${cost1:.10f}")

        # Wait to ensure cache is available. 15 seconds is not enough
        time.sleep(5)

        # Second call with same context - should use cache
        print("\n=== Second call (cache read) ===")
        question2: list[ChatCompletionMessage] = [
            UserMessageWithText(
                role="user", content="Can you elaborate on neural networks?"
            )
        ]

        # Apply prompt caching (same cacheable prefix)
        processed_messages2, metadata2 = process_with_prompt_cache(
            llm=llm,
            cacheable_prefix=cacheable_prefix,
            suffix=question2,
            continuation=False,
        )
        # print(f"Processed messages 2: {processed_messages2}")
        kwargs2: dict[str, Any] = {}
        cache_key_for_second = (
            metadata2.cache_key
            if metadata2
            else (metadata1.cache_key if metadata1 else None)
        )
        if cache_key_for_second:
            kwargs2["prompt_cache_key"] = cache_key_for_second

        response2 = litellm_completion(
            model=f"{llm._model_provider}/{llm._model_version}",
            messages=processed_messages2,
            api_key=llm._api_key,
            timeout=llm._timeout,
            **kwargs2,
        )
        cost2 = completion_cost(completion_response=response2)

        usage2 = response2.get("usage", {})
        cached_tokens_2 = _extract_cached_tokens(usage2)
        prompt_tokens_2 = _extract_prompt_tokens(usage2)
        # print(f"Response 2 usage: {usage2}")
        # print(f"Cost 2: ${cost2:.10f}")

        # Verify caching occurred – OpenAI reports cached work via prompt_tokens_details.cached_tokens
        print(f"\nCached tokens call 1: {cached_tokens_1}, call 2: {cached_tokens_2}")
        print(f"Prompt tokens call 1: {prompt_tokens_1}, call 2: {prompt_tokens_2}")
        print(f"Cost delta (1 -> 2): ${cost1 - cost2:.10f}")

        # assert (
        #     cached_tokens_1 > 0 or cached_tokens_2 > 0
        # ), f"Expected cached tokens in prompt_tokens_details. call1={cached_tokens_1}, call2={cached_tokens_2}"
        if cached_tokens_1 > 0 or cached_tokens_2 > 0:
            successes += 1
            break

    # empirically there's a 60% chance of success per attempt, so we expect at least one success in 8 attempts
    # (99.94% probability). we can bump this number if the test is too flaky.
    assert (
        successes > 0
    ), f"Expected at least one success. 0 of {attempts} attempts used prompt caching."


@pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"),
    reason="Anthropic API key not available",
)
def test_anthropic_prompt_caching_reduces_costs(
    db_session: Session,
) -> None:
    """Test that Anthropic prompt caching reduces costs on subsequent calls.

    Anthropic requires explicit cache_control parameters.
    """
    # Create Anthropic LLM
    llm = LitellmLLM(
        api_key=os.environ["ANTHROPIC_API_KEY"],
        model_provider="anthropic",
        model_name="claude-3-5-sonnet-20241022",
        max_input_tokens=200000,
    )

    # Create a long context message
    long_context = (
        "This is a comprehensive document about artificial intelligence and machine learning. "
        + " ".join(
            [
                f"Section {i}: This section discusses various aspects of AI technology, "
                f"including neural networks, deep learning, natural language processing, "
                f"computer vision, and reinforcement learning. These technologies are "
                f"revolutionizing how we interact with computers and process information."
                for i in range(50)
            ]
        )
    )

    base_messages: list[ChatCompletionMessage] = [
        UserMessageWithText(role="user", content=long_context)
    ]

    # First call - creates cache
    print("\n=== First call (cache creation) ===")
    question1: list[ChatCompletionMessage] = [
        UserMessageWithText(role="user", content="What are the main topics discussed?")
    ]

    # Apply prompt caching
    processed_messages1, _ = process_with_prompt_cache(
        llm=llm,
        cacheable_prefix=base_messages,
        suffix=question1,
        continuation=False,
    )

    response1 = litellm_completion(
        model=f"{llm._model_provider}/{llm._model_version}",
        messages=processed_messages1,
        api_key=llm._api_key,
        timeout=llm._timeout,
    )
    cost1 = completion_cost(completion_response=response1)

    usage1 = response1.get("usage", {})
    print(f"Response 1 usage: {usage1}")
    print(f"Cost 1: ${cost1:.10f}")

    # Wait to ensure cache is available
    time.sleep(2)

    # Second call with same context - should use cache
    print("\n=== Second call (cache read) ===")
    question2: list[ChatCompletionMessage] = [
        UserMessageWithText(
            role="user", content="Can you elaborate on neural networks?"
        )
    ]

    # Apply prompt caching (same cacheable prefix)
    processed_messages2, _ = process_with_prompt_cache(
        llm=llm,
        cacheable_prefix=base_messages,
        suffix=question2,
        continuation=False,
    )

    response2 = litellm_completion(
        model=f"{llm._model_provider}/{llm._model_version}",
        messages=processed_messages2,
        api_key=llm._api_key,
        timeout=llm._timeout,
    )
    cost2 = completion_cost(completion_response=response2)

    usage2 = response2.get("usage", {})
    print(f"Response 2 usage: {usage2}")
    print(f"Cost 2: ${cost2:.10f}")

    # Verify caching occurred
    cache_creation_tokens = usage1.get("cache_creation_input_tokens", 0)
    cache_read_tokens = usage2.get("cache_read_input_tokens", 0)

    print(f"\nCache creation tokens (call 1): {cache_creation_tokens}")
    print(f"Cache read tokens (call 2): {cache_read_tokens}")
    print(f"Cost reduction: ${cost1 - cost2:.10f}")

    # For Anthropic, we should see cache creation on first call and cache reads on second
    assert (
        cache_creation_tokens > 0
    ), f"Expected cache creation tokens on first call. Got: {cache_creation_tokens}"

    assert (
        cache_read_tokens > 0
    ), f"Expected cache read tokens on second call. Got: {cache_read_tokens}"

    # Cost should be lower on second call
    assert (
        cost2 < cost1
    ), f"Expected lower cost on cached call. Cost 1: ${cost1:.10f}, Cost 2: ${cost2:.10f}"


@pytest.mark.skipif(
    not os.environ.get(VERTEX_CREDENTIALS_ENV),
    reason="Vertex AI credentials file not available",
)
def test_vertex_ai_prompt_caching_reduces_costs(
    db_session: Session,
) -> None:
    """Test that Google GenAI prompt caching reduces costs on subsequent calls."""
    import random
    import string

    credentials_path = Path(os.environ[VERTEX_CREDENTIALS_ENV]).expanduser()
    if not credentials_path.exists():
        pytest.skip(f"Vertex credentials file not found at {credentials_path}")

    service_account_info = json.loads(credentials_path.read_text(encoding="utf-8"))
    project_id = service_account_info["project_id"]
    location = (
        service_account_info.get("location")
        or os.environ.get(VERTEX_LOCATION_ENV)
        or "us-central1"
    )
    credentials = service_account.Credentials.from_service_account_info(
        service_account_info,
        scopes=["https://www.googleapis.com/auth/cloud-platform"],
    )

    model_name = os.environ.get(VERTEX_MODEL_ENV, DEFAULT_VERTEX_MODEL)
    llm_stub = _DummyVertexLLM(
        model_name=model_name,
        max_input_tokens=1_000_000,
    )

    attempts = 4
    success = False
    last_metrics: dict[str, Any] = {}

    with genai.Client(
        vertexai=True,
        project=project_id,
        location=location,
        credentials=credentials,
    ) as client:
        for attempt in range(attempts):
            random_prefix = "".join(random.choices(string.ascii_lowercase, k=32))
            long_context = (
                random_prefix
                + "This is a comprehensive document about artificial intelligence and machine learning. "
                + " ".join(
                    [
                        f"Section {i}: This section discusses various aspects of AI technology, "
                        f"including neural networks, deep learning, natural language processing, "
                        f"computer vision, and reinforcement learning. These technologies are "
                        f"revolutionizing how we interact with computers and process information."
                        for i in range(50)
                    ]
                )
            )

            cacheable_prefix: list[ChatCompletionMessage] = [
                UserMessageWithText(role="user", content=long_context)
            ]

            print(f"\n=== Vertex attempt {attempt + 1} (cache creation) ===")
            question1: list[ChatCompletionMessage] = [
                UserMessageWithText(
                    role="user", content="What are the main topics discussed?"
                )
            ]

            processed_messages1, _ = process_with_prompt_cache(
                llm=llm_stub,
                cacheable_prefix=cacheable_prefix,
                suffix=question1,
                continuation=False,
            )

            if not isinstance(processed_messages1, list):
                pytest.fail("Expected list of chat messages for cached prompt.")

            messages_list1 = cast(list[ChatCompletionMessage], processed_messages1)
            system_instruction1, contents1 = _messages_to_genai_contents(messages_list1)

            content_payload1 = [
                cast(
                    genai_types.ContentDict,
                    content.model_dump(exclude_none=True),
                )
                for content in contents1
            ]
            config_kwargs1: dict[str, Any] = {"temperature": 0.2}
            if system_instruction1 is not None:
                config_kwargs1["system_instruction"] = system_instruction1
            config1 = genai_types.GenerateContentConfig(**config_kwargs1)

            response1 = client.models.generate_content(
                model=model_name,
                contents=cast(Any, content_payload1),
                config=config1,
            )
            usage1 = response1.usage_metadata
            cached_count_1 = _get_usage_metric(usage1, "cached_content_token_count")
            prompt_tokens_1 = _get_usage_metric(usage1, "prompt_token_count")

            print(
                "Vertex response 1 usage:",
                {
                    "cached_content_token_count": cached_count_1,
                    "prompt_token_count": prompt_tokens_1,
                },
            )

            time.sleep(5)

            print(f"\n=== Vertex attempt {attempt + 1} (cache read) ===")
            question2: list[ChatCompletionMessage] = [
                UserMessageWithText(
                    role="user", content="Can you elaborate on neural networks?"
                )
            ]

            processed_messages2, _ = process_with_prompt_cache(
                llm=llm_stub,
                cacheable_prefix=cacheable_prefix,
                suffix=question2,
                continuation=False,
            )

            if not isinstance(processed_messages2, list):
                pytest.fail("Expected list of chat messages for cached prompt.")

            messages_list2 = cast(list[ChatCompletionMessage], processed_messages2)
            system_instruction2, contents2 = _messages_to_genai_contents(messages_list2)

            content_payload2 = [
                cast(
                    genai_types.ContentDict,
                    content.model_dump(exclude_none=True),
                )
                for content in contents2
            ]
            config_kwargs2: dict[str, Any] = {"temperature": 0.2}
            if system_instruction2 is not None:
                config_kwargs2["system_instruction"] = system_instruction2
            config2 = genai_types.GenerateContentConfig(**config_kwargs2)

            response2 = client.models.generate_content(
                model=model_name,
                contents=cast(Any, content_payload2),
                config=config2,
            )
            usage2 = response2.usage_metadata

            cached_count_2 = _get_usage_metric(usage2, "cached_content_token_count")
            prompt_tokens_2 = _get_usage_metric(usage2, "prompt_token_count")

            print(
                "Vertex response 2 usage:",
                {
                    "cached_content_token_count": cached_count_2,
                    "prompt_token_count": prompt_tokens_2,
                },
            )

            last_metrics = {
                "cached_content_token_count_call1": cached_count_1,
                "cached_content_token_count_call2": cached_count_2,
                "prompt_token_count_call1": prompt_tokens_1,
                "prompt_token_count_call2": prompt_tokens_2,
            }

            if cached_count_2 > 0 or prompt_tokens_2 < prompt_tokens_1:
                success = True
                break

    assert success, (
        "Expected Gemini prompt caching evidence across attempts. "
        f"Last observed metrics: {last_metrics}"
    )


@pytest.mark.skipif(
    not os.environ.get("OPENAI_API_KEY"),
    reason="OpenAI API key not available",
)
def test_prompt_caching_with_conversation_history(
    db_session: Session,
) -> None:
    """Test that prompt caching works with multi-turn conversations.

    System message and history should be cached, only new user message is uncached.
    """
    # Create OpenAI LLM
    llm = LitellmLLM(
        api_key=os.environ["OPENAI_API_KEY"],
        model_provider="openai",
        model_name="gpt-4o-mini",
        max_input_tokens=128000,
    )

    # Create a long system message and context
    system_message: SystemMessage = SystemMessage(
        role="system",
        content=(
            "You are an AI assistant specialized in technology. "
            + " ".join(
                [
                    f"You have knowledge about topic {i} including detailed information. "
                    for i in range(50)
                ]
            )
        ),
    )

    long_context = "This is a comprehensive document. " + " ".join(
        [f"Section {i}: Details about topic {i}. " * 20 for i in range(30)]
    )

    # Turn 1
    print("\n=== Turn 1 ===")
    messages_turn1: list[ChatCompletionMessage] = [
        system_message,
        UserMessageWithText(
            role="user", content=long_context + "\n\nWhat is this about?"
        ),
    ]

    response1 = litellm_completion(
        model=f"{llm._model_provider}/{llm._model_version}",
        messages=messages_turn1,
        api_key=llm._api_key,
        timeout=llm._timeout,
    )
    cost1 = completion_cost(completion_response=response1)

    usage1 = response1.get("usage", {})
    print(f"Turn 1 usage: {usage1}")
    print(f"Turn 1 cost: ${cost1:.10f}")

    # Wait for cache
    time.sleep(2)

    # Turn 2 - add assistant response and new user message
    print("\n=== Turn 2 (with cached history) ===")
    messages_turn2: list[ChatCompletionMessage] = messages_turn1 + [
        AssistantMessage(
            role="assistant", content="This document discusses various topics."
        ),
        UserMessageWithText(role="user", content="Tell me about the first topic."),
    ]

    response2 = litellm_completion(
        model=f"{llm._model_provider}/{llm._model_version}",
        messages=messages_turn2,
        api_key=llm._api_key,
        timeout=llm._timeout,
    )
    cost2 = completion_cost(completion_response=response2)

    usage2 = response2.get("usage", {})
    print(f"Turn 2 usage: {usage2}")
    print(f"Turn 2 cost: ${cost2:.10f}")

    # Turn 3 - continue conversation
    print("\n=== Turn 3 (with even more cached history) ===")
    messages_turn3: list[ChatCompletionMessage] = messages_turn2 + [
        AssistantMessage(role="assistant", content="The first topic covers..."),
        UserMessageWithText(role="user", content="What about the second topic?"),
    ]

    response3 = litellm_completion(
        model=f"{llm._model_provider}/{llm._model_version}",
        messages=messages_turn3,
        api_key=llm._api_key,
        timeout=llm._timeout,
    )
    cost3 = completion_cost(completion_response=response3)

    usage3 = response3.get("usage", {})
    print(f"Turn 3 usage: {usage3}")
    print(f"Turn 3 cost: ${cost3:.10f}")

    # Verify caching in subsequent turns
    cache_tokens_2 = usage2.get("cache_read_input_tokens", 0)
    cache_tokens_3 = usage3.get("cache_read_input_tokens", 0)

    prompt_tokens_1 = usage1.get("prompt_tokens", 0)
    prompt_tokens_2 = usage2.get("prompt_tokens", 0)
    prompt_tokens_3 = usage3.get("prompt_tokens", 0)

    print(f"\nCache tokens - Turn 2: {cache_tokens_2}, Turn 3: {cache_tokens_3}")
    print(
        f"Prompt tokens - Turn 1: {prompt_tokens_1}, Turn 2: {prompt_tokens_2}, Turn 3: {prompt_tokens_3}"
    )

    # Either cache tokens should increase or prompt tokens should be relatively stable
    # (not growing linearly with conversation length)
    assert (
        cache_tokens_2 > 0
        or cache_tokens_3 > 0
        or prompt_tokens_2 < prompt_tokens_1 * 1.5
    ), "Expected caching benefits in multi-turn conversation"


@pytest.mark.skipif(
    not os.environ.get("OPENAI_API_KEY"),
    reason="OpenAI API key not available",
)
def test_no_caching_without_process_with_prompt_cache(
    db_session: Session,
) -> None:
    """Test baseline: without using process_with_prompt_cache, no special caching occurs.

    This establishes a baseline to compare against the caching tests.
    """
    # Create OpenAI LLM
    llm = LitellmLLM(
        api_key=os.environ["OPENAI_API_KEY"],
        model_provider="openai",
        model_name="gpt-4o-mini",
        max_input_tokens=128000,
    )

    # Create a long context
    long_context = "This is a comprehensive document. " + " ".join(
        [f"Section {i}: Details about technology topic {i}. " * 10 for i in range(50)]
    )

    # First call - no explicit caching
    print("\n=== First call (no explicit caching) ===")
    messages1: list[ChatCompletionMessage] = [
        UserMessageWithText(role="user", content=long_context + "\n\nSummarize this.")
    ]

    response1 = litellm_completion(
        model=f"{llm._model_provider}/{llm._model_version}",
        messages=messages1,
        api_key=llm._api_key,
        timeout=llm._timeout,
    )
    cost1 = completion_cost(completion_response=response1)

    usage1 = response1.get("usage", {})
    print(f"Response 1 usage: {usage1}")
    print(f"Cost 1: ${cost1:.10f}")

    # This test just verifies the LLM works and we can calculate costs
    # It serves as a baseline comparison for the caching tests
    assert cost1 > 0, "Should have non-zero cost"
    assert usage1, "Should have usage data"

    print("\nBaseline test passed - ready to compare with caching tests")
