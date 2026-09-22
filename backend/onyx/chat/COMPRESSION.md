# Chat history compaction

Onyx uses native Pydantic AI harness strategies for persisted summaries and active agent history.
Application code retains branch persistence and required context placement.
It does not implement another model or tool execution loop.

## Persisted branch summaries

`compression.compact_branch` runs `SummarizingCompaction` through `TieredCompaction` and `compact_now`.
The native strategy selects older messages and generates an incremental summary.
The latest user exchange remains verbatim.
The available budget excludes tokens reserved for prompts, tools, and files.

`native_branch_history` attaches database message IDs to native message metadata.
After compaction, the persistence adapter identifies the removed rows through those IDs.
`db/chat_compaction.py` finds and stores summaries for the selected conversation branch.

Each summary remains a `ChatMessage` row:

- `parent_message_id` identifies the branch tip where compaction ran.
- `last_summarized_message_id` identifies the last summarized message.

A summary applies only when its parent belongs to the selected branch.
Later compaction includes the existing summary and newer messages.
The summarization model uses scoped provider clients, tracing, and usage accounting.

## Active agent history

`agent_runtime` uses `ClearToolResults` followed by `SlidingWindowCompaction`.
The native strategies preserve valid tool call and result pairs.
Application prompts and required file context retain their placement around compacted history.
A final budget check includes tool definitions before sending a model request.

Native provider messages remain intact throughout a run.
Thinking signatures and tool IDs do not pass through legacy message representations between requests.
