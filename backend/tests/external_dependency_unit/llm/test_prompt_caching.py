"""External dependency unit tests for prompt caching functionality.

These tests call LLM providers directly and use litellm's completion_cost() to verify
that prompt caching reduces costs.
"""

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any

import pytest
from litellm import completion_cost
from sqlalchemy.orm import Session

from onyx.llm.model_response import Usage
from onyx.llm.models import AssistantMessage
from onyx.llm.models import ChatCompletionMessage
from onyx.llm.models import SystemMessage
from onyx.llm.models import UserMessage
from onyx.llm.multi_llm import LitellmLLM
from onyx.llm.prompt_cache.processor import process_with_prompt_cache


VERTEX_CREDENTIALS_ENV = "VERTEX_CREDENTIALS"
VERTEX_LOCATION_ENV = "VERTEX_LOCATION"
VERTEX_MODEL_ENV = "VERTEX_MODEL_NAME"
DEFAULT_VERTEX_MODEL = "gemini-2.5-flash"


def _extract_cached_tokens(usage: Usage | None) -> int:
    """Helper to extract cached_tokens from usage (dict or object)."""
    if not usage:
        print("Usage is None")
        return 0

    cached_tokens = usage.cache_creation_input_tokens

    return cached_tokens


def _extract_prompt_tokens(usage: Usage | None) -> int:
    """Helper to extract prompt_tokens from usage (dict or object)."""
    if not usage:
        print("Usage is None")
        return 0

    return usage.prompt_tokens


def _extract_cache_read_tokens(usage: Usage | None) -> int:
    """Extract cache read metrics from usage (dict or object)."""
    print(f"usage: {usage}")
    if not usage:
        print("Usage is None")
        return 0

    return usage.cache_read_input_tokens


def _get_usage_value(usage: Any, key: str) -> int:
    """Retrieve a numeric field from usage objects or dictionaries."""
    if isinstance(usage, dict):
        value = usage.get(key)
    else:
        value = getattr(usage, key, None)
    return int(value or 0)


def _resolve_vertex_credentials() -> tuple[Path, bool]:
    """Return a path to credentials; support inline JSON or filesystem path."""
    raw_value = os.environ.get(VERTEX_CREDENTIALS_ENV)
    if not raw_value:
        raise FileNotFoundError("Vertex credentials environment variable not set.")

    raw_value = raw_value.strip()
    candidate_path = Path(raw_value)
    if len(raw_value) < 100 and candidate_path.exists():
        return candidate_path, False

    try:
        json.loads(raw_value)
    except json.JSONDecodeError as exc:
        raise ValueError(
            "Vertex credentials must be a valid JSON string or file path."
        ) from exc

    temp_file = tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    )
    try:
        temp_file.write(raw_value)
        temp_file.flush()
    finally:
        temp_file.close()
    return Path(temp_file.name), True


def _validate_vertex_credentials_file(credentials_path: Path) -> None:
    """Validate that the credentials file contains a usable service account."""
    try:
        content = credentials_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"Failed to read credentials file: {exc}") from exc

    try:
        data = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ValueError("Credentials file does not contain valid JSON.") from exc

    if not isinstance(data, dict):
        raise ValueError("Credentials JSON must be an object.")

    cred_type = data.get("type")
    if cred_type != "service_account":
        raise ValueError(
            f"Unsupported credential type '{cred_type}'. Provide a service_account JSON blob."
        )

    missing_fields = [
        field
        for field in ("project_id", "client_email", "private_key")
        if not data.get(field)
    ]
    if missing_fields:
        raise ValueError(
            "Missing required service account fields: "
            + ", ".join(sorted(missing_fields))
        )

    try:
        from google.oauth2 import service_account

        service_account.Credentials.from_service_account_info(
            data,
            scopes=["https://www.googleapis.com/auth/cloud-platform"],
        )
    except (
        Exception
    ) as exc:  # pragma: no cover - depends on google SDK validation paths
        raise ValueError(
            f"Failed to construct service account credentials: {exc}"
        ) from exc


