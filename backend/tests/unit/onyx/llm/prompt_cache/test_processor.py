from __future__ import annotations

from unittest.mock import patch

from onyx.llm.interfaces import LLMConfig
from onyx.llm.models import ChatCompletionMessage, SystemMessage, UserMessage
from onyx.llm.prompt_cache import processor as processor_module
from onyx.llm.prompt_cache.processor import process_with_prompt_cache


def _anthropic_config() -> LLMConfig:
    return LLMConfig(
        model_provider="anthropic",
        model_name="claude-sonnet",
        temperature=0,
        max_input_tokens=200_000,
    )


def test_with_metadata_false_skips_cache_key_hash() -> None:
    llm_config = _anthropic_config()
    prefix: list[ChatCompletionMessage] = [SystemMessage(content="stable instructions")]
    suffix: list[ChatCompletionMessage] = [UserMessage(content="new request")]

    with (
        patch.object(processor_module, "ENABLE_PROMPT_CACHING", True),
        patch.object(
            processor_module, "generate_cache_key_hash"
        ) as generate_cache_key_hash,
    ):
        processed, metadata = process_with_prompt_cache(
            llm_config=llm_config,
            cacheable_prefix=prefix,
            suffix=suffix,
            continuation=False,
            with_metadata=False,
        )

    assert metadata is None
    generate_cache_key_hash.assert_not_called()
    assert processed is not None


def test_with_metadata_true_default_keeps_current_behavior() -> None:
    llm_config = _anthropic_config()
    prefix: list[ChatCompletionMessage] = [SystemMessage(content="stable instructions")]
    suffix: list[ChatCompletionMessage] = [UserMessage(content="new request")]

    with (
        patch.object(processor_module, "ENABLE_PROMPT_CACHING", True),
        patch.object(
            processor_module,
            "generate_cache_key_hash",
            return_value="deterministic-hash",
        ) as generate_cache_key_hash,
    ):
        processed_with_metadata, metadata = process_with_prompt_cache(
            llm_config=llm_config,
            cacheable_prefix=prefix,
            suffix=suffix,
            continuation=False,
        )
        processed_without_metadata, no_metadata = process_with_prompt_cache(
            llm_config=llm_config,
            cacheable_prefix=prefix,
            suffix=suffix,
            continuation=False,
            with_metadata=False,
        )

    generate_cache_key_hash.assert_called_once()
    assert metadata is not None
    assert metadata.cache_key == "deterministic-hash"
    assert metadata.provider == "anthropic"
    assert metadata.model_name == "claude-sonnet"
    assert no_metadata is None
    assert processed_with_metadata == processed_without_metadata
