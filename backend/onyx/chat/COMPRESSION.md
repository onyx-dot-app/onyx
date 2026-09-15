# Chat history compaction

The shared Agent compacts context during execution. Chat, coding, research, and child agents use the same stage.
See [the runtime guide](../agents/README.md#compaction) for its behavior.

The runtime stores summaries as transcript checkpoints. Each checkpoint records a summary, covered message count, and source-history digest.
Context loading verifies the digest before applying the summary. Recorded messages remain available for display and artifacts.

## Legacy summary records

History loading also accepts summaries stored as `ChatMessage` rows:

- `parent_message_id` identifies the branch where the summary applies.
- `last_summarized_message_id` identifies the last covered message.

`find_summary_for_branch` selects a summary whose parent belongs to the loaded branch.
Messages after its cutoff remain in context. New compaction writes transcript checkpoints.