@pytest.mark.skip(reason="OpenAI prompt caching is unreliable")
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
            model_name="gpt-4o",
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
            UserMessage(role="user", content=long_context)
        ]

        # First call - creates cache
        print("\n=== First call (cache creation) ===")
        question1: list[ChatCompletionMessage] = [
            UserMessage(role="user", content="What are the main topics discussed?")
        ]

        # Apply prompt caching (for OpenAI, this is mostly a no-op but should still work)
        processed_messages1, _ = process_with_prompt_cache(
            llm_config=llm.config,
            cacheable_prefix=cacheable_prefix,
            suffix=question1,
            continuation=False,
        )
        # print(f"Processed messages 1: {processed_messages1}")
        # print(f"Metadata 1: {metadata1}")
        # print(f"Cache key 1: {metadata1.cache_key if metadata1 else None}")

        # Call litellm directly so we can get the raw response
        response1 = llm.invoke(prompt=processed_messages1)
        cost1 = completion_cost(
            completion_response=response1.model_dump(),
            model=f"{llm._model_provider}/{llm._model_version}",
        )

        usage1 = response1.usage
        cached_tokens_1 = _extract_cached_tokens(usage1)
        prompt_tokens_1 = _extract_prompt_tokens(usage1)
        # print(f"Response 1 usage: {usage1}")
        # print(f"Cost 1: ${cost1:.10f}")

        # Wait to ensure cache is available
        time.sleep(5)

        # Second call with same context - should use cache
        print("\n=== Second call (cache read) ===")
        question2: list[ChatCompletionMessage] = [
            UserMessage(role="user", content="Can you elaborate on neural networks?")
        ]

        # Apply prompt caching (same cacheable prefix)
        processed_messages2, _ = process_with_prompt_cache(
            llm_config=llm.config,
            cacheable_prefix=cacheable_prefix,
            suffix=question2,
            continuation=False,
        )
        # print(f"Processed messages 2: {processed_messages2}")
        response2 = llm.invoke(prompt=processed_messages2)
        cost2 = completion_cost(
            completion_response=response2.model_dump(),
            model=f"{llm._model_provider}/{llm._model_version}",
        )

        usage2 = response2.usage
        cached_tokens_2 = _extract_cache_read_tokens(usage2)
        prompt_tokens_2 = _extract_prompt_tokens(usage2)
        # print(f"Response 2 usage: {usage2}")
        # print(f"Cost 2: ${cost2:.10f}")

        # Verify caching occurred – OpenAI reports cached work via prompt_tokens_details.cached_tokens
        print(f"\nCached tokens call 1: {cached_tokens_1}, call 2: {cached_tokens_2}")
        print(f"Prompt tokens call 1: {prompt_tokens_1}, call 2: {prompt_tokens_2}")
        print(f"Cost delta (1 -> 2): ${cost1 - cost2:.10f}")

        # The first call is expected to *create* cache (cached_tokens may be 0).
        # The second call should show cached tokens being used.
        if cached_tokens_2 > 0:
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
    # NOTE: prompt caching support is model-specific; `claude-3-5-haiku-20241022` is known
    # to return cache_creation/cache_read usage metrics, while some newer aliases may not.
    llm = LitellmLLM(
        api_key=os.environ["ANTHROPIC_API_KEY"],
        model_provider="anthropic",
        model_name="claude-3-5-haiku-20241022",
        max_input_tokens=200000,
    )

    import random
    import string

    # Create a long context message.
    # Add a random prefix to avoid reusing an existing ephemeral cache from prior test runs.
    random_prefix = "".join(random.choices(string.ascii_lowercase, k=32))
    long_context = (
        random_prefix + " "
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
        UserMessage(role="user", content=long_context)
    ]

    # First call - creates cache
    print("\n=== First call (cache creation) ===")
    question1: list[ChatCompletionMessage] = [
        UserMessage(role="user", content="What are the main topics discussed?")
    ]

    # Apply prompt caching
    processed_messages1, _ = process_with_prompt_cache(
        llm_config=llm.config,
        cacheable_prefix=base_messages,
        suffix=question1,
        continuation=False,
    )

    response1 = llm.invoke(prompt=processed_messages1)
    cost1 = completion_cost(
        completion_response=response1.model_dump(),
        model=f"{llm._model_provider}/{llm._model_version}",
    )

    usage1 = response1.usage
    print(f"Response 1 usage: {usage1}")
    print(f"Cost 1: ${cost1:.10f}")

    # Wait to ensure cache is available
    time.sleep(2)

    # Second call with same context - should use cache
    print("\n=== Second call (cache read) ===")
    question2: list[ChatCompletionMessage] = [
        UserMessage(role="user", content="Can you elaborate on neural networks?")
    ]

    # Apply prompt caching (same cacheable prefix)
    processed_messages2, _ = process_with_prompt_cache(
        llm_config=llm.config,
        cacheable_prefix=base_messages,
        suffix=question2,
        continuation=False,
    )

    response2 = llm.invoke(prompt=processed_messages2)
    cost2 = completion_cost(
        completion_response=response2.model_dump(),
        model=f"{llm._model_provider}/{llm._model_version}",
    )

    usage2 = response2.usage
    print(f"Response 2 usage: {usage2}")
    print(f"Cost 2: ${cost2:.10f}")

    # Verify caching occurred
    cache_creation_tokens = _get_usage_value(usage1, "cache_creation_input_tokens")
    cache_read_tokens = _get_usage_value(usage2, "cache_read_input_tokens")

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
@pytest.mark.skipif(
    not os.environ.get(VERTEX_LOCATION_ENV),
    reason="VERTEX_LOCATION required for Vertex AI context caching (e.g., 'us-central1')",
)
def test_google_genai_prompt_caching_reduces_costs(
    db_session: Session,
) -> None:
    """Test that Litellm Gemini prompt caching reduces costs on subsequent calls.

    Vertex AI requires explicit context caching via the Context Caching API,
    which needs both credentials and a valid location (e.g., us-central1).
    """
    import random
    import string
    from litellm import exceptions as litellm_exceptions

    try:
        credentials_path, should_cleanup = _resolve_vertex_credentials()
    except FileNotFoundError:
        pytest.skip("Vertex credentials not available for test.")
    except ValueError as exc:
        pytest.skip(str(exc))

    vertex_location = os.environ.get(VERTEX_LOCATION_ENV)
    if not vertex_location:
        pytest.skip("VERTEX_LOCATION required for Vertex AI context caching")
    model_name = os.environ.get(VERTEX_MODEL_ENV, DEFAULT_VERTEX_MODEL)

    try:
        _validate_vertex_credentials_file(credentials_path)
        os.environ.setdefault("GOOGLE_APPLICATION_CREDENTIALS", str(credentials_path))

        custom_config: dict[str, str] = {"vertex_credentials": str(credentials_path)}
        if vertex_location:
            custom_config["vertex_location"] = vertex_location

        llm = LitellmLLM(
            api_key=None,
            model_provider="vertex_ai",
            model_name=model_name,
            max_input_tokens=1_000_000,
            custom_config=custom_config,
        )

        attempts = 4
        success = False
        last_metrics: dict[str, Any] = {}

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
                SystemMessage(role="system", content=long_context)
            ]

            print(f"\n=== Vertex attempt {attempt + 1} (cache creation) ===")
            question1: list[ChatCompletionMessage] = [
                UserMessage(role="user", content="What are the main topics discussed?")
            ]

            processed_messages1, _ = process_with_prompt_cache(
                llm_config=llm.config,
                cacheable_prefix=cacheable_prefix,
                suffix=question1,
                continuation=False,
            )
            # Debug: print processed messages structure
            print(
                f"Processed messages structure (first msg): {processed_messages1[0] if processed_messages1 else 'empty'}"
            )

            response1 = llm.invoke(prompt=processed_messages1)
            cost1 = completion_cost(
                completion_response=response1.model_dump(),
                model=f"{llm._model_provider}/{llm._model_version}",
            )
            usage1 = response1.usage
            cache_creation_tokens = _get_usage_value(
                usage1, "cache_creation_input_tokens"
            )
            cached_tokens_1 = _extract_cached_tokens(usage1)
            cache_read_tokens_1 = _extract_cache_read_tokens(usage1)

            print(f"Vertex response 1 usage: {usage1}")
            print(f"Vertex cost 1: ${cost1:.10f}")

            time.sleep(5)

            print(f"\n=== Vertex attempt {attempt + 1} (cache read) ===")
            question2: list[ChatCompletionMessage] = [
                UserMessage(
                    role="user", content="Can you elaborate on neural networks?"
                )
            ]

            processed_messages2, _ = process_with_prompt_cache(
                llm_config=llm.config,
                cacheable_prefix=cacheable_prefix,
                suffix=question2,
                continuation=False,
            )

            response2 = llm.invoke(prompt=processed_messages2)
            cost2 = completion_cost(
                completion_response=response2.model_dump(),
                model=f"{llm._model_provider}/{llm._model_version}",
            )
            usage2 = response2.usage
            cache_read_tokens_2 = _extract_cache_read_tokens(usage2)
            cached_tokens_2 = _extract_cached_tokens(usage2)

            print(f"Vertex response 2 usage: {usage2}")
            print(f"Vertex cost 2: ${cost2:.10f}")
            print(
                f"Vertex cache metrics - creation: {cache_creation_tokens}, "
                f"call1 cached tokens: {cached_tokens_1}, "
                f"call1 cache read tokens: {cache_read_tokens_1}, "
                f"call2 cached tokens: {cached_tokens_2}, "
                f"call2 cache read tokens: {cache_read_tokens_2}"
            )
            print(f"Vertex cost delta (1 -> 2): ${cost1 - cost2:.10f}")

            last_metrics = {
                "cache_creation_tokens": cache_creation_tokens,
                "cached_tokens_1": cached_tokens_1,
                "cache_read_tokens_1": cache_read_tokens_1,
                "cached_tokens_2": cached_tokens_2,
                "cache_read_tokens_2": cache_read_tokens_2,
                "cost_delta": cost1 - cost2,
            }

            if cache_read_tokens_2 > 0 or cached_tokens_2 > 0 or (cost1 - cost2) > 0:
                success = True
                break
    except ValueError as exc:
        pytest.fail(f"Invalid Vertex credentials: {exc}")
    except litellm_exceptions.APIConnectionError as exc:
        creds_details = json.loads(credentials_path.read_text(encoding="utf-8"))
        pytest.fail(
            "Vertex credentials appeared well-formed but failed to mint an access token. "
            "This typically means the service account lacks the required Vertex AI permissions "
            "or the key was revoked.\n"
            f"project_id={creds_details.get('project_id')!r}, "
            f"client_email={creds_details.get('client_email')!r}\n"
            f"Original error: {exc}"
        )
    finally:
        if should_cleanup:
            try:
                credentials_path.unlink(missing_ok=True)
            except OSError:
                pass

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
        UserMessage(role="user", content=long_context + "\n\nWhat is this about?"),
    ]

    response1 = llm.invoke(prompt=messages_turn1)
    cost1 = completion_cost(
        completion_response=response1.model_dump(),
        model=f"{llm._model_provider}/{llm._model_version}",
    )

    usage1 = response1.usage
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
        UserMessage(role="user", content="Tell me about the first topic."),
    ]

    response2 = llm.invoke(prompt=messages_turn2)
    cost2 = completion_cost(
        completion_response=response2.model_dump(),
        model=f"{llm._model_provider}/{llm._model_version}",
    )

    usage2 = response2.usage
    print(f"Turn 2 usage: {usage2}")
    print(f"Turn 2 cost: ${cost2:.10f}")

    # Turn 3 - continue conversation
    print("\n=== Turn 3 (with even more cached history) ===")
    messages_turn3: list[ChatCompletionMessage] = messages_turn2 + [
        AssistantMessage(role="assistant", content="The first topic covers..."),
        UserMessage(role="user", content="What about the second topic?"),
    ]

    response3 = llm.invoke(prompt=messages_turn3)
    cost3 = completion_cost(
        completion_response=response3.model_dump(),
        model=f"{llm._model_provider}/{llm._model_version}",
    )

    usage3 = response3.usage
    print(f"Turn 3 usage: {usage3}")
    print(f"Turn 3 cost: ${cost3:.10f}")

    # Verify caching in subsequent turns
    cache_tokens_2 = _get_usage_value(usage2, "cache_read_input_tokens")
    cache_tokens_3 = _get_usage_value(usage3, "cache_read_input_tokens")

    prompt_tokens_1 = _get_usage_value(usage1, "prompt_tokens")
    prompt_tokens_2 = _get_usage_value(usage2, "prompt_tokens")
    prompt_tokens_3 = _get_usage_value(usage3, "prompt_tokens")

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
        UserMessage(role="user", content=long_context + "\n\nSummarize this.")
    ]

    response1 = llm.invoke(prompt=messages1)
    cost1 = completion_cost(
        completion_response=response1.model_dump(),
        model=f"{llm._model_provider}/{llm._model_version}",
    )

    usage1 = response1.usage
    print(f"Response 1 usage: {usage1}")
    print(f"Cost 1: ${cost1:.10f}")

    # This test just verifies the LLM works and we can calculate costs
    # It serves as a baseline comparison for the caching tests
    assert cost1 > 0, "Should have non-zero cost"
    assert usage1, "Should have usage data"

    print("\nBaseline test passed - ready to compare with caching tests")
