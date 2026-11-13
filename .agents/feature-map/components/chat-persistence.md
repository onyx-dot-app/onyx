# Chat Persistence

> How a conversation is stored and read back: the session, the message tree and
> its branches, model steps, tool calls, surfaced documents, feedback, sharing,
> incognito, history search and retention. Each answer row is reserved before the
> run, marked running when the run starts, and finalized in one transaction;
> every reload, share link and later turn reads that record.

**Verified against:** `6bac4e012f` (2026-10-29)
**Edition:** CE. The chat retention job is EE.

---

## User experience

- **A user** sees the chats they own in the sidebar, newest update first.
  Incognito sessions, `onyxbot_flow` sessions, and sessions that hold only
  the root row five minutes after creation do not appear
  (`db/chat.py:get_chat_sessions_by_user`). Opening a chat replays it as it
  looked live: reasoning, tool steps, sources, the answer and its citations.
- **A user who edits a sent message** gets a new branch, not an overwrite. The
  conversation continues from the edit. A branch switcher moves between the
  original and each edit, and the rest of the conversation follows the chosen
  branch. Regenerate adds a new answer next to the old one under the same
  question.
- **A user who sent one message to several models** picks the answer to keep.
  The pick becomes the branch that later messages continue from. If the user
  sends a follow-up without a pick, the client picks for them
  ([[chat-frontend]]).
- **A user can rate an answer.** In Slack, a user can also endorse, reject or
  hide one retrieved document. That changes the document's boost or hidden flag
  for every user's later searches
  (`db/feedback.py:create_doc_retrieval_feedback`). The web chat has no
  document feedback.
- **A user can share a chat.** Any signed-in user with the link, or an
  anonymous user when anonymous access is on, sees a read-only copy. Deleting the chat hides it from the link but does not unshare
  it.
- **A user can search their own history** by title and message text.
  Incognito chats never match.
- **A user in incognito** sees the chat vanish from their history, search and
  projects. An admin security setting decides who may start one: nobody (the
  default), everyone, or members of chosen groups. Anonymous users never can.
  A second admin setting decides what the workspace keeps: the whole
  conversation (full history), or blank rows with token counts (usage only).
  In usage-only mode the conversation lives in Redis until the tab closes or
  an hour of idle time passes, and the chat never gets a title.
- **An EE admin** sets a retention window in days. A chat with no activity for
  that long is deleted with no warning. A CE deployment never deletes chats on
  its own.
- **An API caller** reads a session with `GET /chat/get-chat-session/{id}`. The
  response holds the messages and, for each answer, the packets that rebuild
  it. A send that names a parent off the active branch fails with "not on the
  latest mainline".

---

## Scope

This component owns the chat tables (`ChatSession`, `ChatMessage`, `ToolCall`,
`SearchDoc`, `chat_response_item`, `chat_response_checkpoint`, the two
feedback tables), the code that writes and reads them, the two history stores
(Postgres and the incognito Redis store), child sessions of sub-agents, replay
of a saved answer as packets, incognito storage, retention, and the session
lifecycle endpoints: list, read, rename, share, delete, branch switch,
multi-model pick, feedback and incognito teardown.

Neighbours own the rest. [[core-chat-loop]] owns the send endpoint, the turn
admission, response ownership leases, Stop and stream resume. [[agent-runtime]]
owns the run, its records and the checkpoint data model; this component stores
them. [[context-assembly]] turns saved history into a prompt and owns
compaction. [[citations]] owns the numbers that `ChatMessage.citations` stores.
[[auth-and-identity]] stores the security settings that hold incognito
availability and the record mode; this component applies them.

---

## Architecture

```
prepare_chat_turn                          chat/process_message.py
  create_new_chat_message (user row)       commits in one transaction with
  reserve_chat_response_ids                db/chat.py: assistant row(s), placeholder
                                           text, response_status NULL; moves the
                                           parent's active pointer to it
  RedisChatHistoryStore.save_user_messages      USAGE_ONLY: Redis, after reservation
ChatRunStore (content-persisting only)     chat/run_store.py; each save commits alone
  register (run start)                     save_response_record__no_commit: RUNNING,
                                           no steps yet
  reserve_run_id (sub-agent)               saves the parent's steps so far, then
                                           reserve_child_response__no_commit
  save (child run end)                     _save_output -> save_chat_turn: terminal
                                           record, display data and source links
  save (root run end)                      ownership check, then:
ChatResponsePersistence.save               chat/persistence.py; for USAGE_ONLY it is
                                           the run store itself (no ChatRunStore)
  ChatHistoryStore.save_response           chat/history_store.py: Postgres or Redis
    save_chat_response_to_db               db/chat_response.py: checks the record
                                           mode, drops the checkpoint, then:
      save_chat_turn                       ONE commit: text, SearchDoc rows, links,
                                           citations, final records
GET /chat/get-chat-session/{id}
  get_chat_message_page_ids                with `limit`: one page of the current
                                           branch and the children of its messages
  get_chat_messages_by_session             that page, or all branches without
                                           `limit`; two ToolCall levels
  translate_assistant_message_to_packets   runtime rows: read_chat_execution,
                                           read_response_replay_data ->
                                           chat/presentation.py:replay_response;
                                           legacy rows: per-tool builders
```

