# Prompt Caching Framework

A comprehensive prompt-caching mechanism for enabling cost savings across multiple LLM providers by leveraging provider-side prompt token caching.

## Overview

The prompt caching framework provides a unified interface for enabling prompt caching across different LLM providers. It supports both **implicit caching** (automatic provider-side caching) and **explicit caching** (with cache metadata management).

## Features

- **Provider Support**: OpenAI (implicit), Anthropic (explicit), Vertex AI (implicit)
- **Flexible Input**: Supports both `str` and `Sequence[ChatCompletionMessage]` inputs
- **Continuation Handling**: Smart merging of cacheable prefix and suffix messages
- **Best-Effort**: Gracefully degrades if caching fails
- **Tenant-Aware**: Automatic tenant isolation for multi-tenant deployments
- **Configurable**: Enable/disable via environment variable

## Quick Start

### Basic Usage

```python
from onyx.llm.prompt_cache import process_with_prompt_cache
from onyx.llm.factory import get_default_llms

# Get your LLM instance
llm, _ = get_default_llms()

# Define cacheable prefix (static context)
cacheable_prefix = [
    {"role": "system", "content": "You are a helpful assistant."},
    {"role": "user", "content": "Context: ..."}  # Static context
]

# Define suffix (dynamic user input)
suffix = [{"role": "user", "content": "What is the weather?"}]

# Process with caching
processed_prompt, cache_metadata = process_with_prompt_cache(
    llm=llm,
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
    llm=llm,
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
    llm=llm,
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
- **Behavior**: Automatically adds `cache_control={"type": "ephemeral"}` to cacheable messages
- **Cache Lifetime**: 5 minutes (default)
- **Limitations**: Supports up to 4 cache breakpoints

### Vertex AI
- **Caching Type**: Implicit (for this PR)
- **Behavior**: Similar to OpenAI - automatic caching
- **Cache Lifetime**: 5 minutes
- **Future**: Explicit caching with block number management (deferred to future PR)

## Configuration

### Environment Variables

- `ENABLE_PROMPT_CACHING`: Enable/disable prompt caching (default: `true`)
  ```bash
  export ENABLE_PROMPT_CACHING=false  # Disable caching
  ```

- `PROMPT_CACHE_REDIS_TTL_MULTIPLIER`: Cache TTL multiplier (default: `1.2`)
  ```bash
  export PROMPT_CACHE_REDIS_TTL_MULTIPLIER=1.5  # Store caches 50% longer
  ```

## Architecture

### Core Components

1. **`processor.py`**: Main entry point (`process_with_prompt_cache`)
2. **`cache_manager.py`**: Cache metadata storage and retrieval
3. **`providers/`**: Provider-specific adapters
4. **`utils.py`**: Shared utility functions

### Provider Adapters

Each provider has its own adapter that implements:
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

See the usage examples in the codebase for more detailed integration patterns.

