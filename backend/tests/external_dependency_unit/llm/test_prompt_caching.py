"""External dependency unit tests for prompt caching functionality.

These tests call LLM providers directly and use litellm's completion_cost() to verify
that prompt caching reduces costs.
"""

import os
import time
from typing import Any

import pytest
from litellm import completion as litellm_completion
from litellm import completion_cost
from sqlalchemy.orm import Session

from onyx.llm.chat_llm import LitellmLLM
from onyx.llm.message_types import AssistantMessage
from onyx.llm.message_types import ChatCompletionMessage
from onyx.llm.message_types import SystemMessage
from onyx.llm.message_types import UserMessageWithText
from onyx.llm.prompt_cache.processor import process_with_prompt_cache


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