**Two response formats.** `ChatMessage.response_status` tells them apart. A
row with a status is a runtime response. Each model step is a
`chat_response_item` that holds the whole assistant message (text, thinking,
tool calls) in `step_index` order. Each tool call is a `ToolCall` row whose
typed result is in `ToolCall.result` (`db/models.py:StoredToolResult`). A row
with a NULL status is a legacy response, or a row with no saved run
([[#reserved-row-resolves]]). Legacy tool output is in the `tool_call_response`
column (mapped as `legacy_response`) and its reasoning in the
`reasoning_tokens` columns. History (`chat/chat_utils.py:capture_chat_history`)
and replay (`db/chat_response.py:read_chat_execution`) use the runtime path
only when the row has a status and the session's pinned mode keeps content, so
a `USAGE_ONLY` answer takes the legacy path. Reasoning display
(`db/chat.py:get_chat_message_reasoning`) checks the status only.
`backend/onyx/db/README.md` describes only the legacy format.

**The tree.** Each session has one root row: `SYSTEM` type, no parent, empty
text (`db/chat.py:get_or_create_root_message`). A user message starts a turn;
unread child results start a turn under a hidden `AGENT_RESULTS` question after a
completed assistant response. Two assistant rows never follow each other. An edit adds a sibling user row under the same parent. A
regenerate is a send whose parent is the user row, so
`chat/process_message.py:prepare_chat_turn` reuses that row and adds a sibling
answer. Each row's `latest_child_message_id` marks the active child. Walking
those pointers from the root gives the active conversation
(`db/chat.py:create_chat_history_chain`). A branch switch moves one pointer
(`db/chat.py:set_as_latest_chat_message`). A multi-model pick sets
`preferred_response_id` and moves the same pointer (`db/chat.py:set_preferred_response`).

**Child sessions.** When a research, coding or background sub-agent runs in a
content-persisting chat, `reserve_child_response__no_commit` creates a
`ChatSession` with `spawned_by_message_id` set to the parent response. It
copies the root's user, agent, Slack flag and record mode. A child session has
no `SYSTEM` root: its first question has no parent, and
`invoking_tool_call_id` links it to the parent's `ToolCall`, which
`ChatRunStore.reserve_run_id` saves first. A later call to the same sub-agent
reuses its child session and chains the new question to the previous
response, which must be terminal. Creation links determine authorized ancestors;
the invoking tool identifies the requester of each run. A child's result goes
to the agent that spawned it, also for runs that a later instruction started
(`db/chat_inputs.py:reserve_inbox_run__no_commit`). An automatic response
to child output links directly to the previous assistant response and retains
its original invocation. It creates no user-message row. An ancestor can request
a grandchild's next run without changing the grandchild's session ancestry.
`db/chat_response.py:_ResponseWriter.store`
refuses a run tree deeper than 8 or larger than 512 runs, and a run with more
than 8192 messages, so a very large research turn fails its save. Hard delete and
retention treat the root and its descendants as one conversation
(`db/chat.py:session_descendants`). A failed child start deletes the unused
question, response and empty child session
(`db/chat_response.py:abort_response_start__no_commit`). Child answers retain
their own source links. Reads prefer those sources and fall back to the root
response's sources for earlier saved children.
`db/chat_subagents.py:load_session_agent_metadata` limits recent agents but
also returns their ancestors, so discovery can reach each selected descendant.

**Tool calls.** On a runtime response, `parent_chat_message_id` always names
the owning response ([[#turn-number-is-step-index]]), and
`parent_tool_call_id` adds optional display nesting under the tool that
started a sub-agent. On legacy rows, a nested call has only
`parent_tool_call_id`. Parallel calls in one step are stored and replayed in
the assistant's call order, not completion order. `tool_id`, `tab_index` and
`parent_tool_call_id` are final only after `save_chat_turn`.

**Replay.** Neither path re-runs anything. A runtime response replays through
`chat/presentation.py:replay_response`, which uses the same message and tool
renderers as the live stream and reads typed results, not the tool catalog.
It excludes background child output from the `spawn_agent` card. The parent
receives that output as a message before its next model call.
`ChatInput` is the inbox: pending human and agent messages, and unread child
results. Each message is in exactly
one place at any moment. The delivery and the reader decide its path:

| Message | Path |
| --- | --- |
| `send` that a running step reads | `chat_input` row → deleted when the step accepts it → `chat_response_item.inputs` of the reading step, in the same transaction |
| `queue`, `interrupt`, or a `send` that no step can read | `chat_input` row → deleted when a turn accepts it → a USER `chat_message` that starts the new turn, in the same transaction |

Agent messages follow the same two paths. Child results go into the
recipient's `inputs`. An automatic follow-up starts under a hidden
`AGENT_RESULTS` `chat_message` instead of a USER one.

A step deletes the rows it accepts (`db/chat_inputs.py:consume_inputs__no_commit`)
in the transaction that writes `ChatResponseItem.inputs`, the typed list of
accepted messages. Starting a new run moves its pending instruction into the
question tree in the same transaction.
The runtime records an input only after its acceptance transaction commits.
Live and saved rendering emit accepted human inputs as `user_message` packets
before the model step that consumed them. This preserves their display order.
Human input needs no invoking tool call or source response. Main Chat accepts
text without attachments or request headers. A queued or interrupting message
keeps its Deep Research choice (`chat_input.deep_research`) and the model the
picker showed (`chat_input.llm_override`). The human queue belongs to the
session: only a `send` row targets a response, and a `send` that its run never
reads waits like queued input. Withdrawing pending text uses the
same recipient lock as acceptance; accepted text cannot be withdrawn. Promotion
to `interrupt` changes that same row and requests the turn's Stop.
Acceptance rechecks delivery so input already read by a runner cannot bypass a
concurrent promotion. `db/chat_inputs.py:next_queued_turn` reads the next root
turn and `accept_queued_turn__no_commit` consumes it with the user-message
insert under the session lock. A branch whose tip is a question, not a
response, is not ready for a queued turn. Interrupts take priority and may start after
any terminal response; ordinary queued turns wait while Stop paused the queue
(`chat_session.queue_paused_at`) or the latest response failed
(`db/chat_inputs.py:can_start_input`, shared with child inboxes). Unread
finished results wake a recipient only while its queue is not paused and its
latest run did not fail; an agent's queue pauses when its latest run was
stopped (`db/chat_inputs.py:wakes_for_results`).

The root's `wait_agents` call ends its turn when it is the step's only call and a named
agent, or any agent, still runs.
Its saved `tool_call` result (`AgentWaitDetails`) is the only record of the wait. It holds
the root's unread results from those agents' runs that belong to its root response or an
earlier one. `wakes_for_results` applies one rule to an idle root: a finished result that no
wait holds wakes it at once; held results wake it together once none of their wait's runs is
active and no message that dispatch would start (`can_start_input`) is queued for its agents.
A result held by several waits wakes the root only when all of them are released. Interrupted runs leave no result, so they count
as finished; a wait whose runs left only stopped results wakes nobody. The follow-up reads the
results, so a wait wakes the root once. An interim follow-up leaves the results that an open
wait holds unread (`db/chat_inputs.py:read_run_inputs`); a user's turn reads all of them.
`agent_waits` reads waits only when results would wake the root, from the oldest unread
result's root response on. The existing dispatch callers evaluate the rule: a child's
release, the turn's own release, the agent host, and `/status`.
A pod crash while awaited runs are active, with no browser open, delays the wake until
`/status` or a run store repairs the orphaned runs.
A user turn reads the root's unread results at its first step, so it ends a wait whose wake was lost.

Inbox writers lock the recipient session before the response. The session lock
uses `NO KEY UPDATE` so response and tool foreign-key checks can proceed.
Pending text is limited to `db/chat_inputs.py:MAX_PENDING_MESSAGE_BYTES` per
message, for human and agent messages. The source check uses `IS TRUE`, so a
row with a NULL required field fails it.
Accepted result inputs reference their source response; reconstructed history
retains that provenance across compaction. Reserving a child response that its
caller marks as result-delivering (a `spawn_agent` child, or any run started from
the inbox) adds an `agent_result` row for the child's spawner
(`db/chat_response.py:reserve_child_response__no_commit`). A child reservation
is a running response; `chat/run_store.py:ChatRunStore` commits it with its owner
lease, so a second run of that agent cannot be reserved. The row is readable
once the response finishes. It names the run's root response: the invocation's
root, or the newer root of the recipient's previous run when a message from an
earlier turn continues it. Agents can message each other, so the chain of
invoking runs can be longer than the spawn depth;
`db/chat.py:response_invocation_chain` reads it in one query, and
`db/chat.py:response_on_branch` is the one branch rule for reserving and saving.
`db/chat_inputs.py:reserve_inbox_run__no_commit` picks that root, and
`db/chat_inputs.py:agent_result_states` returns it only on branches that contain
that root, so receipt on one branch does not consume a result on another. A
completed parent gets a follow-up run under an `AGENT_RESULTS` question when
unread results arrive, including nested parents
(`db/chat_inputs.py:reserve_inbox_run__no_commit`); the first model step
consumes them. Each run of a child delivers its own result to the child's spawner,
whichever agent's message started it, except a run that `interrupt_agent` stops:
its row is deleted first (`db/chat_inputs.py:withdraw_agent_result__no_commit`),
so it wakes no agent. A run that Stop subagents stops keeps its row for the root
but records `STOPPED_BY_USER`, so it wakes no agent either; the root reads it as a
notice at its next step. Agent messages to the root have no target run; a root run
reads them at its next step, and dispatch never starts a root run for them. The runtime suspends a subagent before
completion while its unread results include running children
(`RunOwnership.delegated_runs`).
Cancelled and failed parents do not restart automatically.
User-submitted queued messages take priority.
Result inputs remain model context and do not render as user messages.
Search documents and `tool_id` come from the `ToolCall` rows and their search-doc
links (`db/chat_response.py:read_response_replay_data`), not from the typed
result: the saved `SearchDocsResponse` holds no documents. Only
`save_chat_turn` writes those links, for the calls that
`chat/presentation.py:project_response` collects, through
`db/chat.py:add_search_docs_to_tool_call`. It stores each document's index in
the tool's result as `ToolCall__SearchDoc.position`, and `ToolCall.search_docs`
orders by position, then id. Do not order by id alone: when a later call
returns a document that an earlier call saved, the save reuses the older
`SearchDoc` row and id. Links saved before the column existed have no position
and keep id order. A
legacy response replays through the builders in
`server/query_and_chat/session_loading.py:translate_assistant_message_to_packets`:
tool steps grouped by `turn_number`, the answer as one delta, citations in
order of first use, and a stop packet. It picks a builder per tool by
`in_code_tool_id`, with a custom-tool fallback. A runtime answer with tool
calls adds a child-response query and a tool-replay query to session load.
`get_chat_session` prefetches the tool calls' search docs and loads their tools
in one query (`server/query_and_chat/session_loading.py:load_session_tools`);
do not add per-message or per-call queries. A reload shows a `RUNNING` row as it is, with the steps saved so far.
A failed answer's error comes from `ChatMessage.response_failure` through
`chat/errors.py:chat_error` (code, retryable flag, model and provider), and
falls back to `ChatMessage.error` on legacy rows
(`db/chat.py:translate_db_message_to_chat_message_detail`); a change to the
failure shape must keep old rows readable.

**History for the next turn.** `chat/chat_utils.py:capture_chat_history` reconstructs
runtime results from their recorded bodies. For legacy generated-image results,
`_build_tool_call_response_history_message` prefers usable stored file IDs and revised
prompts. If none are usable, it falls back to saved response text, then a placeholder.
Other legacy results use saved response text, then the placeholder.

A code mode result is replayed as saved ([[#code-mode-replay-content]]).

The runtime builds its working context from that history. `messages_for_model`
removes incomplete tool exchanges and unsigned thinking. Context-budget compaction
can summarize older results; truncation can remove them. These operations change
model input, not the source records.

Content-persisting sessions retain PostgreSQL evidence for replay and citations.
`USAGE_ONLY` sessions store no conversation content there. Their temporary history
can lose evidence before model compaction under the retention limits below.

**Incognito.** Chat does not start subagents, deep research, or coding agents in
incognito. Temporary history retains root messages and response receipts for
idempotent saves. It does not index child conversations. A session pins `incognito_record_mode` when it is created
(`chat/incognito.py:resolve_incognito_record_mode`, read past the settings
cache). `FULL_HISTORY` stores content like a normal chat and only hides it
from the owner. `USAGE_ONLY` (the default) writes rows with blank text and
real token counts, sets only `response_status` on the answer, writes no
response items, tool calls, sources, citations or checkpoints, and keeps the
conversation in Redis through `chat/history_store.py:RedisChatHistoryStore`.
Tool results there keep their details as the saved type, documents included
(`chat/models.py:serialize_incognito_message`), so citations and the code
mode store work in later turns.
The database branch selects retained user messages and response output IDs from
the temporary list. Saving a new input removes future turns and unselected model
answers before appending its text-file messages and question. A small response
index keeps run IDs, output IDs and each response’s checkpoint.
Continuation and regeneration use the selected parent’s
checkpoint, never the last sibling saved. A failed save or eviction can leave a
selected database response without temporary content. The next turn’s temporary
prompt history omits that response and never substitutes a sibling. The chat-session
API still returns its blank database row and replay stop. Image metadata keeps file references, not image bytes. Regeneration reuses the saved
input group; it fails when the question has expired or was trimmed.
The list keeps at most 200 messages and 1 MB. Byte and message-count overflows
remove complete oldest turns, including attachments, questions, and response/tool messages.
An input or response that cannot fit with its complete current turn fails its save
(`chat/incognito_context.py:_retained_state`). The answer save is two writes
that are not atomic: the Postgres usage row commits first, then Redis. A
teardown or lost admission between them leaves a final row, a
`RESPONSE_SAVE_ERROR` on the stream, and no answer in the next turn's history.
Incognito needs the Redis cache backend and is off on the Postgres one
(`incognito_context_available`). Leaving the chat calls
`end-incognito-session`, which marks uploads for deletion, drops the Redis
context and deletes generated files. Deleting an incognito session runs the
same teardown. A TTL and a server sweep clean up when the call never arrives.
The stored-value format requires response ownership. Older unindexed values
are ignored on read: new turns continue without that context, and old questions
cannot be regenerated. Redis retains the value until a write replaces it, teardown
deletes it, or its TTL expires. The key namespace stays stable so teardown fences
survive upgrades.
`chat/incognito_context.py:teardown_incognito_session` adds the session to a
tenant pending set and writes the tombstone at once. Under the session lock it
deletes the context, then deletes the buffered stream keys. When the lock is
busy, it queues a retry, and the periodic incognito cleanup task drains the
pending set (`retry_incognito_teardowns`).

**Deletion and retention.** Soft delete sets `deleted`. Hard delete
(`HARD_DELETE_CHATS` or the `hard_delete` parameter) runs
`db/chat.py:delete_messages_and_files_from_chat_session` over the session and
its child sessions: message files, checkpoint blobs, then messages (tool calls,
response items and checkpoints cascade), then `SearchDoc` rows no message links
to. The EE task
`ee/onyx/background/celery/tasks/ttl_management/tasks.py:perform_ttl_management_task`
hard-deletes in batches the sessions whose last activity, child sessions
included, is older than the window (`db/chat.py:get_chat_sessions_older_than`).
A change to `maximum_chat_retention_days` needs the Enterprise tier, and the
Community downgrade clears it ([[billing]]).

---

## Contracts and traps

1. `reasoning-attaches-to-next-row` **On legacy rows, reasoning attaches to
   the row that comes after it**: the next `ToolCall` (a copy on each parallel
   call) or the answer. Legacy replay moves it one turn slot earlier
   (`server/query_and_chat/session_loading.py:translate_assistant_message_to_packets`).
   Runtime rows keep thinking inside each `chat_response_item` in its recorded
   order; do not rebuild it from the `reasoning_tokens` columns.
2. `save-chat-turn-one-commit` **`db/chat_response.py:save_chat_turn`
   commits once.** Text, `SearchDoc` rows, links, final runtime records and
   citations land in one transaction. `save_chat_response_to_db` deletes the
   checkpoint row in the same transaction; a direct caller of `save_chat_turn`
   does not. Do not commit in the middle. The earlier saves
   (`save_response_record__no_commit`) commit on their own, and happen only at
   run start (no steps), when a step accepts pending human input
   (`chat/run_store.py:ChatRunStore.accept_inputs` saves the steps so far plus
   the accepting step, in the transaction that consumes the inbox rows), before
   each sub-agent starts (the root's steps so far), and when a sub-agent run
   ends. A crashed root run keeps its steps only up to the latest of these
   saves, under a `RUNNING` status, so accepted input survives a crash and is
   not delivered again.
   `chat/run_store.py:ChatRunStore._load_status` marks a `RUNNING` response
   with no live owner as `ERROR` (`cancel_run`: `CANCELLED`) only when a later
   run reads it as a sub-agent. A root response left `RUNNING` is repaired
   only in a conversation with an inbox row: dispatch saves it as `ERROR`
   (`chat/run_store.py:interrupt_ownerless_responses`), which pauses the queue.
   Otherwise a reload replays it as is.
3. `reserved-row-resolves` **A reserved assistant row must resolve.** Once
   `ChatTurnExecution.run` starts, `chat/persistence.py:ChatResponsePersistence`
   saves every outcome: an answer, a stop, a run failure, and a startup
   failure. Ordinary startup failures use `save_failure` with a NULL status,
   empty text and `error` set. Preparation timeouts instead save a minimal
   cancelled runtime record with a `DEADLINE` failure. The expected unresolved rows are these. A content-persisting answer
   whose final save fails or is rejected after ownership loss stays `RUNNING`
   with the placeholder text. A `USAGE_ONLY` answer whose Postgres write fails
   keeps the placeholder with a NULL status. A turn that `chat/execution.py:start_chat_turn`
   rejects before `run`, or a worker failure
   (`ChatResponsePersistence.report_worker_failure`), writes nothing. A save
   that takes longer than `PERSISTENCE_WAIT_SECONDS` reports `UNCONFIRMED`; it
   can still succeed later. The root's `OverallStop` packet comes before the
   final save, so a model error or `RESPONSE_SAVE_ERROR` can follow it. Trust
   the saved row only after the stream closes.
4. `incognito-decision-per-field` **Every new content field needs an incognito
   decision.** `db/chat_response.py:save_chat_turn` blanks text and reasoning,
   clears citations and skips sources and tool calls when `persist_content` is
   false, and `save_response_content` keeps only `response_status`. Error text
   becomes a generic message. Token counts and `request_params` are kept on
   purpose for usage metering. `db/chat.py:update_chat_session` drops a title
   with no error. Every runtime writer (`_ResponseWriter`, child reservation,
   `db/chat_checkpoint.py:publish_checkpoint__no_commit`) refuses a
   content-free session. A new column stays empty for `USAGE_ONLY` only if you
   write that rule. Decide from the pinned `ChatSession.incognito_record_mode`
   (`db/enums.py:record_mode_persists_content`), never the live setting.
   `save_chat_response_to_db` raises when the history store the turn chose
   does not match the pinned mode.
5. `history-surface-filters` **Every history surface must apply the same
   filters.** Owner history skips incognito; workspace surfaces skip only
   content-free sessions (`db/chat.py:content_persisting_sessions_filter`).
   Every read also skips child sessions (`spawned_by_message_id IS NULL`) and
   summary rows (`db/chat.py:visible_chat_messages_filter`). A new list,
   search or export query that omits one of these leaks rows. Search applies
   the incognito filter to both halves of its union
   (`db/chat_search.py:search_chat_sessions`). Usage exports keep child
   sessions on purpose, because sub-agents spend tokens.
6. `summary-rows-not-messages` **Summary rows sit in the tree but are not
   messages.** `db/chat_response.py:_ResponseWriter.store` adds a `SUMMARY` row
   as a child of the response whose run compacted, next to the following
   question. No pointer selects it. Code that counts children or siblings must
   filter it. `db/chat.py:find_summary_for_branch` picks the summary on the
   nearest ancestor of the branch, and the turn passes it to the run as a
   compaction checkpoint. `last_summarized_message_id` holds a runtime message
   id (`chat:<question id>` or a step id), not a row id, so a change to how
   `capture_chat_history` names messages breaks saved boundaries.
7. `send-parent-on-active-branch` **A send must name a parent on the active
   branch.** `db/chat.py:load_message_branch` searches only the
   `latest_child_message_id` chain. A parent of None or the root id starts a
   new top-level branch, and `AUTO_PLACE_AFTER_LATEST_MESSAGE` appends to the
   active tip. A client must persist a branch switch before it sends on that
   branch. Reservation moves the active pointer to the new answer before the
   run starts.
8. `replay-matches-live-stream` **Replay must match the live stream.** Runtime
   replay and the live stream share `chat/renderer.py:MessageRenderer` and
   `chat/renderer.py:ToolRenderer`, so change rendering there, not in one
   caller. Runtime replay uses `chat/presentation.py:overall_stop`: a `CANCELLED`
   response with a `DEADLINE` failure gets `timed_out`; other cancellations get
   `user_cancelled`. Lost admission, lost ownership lease and control failures
   still cancel without a classified failure and replay like Stop. History keeps
   deadline cancellations out of error fields, so clients retain the partial answer.
   Preparation timeouts also save a minimal runtime record. Legacy replay
   has its own builders in
   `server/query_and_chat/session_loading.py`; check every `in_code_tool_id`
   branch when a legacy display changes. It finds a stopped answer by the text
   "generation was stopped"; it does not recognize the new time-limit text.
   Content-persisting deadline cancellations save a runtime record and use
   runtime replay; `USAGE_ONLY` sessions still take the legacy path.
   The legacy marker is what
   `db/chat_response.py:save_chat_response_to_db` appends. Legacy dispatch is
   on the class name ([[tools-framework#replay-by-class-name]]), and its
   `run_python` builder parses the saved result JSON
   ([[code-execution#run-python-result-json]]).
9. `tool-id-not-foreign-key` **`ToolCall.tool_id` is not a foreign key.**
   After a tool is deleted, runtime replay still shows its calls from the
   typed result, but legacy replay skips them, and the steps vanish from a
   reloaded chat silently. Code mode has no tool row: `persistence.tool_ids`
   maps `execute_code` and `wait_code` to None, and their calls save with a
   NULL `tool_id`.
10. `shared-read-hides-deleted` **A shared read never returns a deleted
    session.** `db/chat.py:get_chat_session_by_id` adds `deleted IS FALSE`
    whenever `is_shared` is set, because delete does not unshare. Keep that
    filter.
11. `incognito-torn-down-vs-ended` **A missing incognito key does not mean the
    session ended.** A `USAGE_ONLY` session has no Redis context until its
    first message. To decide whether to accept new work, such as an upload,
    call `chat/incognito_context.py:incognito_session_torn_down`, which checks
    for the tombstone (`server/features/projects/api.py` does this).
    `chat/incognito_context.py:incognito_session_ended` also counts a missing
    key as ended. Use it only where a first message is certain, such as the
    stream writer that `chat/execution.py:start_chat_turn` builds. Mixing the
    two accepts work after teardown or refuses a new session.
12. `incognito-callback-no-side-writes` **Callbacks under the incognito lock
    must not write elsewhere.**
    `chat/incognito_context.py:_update_incognito_state` reads fresh state
    under the session lock and passes it to the callback. When the lock is
    busy or lost, it reads again and reruns the callback. It writes only while
    the turn still holds its admission. A callback must be a pure transform of
    the state it gets; do not build replacement state outside it. Saving the
    same response twice is a no-op; different content for the same message
    raises.
13. `stored-tool-result-types` **Saved tool results are a closed set of
    types.** `db/models.py:StoredToolResult` validates `details` against
    `SavedToolResultDetails`, a union keyed by `type`, on save and on every
    load. A tool whose result
    details are not in the union fails its save. Renaming or removing a
    member makes old rows fail to load. Add new detail types to the union and
    keep old ones readable.
14. `turn-number-is-step-index` **On runtime rows, `ToolCall.turn_number` is
    the step index.** Readers join `ToolCall` to `chat_response_item` on
    `(parent_chat_message_id, turn_number) = (chat_message_id, step_index)`
    (`db/chat_response.py:read_response_steps`,
    `db/chat_response.py:read_response_replay_data`). Do not reuse it for
    display grouping. `db/chat_response.py:write_response_items` also refuses
    an update that drops a saved item or tool result, so a run must keep its
    step ids stable across saves.
15. `checkpoints-not-written` **No chat path writes a checkpoint.**
    `chat/run_store.py:ChatRunStore.handoff` writes `chat_response_checkpoint`
    and `agent-checkpoint/<root session id>/` blobs
    (`chat/restoration.py:persist_checkpoint_files`), but nothing calls it.
    Nothing calls `ChatRunStore.resume` either, so no chat path claims a
    checkpoint or runs `chat/restoration.py:restore_chat_agent`. A turn that a
    restart interrupts is never resumed ([[#save-chat-turn-one-commit]]). A
    feature that starts to suspend runs must keep blobs under the root session
    id, because hard delete finds them only by that prefix.
16. `code-mode-replay-content` **A code mode result is replayed as saved, so
    its content must carry what the next turn needs**
    (`tools/tool_implementations/code_mode/prompt.py:format_content`). An
    observation that reports a program that did not complete lists every call
    of the cell, those of earlier observations included, with their states,
    because those calls may have had effects (`calls_note`). A running or
    completed observation lists no calls; when a cell ends without completing,
    its last observation or its closing record lists them. Each observation gives the `file_id` and revised prompt of
    each image that its calls generated (`images_note`), so a later message
    can edit it. When the response ends or the run pauses after a cell's last
    observation, the saved content adds the cell's closing record, formatted
    like an observation. It starts with `closing_heading` ("Cell N stopped when
    the response ended" or "when the run paused", or how it ended) and has the
    output, result and store writes after that observation; it lists the calls
    only when the cell did not complete. A restored
    run closes a cell that its saved observation reports running as
    interrupted: the heading says that calls after the saved output are not
    known, and the record lists the calls that the saved observations hold.

---

## Decisions

- **Edits branch, they do not overwrite.** The empty root lets the first
  message branch too, and older answers stay for a switch back.
- **Inputs live on the user row; everything the run produced lives on the
  assistant row.** System prompts, reminders and custom agent prompts are not
  stored. [[context-assembly]] builds them at load time.
- **`SearchDoc` is a snapshot, not a live reference.** It stores what the user
  saw at retrieval time, without chunk text. Replay shows the same source, and
  a new turn that uses it searches again.
- **The assistant row id is the run id.** A root run's id is
  `str(ChatMessage.id)` of its reserved row, and its agent id is the chat
  session id; a child run's agent id is its child session id. Records,
  ownership keys and checkpoints all use these ids, so no mapping table
  exists. Content-free incognito runs use generated ids and never reach the
  database writers.

---

## Known issues

- **A session with no owner is open.** `get_chat_session_by_id` matches
  `user_id IS NULL` for every caller, and
  `server/query_and_chat/chat_backend.py:get_chat_session` assigns such a
  session to the first signed-in reader. Anonymous users share one fixed user
  id, so they can read each other's sessions by id.
- **"Continue in web UI" copies sessions it can reach by id.**
  `db/chat.py:duplicate_chat_session_for_user_from_slack` accepts a session
  owned by no user, by the anonymous user, or by the caller, and refuses
  incognito sessions. Any signed-in user who knows the id of a public-channel
  Slack session can therefore copy it.
- **No constraint protects the root row.** `get_or_create_root_message` reads,
  then inserts. Two concurrent first loads can insert two roots, and later
  reads raise "Multiple root messages found".
- **Chat duplication can raise `MultipleResultsFound`.** When the original
  agent is not readable,
  `backend/onyx/db/persona.py:get_best_persona_id_for_user` calls
  `one_or_none` on a query that can return many agents. Not reproduced.
- **The retention chain can stall.** Each batch reselects the oldest expired
  sessions. If one never deletes, the chain retries it forever and never
  reaches newer ones. The task docstring accepts this.

---

## Dependencies

- [[agent-runtime]]: the run records, step and tool statuses, and the
  checkpoint data that this component stores.
- [[tools-framework]]: the result detail types that `StoredToolResult` holds,
  and the `in_code_tool_id` that legacy replay dispatches on.
- [[citations]]: the mappings that `save_chat_turn` stores.
- [[streaming-protocol]]: the packet types replay emits.
- [[background-jobs]]: runs the EE retention chain and the incognito cleanup
  task.
- [[multi-tenancy]]: every table and Redis key is tenant-scoped.
- [[auth-and-identity]]: the security settings for incognito availability and
  record mode.

---

## Recipes

- `chat-message-column` **A column on `ChatMessage` or `ToolCall`.** Copy how `reasoning_tokens`
  flows; list the columns in `db/models.py:ChatMessage`. Write the migration
  (backend `AGENTS.md`). Decide what `save_chat_turn` writes and what
  `USAGE_ONLY` writes ([[#incognito-decision-per-field]]). Add it to
  `db/chat.py:translate_db_message_to_chat_message_detail` if the client
  needs it, and to replay if it changes what a reload shows.
- `replay-new-tool` **Replay for a new tool.** Add the tool's result details
  type to `db/models.py:SavedToolResultDetails` ([[#stored-tool-result-types]],
  [[tools-framework#durable-details-registered]]), and
  its packets to `chat/renderer.py:ToolRenderer`, which serves the live stream
  and runtime replay alike; copy the `MemoryTool` branch there. A new tool has
  no legacy rows, so it needs no builder in
  `server/query_and_chat/session_loading.py`. A tool that reuses the search
  packets joins the search branch by name, which reads queries from the
  `queries` argument and from `SearchDocsResponse.queries`.
- `history-surface` **A history surface (list, search, export).** Copy
  `db/chat.py:get_chat_sessions_by_user`; list the readers with
  `git grep -n visible_chat_messages_filter backend`. Apply every filter in
  [[#history-surface-filters]], and decide whether owner-hidden incognito
  sessions belong.
- `investigate-reload-differs` **Investigate "the reload looks different from
  the live answer".** Fetch
  `/api/chat/get-chat-session/{id}` through the frontend and compare its
  `packets` for the answer with the live stream. On a legacy row, missing tool
  steps point at a deleted tool ([[#tool-id-not-foreign-key]]). On any row they
  can point at a missing replay branch ([[#replay-matches-live-stream]]). A tab
  that shows its start but no result has no saved result: query
  `tool_call.operation_status` and `result` for the response (`turn_number` is
  the step index). A NULL `result` with status `running`, `cancelled` or
  `error` comes from a cancel before the call ended, a blocked `SEQUENTIAL`
  call, or a crash ([[#save-chat-turn-one-commit]]). A search or `open_url` tab
  with queries but no documents means `save_chat_turn` wrote no search-doc
  links: the tool name was missing from `persistence.tool_ids`, or the log
  shows "Could not collect tool history". If the `ToolCall` rows and the
  assistant tool calls do not match, `read_response_steps` raises and the whole
  session load fails. Missing citations point at the save path
  ([[citations#persist-emitted-subset]]). A wrong branch points at a branch
  switch that never reached the server ([[#send-parent-on-active-branch]]).
  Query `chat_message` for the session to see the stored tree, and
  `chat_response_item` for the steps of an answer whose `response_status` is
  set. A `running` status with no `chat_response_owner:<id>` key in the cache
  means the run died or its final save failed; a NULL status with `error` set
  means a startup failure ([[#reserved-row-resolves]]). Blank text and
  no tool calls are expected when `chat_session.incognito_record_mode` is
  `usage_only` ([[#incognito-decision-per-field]]); that is not data loss.
- `incognito-test-session` **Set up an incognito session for a test.** Make sure the deployment uses
  the Redis cache backend. Set the admin incognito record mode, then create a
  session with `incognito: true` in the create request. In `USAGE_ONLY` mode,
  the rows hold blank text, and the context sits in the tenant's Redis key
  `incognito_ctx:v2:<session id>` from the first message on. Teardown deletes
  it and sets `incognito_ctx:v2:<session id>:ended`.

---

## Verification

- Integration: `backend/tests/integration/tests/chat/` and
  `backend/tests/integration/tests/chat_retention/`.
- Unit: `backend/tests/unit/onyx/chat/` (response records, projection,
  replay, history stores and incognito helpers) and `backend/tests/unit/onyx/db/`.
- Run store ownership, incognito storage and Slack copy authorization:
  `backend/tests/external_dependency_unit/chat/` and
  `backend/tests/external_dependency_unit/db/`.
- By hand: send, edit, switch branches, and reload. The same branch, tool
  steps and citations must show, and the session has one root row. Run a deep
  research turn and reload: the sub-agent steps show inside the research tool.
