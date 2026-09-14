# Chat History Compression

Compresses long chat histories by summarizing older messages while keeping recent ones verbatim.

## Architecture Decisions

### Branch-Aware via Tree Structure
Summaries are stored as `ChatMessage` records with two key fields:
- `parent_message_id` → latest user message when compression triggered (places summary in the tree)
- `last_summarized_message_id` → pointer to an older message up the chain (the cutoff). Messages after this are kept verbatim.

**Why store summary as a separate message?** A separate record limits the summary to branches that contain its parent.
The parent is the latest user message, so sibling answers can share the summary.
The cutoff identifies the older messages that the summary replaces.

### Progressive Summarization
Subsequent compressions incorporate the existing summary text and new messages. Summarization can lose detail.

### Cutoff Marker Prompt Strategy
The LLM receives older messages, a cutoff marker, then recent messages. It summarizes only content before the marker while using recent context to inform what's important.

## Token Budget

Token estimates use stored agent transcripts when available and stored token counts for older records.

Context window breakdown:
- `max_context_tokens` — LLM's total context window
- `reserved_tokens` — space for system prompt, tools, files, etc.
- Available for chat history = `max_context_tokens - reserved_tokens`
Note: If there is a lot of reserved tokens, chat compression may happen fairly frequently which is costly, slow, and leads to a bad user experience. Possible area of future improvement.

Configurable ratios:
- `COMPRESSION_TRIGGER_RATIO` (default 0.75) — compress when chat history exceeds this ratio of available space
- `RECENT_MESSAGES_RATIO` (default 0.2) — portion of chat history to keep verbatim when compressing

## Flow

1. Trigger when `history_tokens > available * 0.75`
2. Find existing summary for branch (if any)
3. Split messages: older (summarize) / recent (target 20%, keeping complete user exchanges)
4. Generate summary via LLM
5. Save as `ChatMessage` with `parent_message_id` + `last_summarized_message_id`

## Key Functions

| Function | Purpose |
|----------|---------|
| `get_compression_params` | Check if compression needed based on token counts |
| `find_summary_for_branch` | Find applicable summary by checking `parent_message_id` membership |
| `get_messages_to_summarize` | Split messages at token budget boundary |
| `compress_chat_history` | Orchestrate flow, save summary message |
