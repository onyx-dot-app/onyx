# Chat history compaction

The shared Agent compacts context during execution. Chat, coding, research, and child agents use the same stage.
See [the runtime guide](../agents/README.md#compaction) for its behavior.

Each checkpoint records summary text, a covered model-message count, and a source-history digest.
The runtime verifies the digest before applying the summary. Original response items remain available for display.

A checkpoint can end within one saved response. Model context also contains synthetic file messages without saved response-item identities.
The count locates the covered prefix; the digest rejects it if reconstructed inputs change. A response-item ID alone cannot establish this boundary.

Chat saves a new checkpoint as a summary `ChatMessage`:

- `message_type=SUMMARY` excludes the row from public chat history.
- `parent_message_id` identifies the response where compaction occurred.
- `message` contains the summary.
- `summary_covered_count` and `summary_covered_digest` identify the exact covered prefix.

History loading selects the applicable summary from the chosen branch. Continuing with an unchanged checkpoint creates no new summary.

Historical summaries use `last_summarized_message_id` as their cutoff. Their baseline remains intact when applying a newer exact checkpoint.
Model-request preparation filters historical tool results after checkpoint selection. This keeps the saved history and its digest unchanged.
