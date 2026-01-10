# Prompt Caching Framework

A comprehensive prompt-caching mechanism for enabling cost savings across multiple LLM providers by leveraging provider-side prompt token caching.

## Overview

The prompt caching framework provides a unified interface for enabling prompt caching across different LLM providers. It supports both **implicit caching** (automatic provider-side caching) and **explicit caching** (with cache control parameters).

## Features

- **Provider Support**: OpenAI (implicit), Anthropic (explicit), Vertex AI (explicit)
- **Flexible Input**: Supports both `str` and `Sequence[ChatCompletionMessage]` inputs
- **Continuation Handling**: Smart merging of cacheable prefix and suffix messages
- **Best-Effort**: Gracefully degrades if caching fails
- **Tenant-Aware**: Automatic tenant isolation for multi-tenant deployments
- **Configurable**: Enable/disable via environment variable

## Quick Start

### Basic Usage

```python
from onyx.llm.prompt_cache import process_with_prompt_cache
from onyx.llm.models import SystemMessage, UserMessage

# Assume you have an LLM instance with a config property
# llm = get_your_llm_instance()

# Define cacheable prefix (static context) using Pydantic message models
cacheable_prefix = [
    SystemMessage(role="system", content="You are a helpful assistant."),
    UserMessage(role="user", content="Context: ...")  # Static context
]

# Define suffix (dynamic user input)
suffix = [UserMessage(role="user", content="What is the weather?")]

# Process with caching - pass llm_config, not the llm instance
processed_prompt, cache_metadata = process_with_prompt_cache(
    llm_config=llm.config,
    cacheable_prefix=cacheable_prefix,
    suffix=suffix,
    continuation=False,
)

# Make LLM call with processed prompt
response = llm.invoke(processed_prompt)
```

### Using String Inputs

```python
# Both prefix and suffix can be strings
cacheable_prefix = "You are a helpful assistant. Context: ..."
suffix = "What is the weather?"

processed_prompt, cache_metadata = process_with_prompt_cache(
    llm_config=llm.config,
    cacheable_prefix=cacheable_prefix,
    suffix=suffix,
    continuation=False,
)

response = llm.invoke(processed_prompt)
```

### Continuation Flag

When `continuation=True`, the suffix is appended to the last message of the cacheable prefix:

```python
# Without continuation (default)
# Result: [system_msg, prefix_user_msg, suffix_user_msg]

# With continuation=True
# Result: [system_msg, prefix_user_msg + suffix_user_msg]
processed_prompt, _ = process_with_prompt_cache(
    llm_config=llm.config,
    cacheable_prefix=cacheable_prefix,
    suffix=suffix,
    continuation=True,  # Merge suffix into last prefix message
)
```

**Note**: If `cacheable_prefix` is a string, it remains in its own content block even when `continuation=True`.

## Provider-Specific Behavior

### OpenAI
- **Caching Type**: Implicit (automatic)
- **Behavior**: No special parameters needed. Provider automatically caches prefixes >1024 tokens.
- **Cache Lifetime**: Up to 1 hour
- **Cost Savings**: 50% discount on cached tokens

### Anthropic
- **Caching Type**: Explicit (requires `cache_control` parameter)
- **Behavior**: Automatically adds `cache_control={"type": "ephemeral"}` to the **last message** of the cacheable prefix
- **Cache Lifetime**: 5 minutes (default)
- **Limitations**: Supports up to 4 cache breakpoints

### Vertex AI
- **Caching Type**: Explicit (with `cache_control` parameter)
- **Behavior**: Adds `cache_control={"type": "ephemeral"}` to **all content blocks** in cacheable messages. String content is converted to array format with the cache control attached.
- **Cache Lifetime**: 5 minutes
- **Future**: Full context caching with block number management (deferred to future PR)

## Configuration

### Environment Variables

- `ENABLE_PROMPT_CACHING`: Enable/disable prompt caching (default: `true`)
  ```bash
  export ENABLE_PROMPT_CACHING=false  # Disable caching
  ```

## Architecture

### Core Components

1. **`processor.py`**: Main entry point (`process_with_prompt_cache`)
2. **`cache_manager.py`**: Cache metadata storage and retrieval
3. **`models.py`**: Pydantic models for cache metadata (`CacheMetadata`)
4. **`providers/`**: Provider-specific adapters
5. **`utils.py`**: Shared utility functions

### Provider Adapters

Each provider has its own adapter in `providers/`:

| File | Class | Description |
|------|-------|-------------|
| `base.py` | `PromptCacheProvider` | Abstract base class for all providers |
| `openai.py` | `OpenAIPromptCacheProvider` | Implicit caching (no transformation) |
| `anthropic.py` | `AnthropicPromptCacheProvider` | Explicit caching with `cache_control` on last message |
| `vertex.py` | `VertexAIPromptCacheProvider` | Explicit caching with `cache_control` on all content blocks |
| `noop.py` | `NoOpPromptCacheProvider` | Fallback for unsupported providers |

Each adapter implements:
- `supports_caching()`: Whether caching is supported
- `prepare_messages_for_caching()`: Transform messages for caching
- `extract_cache_metadata()`: Extract metadata from responses
- `get_cache_ttl_seconds()`: Cache TTL

## Best Practices

1. **Cache Static Content**: Use cacheable prefix for system prompts, static context, and instructions that don't change between requests.

2. **Keep Dynamic Content in Suffix**: User queries, search results, and other dynamic content should be in the suffix.

3. **Monitor Cache Effectiveness**: Check logs for cache hits/misses and adjust your caching strategy accordingly.

4. **Provider Selection**: Different providers have different caching characteristics - choose based on your use case.

## Error Handling

The framework is **best-effort** - if caching fails, it gracefully falls back to non-cached behavior:

- Cache lookup failures: Logged and continue without caching
- Provider adapter failures: Fall back to no-op adapter
- Cache storage failures: Logged and continue (caching is best-effort)
- Invalid cache metadata: Cleared and proceed without cache

## Future Enhancements

- **Explicit Caching for Vertex AI**: Full block number tracking and management
- **Cache Analytics**: Detailed metrics on cache effectiveness and cost savings
- **Advanced Strategies**: More sophisticated cache key generation and invalidation
- **Distributed Caching**: Shared caches across instances

## Examples

See `backend/tests/external_dependency_unit/llm/test_prompt_caching.py` for detailed integration test examples.
