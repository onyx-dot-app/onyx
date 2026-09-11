# Chat History Compression

Compresses long chat histories by summarizing older messages while keeping recent ones verbatim.

## Architecture Decisions

### Branch-Aware via Tree Structure
Summaries are stored as `ChatMessage` records with two key fields:
- `parent_message_id` → last message when compression triggered (places summary in the tree)
- `last_summarized_message_id` → pointer to an older message up the chain (the cutoff). Messages after this are kept verbatim.

**Why store summary as a separate message?** If we embedded the summary in the `last_summarized_message_id` message itself, that message would contain context from messages that came after it—context that doesn't exist in other branches. By creating the summary as a new message attached to the branch tip, it only applies to the specific branch where compression occurred. It's only back-pointed to by the
branch which it applies to. All of this is necessary because we keep the last few messages verbatim and also to support branching logic.

### Progressive Summarization
Subsequent compressions incorporate the existing summary text + new messages, preventing information loss in very long conversations.

### Cutoff Marker Prompt Strategy
The LLM receives older messages, a cutoff marker, then recent messages. It summarizes only content before the marker while using recent context to inform what's important.

## Token Budget

Resolve each selected model's budget through `resolve_chat_token_budget`:

```text
raw_input = min(configured_input_cap, model_input_max,
                model_context_capacity - model_output_reserve)
safe_input = floor(raw_input * (1 - tokenizer_safety_margin))
history_capacity = max(0, safe_input - other_replayed_input)
trigger = floor(history_capacity * COMPRESSION_TRIGGER_RATIO)
```

The output reserve uses the model's explicit output maximum and includes reasoning.
The configured input cap is independent of the model's total context capacity.
Use explicit context metadata when available. Otherwise, use the model metadata's
input maximum as a conservative context bound. Never infer context capacity from
the ambiguous legacy `max_tokens` field.

If usable model specifications are missing, preserve the existing configured/default
input allowance and provider-default output behavior. The default input lookup
already holds back `GEN_AI_NUM_RESERVED_OUTPUT_TOKENS`, so do not subtract it again.

The tokenizer safety margin defaults to 5%. It protects against estimation errors.
The compression buffer is separate and leaves space for continued work.

`other_replayed_input` includes system/custom prompts, reminders, tool definitions,
project context, and replay content absent from stored message token counts.
The latter includes file payloads, image payloads or markers, and tool results.
Count each contribution once. Use the actual replay cost for the selected model.

Multi-model chats share the smallest safe input allowance and greatest measured
overhead. The shared compression decision waits for participating models and their
persistence to finish, so a fast model cannot hide a slower model's larger overhead.

Configurable ratios:

- `COMPRESSION_TRIGGER_RATIO` defaults to `0.90`. An environment override still takes precedence.
- `RECENT_MESSAGES_RATIO` is `0.2`. Bound the recent-history token budget by this fraction of available history capacity.

Compression retains its post-answer lifecycle. Each model call still fits history
to the hard input allowance; compression does not run inside the tool loop.
Cancelled or crashed in-flight turns do not start compression after the processing
fence is released. The next completed turn can check compression again.

## Flow

1. After response persistence, trigger when `history_tokens > history_capacity * COMPRESSION_TRIGGER_RATIO`.
2. Find existing summary for branch (if any)
3. Split messages: older messages to summarize and recent messages within their token budget.
4. Generate summary via LLM
5. Save as `ChatMessage` with `parent_message_id` + `last_summarized_message_id`

## Key Functions

| Function | Purpose |
|----------|---------|
| `resolve_chat_token_budget` | Resolve model-specific input, output, context, and safety limits |
| `run_chat_history_compression` | Check the saved branch and run shared compression after persistence |
| `get_compression_params` | Check if compression needed based on token counts |
| `find_summary_for_branch` | Find applicable summary by checking `parent_message_id` membership |
| `get_messages_to_summarize` | Split messages at token budget boundary |
| `compress_chat_history` | Orchestrate flow, save summary message |
