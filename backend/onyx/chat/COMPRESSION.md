# Chat History Compression

Compresses long chat histories by summarizing older messages while keeping recent ones verbatim.

## Architecture Decisions

### Branch-Aware via Tree Structure
Summaries are stored as `ChatMessage` records with two key fields:
- `parent_message_id` → last message when compression triggered (places summary in the tree)
- `last_summarized_message_id` → pointer to an older message up the chain (the cutoff). Messages after this are kept verbatim.

**Why store summary as a separate message?** If we embedded the summary in the `last_summarized_message_id` message itself, that message would contain context from messages that came after it—context that doesn't exist in other branches. By creating the summary as a new message hanging off the tree (never on the mainline — it doesn't update `latest_child_message_id`), the original history remains intact and branching keeps working.

**Why match summaries by cutoff, not parent?** A summary applies to a branch when its
cutoff (`last_summarized_message_id`) is on that branch. Every message has exactly one
parent, so the path from the root to the cutoff is unique: any branch containing the
cutoff shares the entire summarized prefix. Matching on the summary's
`parent_message_id` instead (the original design) was fragile — `latest_child_message_id`
is rewritten whenever a sibling is created, so any regenerate, edit, retry, or
concurrent send after the summary's parent orphaned every existing summary. Affected
sessions then re-summarized their full history at the end of every turn and their
prompts were never truncated. Trade-off: the summarization prompt shows post-cutoff
messages "for context only", so a summary reused across a fork may carry faint context
from a sibling branch — accepted versus losing compression entirely.

### Progressive Summarization
Subsequent compressions incorporate the existing summary text + new messages, preventing information loss in very long conversations.

### Cutoff Marker Prompt Strategy
The LLM receives older messages, a cutoff marker, then recent messages. It summarizes only content before the marker while using recent context to inform what's important.

## Token Budget

Context window breakdown:
- `max_context_tokens` — LLM's total context window
- `reserved_tokens` — space for system prompt, tools, files, etc.
- Available for chat history = `max_context_tokens - reserved_tokens`
Note: If there is a lot of reserved tokens, chat compression may happen fairly frequently which is costly, slow, and leads to a bad user experience. Possible area of future improvement.

Configurable ratios:
- `COMPRESSION_TRIGGER_RATIO` (default 0.75) — compress when chat history exceeds this ratio of available space
- `RECENT_MESSAGES_RATIO` (default 0.2) — portion of chat history to keep verbatim when compressing

## Flow

1. Trigger when `effective_tokens > available * 0.75`, where effective tokens are what
   the next prompt will actually contain: applicable summary + post-cutoff messages
   (the raw chain total would re-trigger every turn once a session ever crossed the
   threshold, since already-summarized messages still count toward it)
2. Acquire the per-session compression lock (skip if another compression is in flight —
   concurrent turns/retries would otherwise duplicate the expensive summarization call)
3. Find existing summary for branch (if any)
4. Split messages: older (summarize) / recent (keep 25%); skip if the older portion is
   below `MIN_TOKENS_TO_COMPRESS` (not worth an LLM round-trip)
5. Generate summary via LLM
6. Save as `ChatMessage` with `parent_message_id` + `last_summarized_message_id`

If no summary applies at prompt-build time and the history exceeds the trigger
threshold anyway (compression in flight, failed, or not yet run), the history is
hard-trimmed to a recent suffix (`trim_history_to_token_budget`) so prompt size stays
bounded regardless.

## Key Functions

| Function | Purpose |
|----------|---------|
| `get_compression_params` | Check if compression needed based on token counts |
| `find_summary_for_branch` | Find applicable summary by checking cutoff membership in the branch (highest cutoff wins) |
| `get_messages_to_summarize` | Split messages at token budget boundary |
| `compress_chat_history` | Orchestrate flow under the per-session lock, save summary message |
| `calculate_effective_history_tokens` | Prompt-effective token count (summary + post-cutoff) for the trigger |
| `trim_history_to_token_budget` | Fallback hard-trim when no summary applies |
