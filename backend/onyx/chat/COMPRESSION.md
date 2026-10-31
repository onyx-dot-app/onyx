# Chat history compaction

The shared Agent compacts context during execution. Chat, coding, research, and child agents use the same stage.
See [the runtime guide](../agents/README.md#compaction) for its behavior.

Each checkpoint records summary text and the ID of the last covered message.
Messages keep their identities across execution, storage, and history loading.
This includes user messages, file context, assistant messages, and tool results.
A cutoff can fall within a saved response, but cannot split a tool call from its result.

For chats that retain content, Chat saves a new summary as a `ChatMessage`:

- `message_type=SUMMARY` excludes the row from public chat history.
- `parent_message_id` identifies the response where compaction occurred.
- `message` contains the summary.
- `last_summarized_message_id` identifies the last covered SDK message.

The cutoff is a string because SDK messages can be parts of a chat response or generated file context.
Existing integer cutoffs migrate to `chat:<id>`, which identifies the end of the original chat message.

History loading selects the summary from the chosen branch. The runtime finds its cutoff in the loaded messages.
It discards the checkpoint and logs the reason if that cutoff is absent or splits a tool-call group.
Reusing a summary creates no new summary row.

Compaction receives file names and IDs instead of uploaded attachment text.
It still receives findings discussed in assistant messages and tool results.
The full attachment text remains in recorded history. Project and persona file text is injected separately from compaction.

A summary records what the agent knew when it was created. Changes to file content do not invalidate it.
Chat lists files removed from context. The agent can reread them only if its available tools support file access.
Without those tools, facts found only in the attachment body are unavailable after compaction.
Request-only context is ineligible as a summary cutoff because it disappears between turns.
Compaction selects the cutoff before summarizing. It can include temporary context when the summary ends at an eligible message.

Emergency truncation stores a cutoff in run state without creating an empty SUMMARY row.
Suspended execution saves this cutoff in its execution checkpoint. A later user turn can try summarization again.
