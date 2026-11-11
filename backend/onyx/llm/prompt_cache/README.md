# Prompt Caching Framework

Provider-side caching reduces the cost of processing repeated prompt prefixes.

## Overview

The prompt caching framework provides a unified interface for enabling prompt caching across different LLM providers. It supports both **implicit caching** (automatic provider-side caching) and **explicit caching** (with cache control parameters).

## Features

- **Provider Support**: Provider-specific adapters for OpenAI, Anthropic, Vertex AI, and compatible gateways
- **Message Input**: Accepts `list[ChatCompletionMessage]` for the prefix and suffix
- **Continuation Handling**: Smart merging of cacheable prefix and suffix messages
- **Best-Effort**: Gracefully degrades if caching fails
- **Tenant-Aware**: Automatic tenant isolation for multi-tenant deployments

## Why caching is always enabled

Onyx optimizes for the total cost of conversations and agent runs, where model calls repeatedly process large amounts of context.
A short request can end after one generation. A tool-using turn can send the same history through many generations.
Disabling caching for the first call would also prevent that call from preparing the prefix for later reuse.

The tradeoff depends on tokens reused, not the number of requests alone.
Small cache writes that never get a hit add a limited absolute cost.
Repeated reads of large prefixes can outweigh many such writes.
This is the rationale for always enabling caching on supported providers, not a guarantee that every workload costs less.

### A cost model

Compare identical model calls and output tokens at one fixed pricing tier.
Let:

- `W` be total input tokens billed as cache writes, including rewrites after misses.
- `R` be total input tokens billed as cache reads, counting every reuse.
- `U` be ordinary uncached input tokens.
- `O` be generated output tokens across all calls.
- `p` and `q` be the ordinary prices per input and output token.
- `w` and `r` be write and read prices divided by the ordinary input price.

Then:

```text
Without caching = p × (W + R + U) + q × O
With caching    = p × (wW + rR + U) + q × O
Savings         = p × ((1 - r)R - (w - 1)W)
```

Caching saves money when `(1 - r)R > (w - 1)W`.
Use separate calculations for each model, pricing tier, or cache lifetime before summing monetary savings.

For Claude Haiku 4.5 five-minute caching, `w = 1.25` and `r = 0.1`.
Thus, reads must exceed about 27.8% of writes: `R > 0.25W / 0.9`.
This is a token-weighted ratio, not a request hit rate.
For a fixed prefix used `n` times with one write and all later calls hitting, the input cost ratio is `(1.25 + 0.1(n - 1)) / n`.
Two uses save 32.5%; five save 67%. See the [customer examples](../../../../documentation/overview/getting_started/faq.mdx).

These rates come from [Anthropic's pricing](https://platform.claude.com/docs/en/build-with-claude/prompt-caching#pricing), checked November 6, 2026.
Other models and providers differ. [OpenAI's cache modes](https://developers.openai.com/api/docs/guides/prompt-caching) include both write-premium and no-write-premium pricing.
Use the applicable rates rather than a universal discount.

### Growing history and final output

New questions, tool results, and replayed assistant output can add cache writes as the prompt grows.
Count those additions in `W`; do not assume that every input token after the first call is a cache hit.

For five calls with prefixes of 10k, 12k, 14k, 16k, and 18k tokens, suppose each call reuses the entire previous prefix.
There are 18k written tokens and 52k read tokens.
At the example rates, caching costs the equivalent of 27.7k ordinary input tokens instead of 70k: a 60.4% input saving.

For a particular call, reusing `C` tokens while writing `A` new tokens saves `p × (0.9C - 0.25A)`.
That call saves input cost when `A < 3.6C`.
The run-wide decision must also include the initial write and any other misses.

The final generated answer does not get a cache-write surcharge merely because it is output.
If a later call includes that answer in its prompt, it can then become a cache write.
Otherwise, its generation cost is the same on both sides of the comparison.
Large output costs reduce the percentage saved on the total bill, not the sign of the input savings.

### Why large runs can dominate the total

At the same example rates, a 5k-token prefix written once and never reused adds 1.25k ordinary-input-token units.
A 100k-token prefix used five times costs 165k units with caching instead of 500k.
Its 335k-unit saving offsets the write premium on 268 of those isolated 5k-token requests.

These are calculated scenarios, not a measured production workload distribution.
A workload dominated by large, unique prompts or repeated cache misses can cost more.
Cache expiry, prefix changes, provider minimum lengths, and model behavior all affect reuse.

### Verify savings with usage

Use actual cache-read and cache-write token counts, including unsuccessful reuse, rather than counting tool calls.
The usage processor records `cache_read_tokens` and `cache_creation_tokens` and sends both to the model cost calculation.
Compare their cost against ordinary processing at the same model rates.
Keep output and tool charges separate when reporting input savings versus total workflow savings.

## Quick Start

### Basic Usage

```python
from onyx.llm.prompt_cache.processor import process_with_prompt_cache
from onyx.llm.model_request import SystemMessage, UserMessage

# Assume you have an LLM instance with a config property
# llm = get_your_llm_instance()

# Define cacheable prefix (static context) using Pydantic message models
cacheable_prefix = [
    SystemMessage(role="system", content="You are a helpful assistant."),
    UserMessage(role="user", content="Context: ..."),  # Static context
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
```

`processed_prompt` contains provider messages for the raw client interface.
Application generation uses shared messages; see [Language model client](../README.md).

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

**Note**: Continuation concatenates unmarked strings. Marked user messages use separate content blocks to preserve prefix and suffix cache boundaries and lifetimes. List-valued content retains its content blocks.

## Provider-Specific Behavior

### OpenAI and Azure
- **Caching Type**: Implicit, or explicit for models and endpoints that accept `prompt_cache_breakpoint`
- **Behavior**: Implicit caching needs no parameters. With explicit caching, every request marks each
  user message of the cacheable prefix and every tool result. Later steps and later turns repeat those
  markers, so they read the entries earlier requests wrote.
- **Cache Lifetime**: Depends on the model and cache mode.
- **Cost Savings**: Read discounts and write charges depend on the model and cache mode.

### Anthropic
- **Caching Type**: Explicit (requires `cache_control` parameter)
- **Behavior**: Adds breakpoints at the head, before the newest user message, and at the tail. List-valued messages carry the marker on their final content block.
- **Cache Lifetime**: 5 minutes (default)
- **Limitations**: Supports up to 4 cache breakpoints

### Vertex AI
- **Caching Type**: The factory routes all Vertex AI models through the Vertex adapter.
- **Behavior**: The adapter leaves messages unchanged, including for Vertex AI Claude. It does not add explicit cache breakpoints.
- **Limitations**: Explicit Gemini context-cache creation is not implemented.

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
| `openai.py` | `OpenAIPromptCacheProvider` | Flags every user message of the cacheable prefix for explicit breakpoints |
| `anthropic.py` | `AnthropicPromptCacheProvider` | Explicit caching at shared-context and history boundaries |
| `vertex.py` | `VertexAIPromptCacheProvider` | Implicit Gemini caching without message changes |
| `noop.py` | `NoOpPromptCacheProvider` | Fallback for unsupported providers |

Each adapter implements:
- `supports_caching()`: Whether caching is supported
- `prepare_messages_for_caching()`: Transform messages for caching
- `extract_cache_metadata()`: Extract metadata from responses
- `get_cache_ttl_seconds()`: Cache TTL

## Best Practices

1. **Cache Static Content**: Use cacheable prefix for system prompts, static context, and instructions that don't change between requests.

2. **Keep Request-Only Content in the Suffix**: Keep changing reminders outside the stable prefix. Questions and tool results can be cached when later calls repeat them.

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
