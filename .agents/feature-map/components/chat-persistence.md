# Chat Persistence

> How a conversation is stored and read back: the session, the message tree and
> its branches, model steps, tool calls, surfaced documents, feedback, sharing,
> incognito, history search and retention. Each answer row is reserved before the
> run, filled while it runs, and finalized in one transaction; every reload, share
> link and later turn reads that record.

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
  create_new_chat_message (user row)       commits at once; survives a failed answer
  reserve_chat_response_ids                db/chat.py: assistant row(s), placeholder
                                           text, response_status NULL, committed
ChatRunStore (content-persisting only)     chat/run_store.py
  register / save                          db/chat_response.py:save_response_record__no_commit
                                           response items + ToolCall rows, own commit
  reserve_run_id (sub-agent)               db/chat_response.py:reserve_child_response__no_commit
                                           child session, question, response rows
ChatResponsePersistence.save (root, end)   chat/persistence.py
  ChatHistoryStore.save_response           chat/history_store.py: Postgres or Redis
    save_chat_response_to_db               db/chat_response.py: checks the record mode
      save_chat_turn                       ONE commit: text, SearchDoc rows, links,
                                           citations, final records; drops checkpoint
GET /chat/get-chat-session/{id}
  get_chat_messages_by_session             loads all branches, two ToolCall levels
  translate_assistant_message_to_packets   runtime rows: read_chat_execution ->
                                           chat/presentation.py:replay_response;
                                           legacy rows: per-tool builders
```

**Two response formats.** `ChatMessage.response_status` tells them apart. A
row with a status is a runtime response. Each model step is a
`chat_response_item` that holds the whole assistant message (text, thinking,
tool calls) in `step_index` order. Each tool call is a `ToolCall` row whose
typed result is in `ToolCall.result` (`db/models.py:StoredToolResult`). A row
with a NULL status is a legacy response, or a reserved row whose save never
finished. Its tool output is in the `tool_call_response` column (mapped as
`legacy_response`) and its reasoning in the `reasoning_tokens` columns. Every
reader branches on the status: history
(`chat/chat_utils.py:capture_chat_history`), replay, and reasoning display
(`db/chat.py:get_chat_message_reasoning`). `backend/onyx/db/README.md`
describes only the legacy format.

**The tree.** Each session has one root row: `SYSTEM` type, no parent, empty
text (`db/chat.py:get_or_create_root_message`). Messages alternate user and
assistant below it. An edit adds a sibling user row under the same parent. A
regenerate is a send whose parent is the user row, so
`chat/process_message.py:prepare_chat_turn` reuses that row and adds a sibling
answer. Each row's `latest_child_message_id` marks the active child. Walking
those pointers from the root gives the active conversation
(`db/chat.py:create_chat_history_chain`). A branch switch moves one pointer
(`db/chat.py:set_as_latest_chat_message`). A multi-model pick sets
`preferred_response_id` and moves the same pointer (`db/chat.py:set_preferred_response`).

**Child sessions.** When a research or coding sub-agent runs in a
content-persisting chat, `reserve_child_response__no_commit` creates a
`ChatSession` with `spawned_by_message_id` set to the parent response. It
copies the root's user, agent, Slack flag and record mode. A child session has
no `SYSTEM` root: its first question has no parent, and
`invoking_tool_call_id` links it to the parent's `ToolCall`. Hard delete and
retention treat the root and its descendants as one conversation
(`db/chat.py:session_descendants`). A failed child start deletes the unused
question, response and empty child session
(`db/chat_response.py:abort_response_start__no_commit`).

**Tool calls.** On a runtime response, `parent_chat_message_id` always names
the owning response ([[#turn-number-is-step-index]]), and
`parent_tool_call_id` adds optional display nesting under the tool that
started a sub-agent. On legacy rows, a nested call has only
`parent_tool_call_id`.

**Replay.** Neither path re-runs anything. A runtime response replays through
`chat/presentation.py:replay_response`, which uses the same message and tool
renderers as the live stream and reads typed results, not the tool catalog. A
legacy response replays through the builders in
`server/query_and_chat/session_loading.py:translate_assistant_message_to_packets`:
tool steps grouped by `turn_number`, the answer as one delta, citations in
order of first use, and a stop packet. It picks a builder per tool by
`in_code_tool_id`, with a custom-tool fallback.

**History for the next turn.** A later turn does not see earlier tool output.
`chat/chat_utils.py:omit_prior_tool_result_content` marks saved runtime tool
results, and `chat/prompt_utils.py:prepare_prompt` replaces their content with
`TOOL_CALL_RESPONSE_CROSS_MESSAGE`. Legacy rows get the same placeholder from
`chat/chat_utils.py:_build_tool_call_response_history_message`. Image
generation is the exception in both: its output stays. The incognito store
applies the same rule. Within one turn the run keeps the full tool output. The
stored content stays intact for replay and citations.

**Incognito.** A session pins `incognito_record_mode` when it is created
(`chat/incognito.py:resolve_incognito_record_mode`, read past the settings
cache). `FULL_HISTORY` stores content like a normal chat and only hides it
from the owner. `USAGE_ONLY` (the default) writes rows with blank text and
real token counts, sets only `response_status` on the answer, writes no
response items, tool calls, sources, citations or checkpoints, and keeps the
conversation in Redis through `chat/history_store.py:RedisChatHistoryStore`.
Incognito needs the Redis cache backend and is off on the Postgres one
(`incognito_context_available`). Leaving the chat calls
`end-incognito-session`, which marks uploads for deletion, drops the Redis
context and deletes generated files. Deleting an incognito session runs the
same teardown. A TTL and a server sweep clean up when the call never arrives.
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
   citations land in one transaction, and the checkpoint row is deleted in it.
   Do not commit in the middle. The progressive saves before it
   (`save_response_record__no_commit`) commit on their own, so a crashed run
   leaves partial items under a `RUNNING` status, not a half-finalized answer.
   `chat/run_store.py:ChatRunStore._load_status` marks a `RUNNING` response
   with no live owner as `ERROR` when it next reads it.
3. `reserved-row-resolves` **A reserved assistant row must resolve.**
   `chat/persistence.py:ChatResponsePersistence` saves every outcome: an
   answer, a stop, a run failure, and a startup failure (`save_failure`). When
   the save itself fails, or takes longer than `PERSISTENCE_WAIT_SECONDS`, the
   stream gets `RESPONSE_SAVE_ERROR` and the row can keep the "terminated prior
   to completion" placeholder with a NULL status. Any other row left in that
   state is a bug.
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
   `latest_child_message_id` chain. A client must persist a branch switch
   before it sends on that branch.
8. `replay-matches-live-stream` **Replay must match the live stream.** Runtime
   replay and the live stream share `chat/renderer.py:MessageRenderer` and
   `chat/renderer.py:ToolRenderer`, so change rendering there, not in one
   caller. Runtime replay sets `stop_reason=user_cancelled` from a `CANCELLED`
   status. Legacy replay has its own builders in
   `server/query_and_chat/session_loading.py`; check every `in_code_tool_id`
   branch when a legacy display changes. It finds a stopped answer by the text
   "generation was stopped", which
   `db/chat_response.py:save_chat_response_to_db` appends. Legacy dispatch is
   on the class name ([[tools-framework#replay-by-class-name]]), and its
   `run_python` builder parses the saved result JSON
   ([[code-execution#run-python-result-json]]).
9. `tool-id-not-foreign-key` **`ToolCall.tool_id` is not a foreign key.**
   After a tool is deleted, runtime replay still shows its calls from the
   typed result, but legacy replay skips them, and the steps vanish from a
   reloaded chat silently.
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
    `chat/incognito_context.py:_update_incognito_state` can rerun the callback
    on lock retry, and it writes only while the turn still holds its
    admission. A save that loses the compare-and-set must not retry with the
    history it loaded.
13. `stored-tool-result-types` **Saved tool results are a closed set of
    types.** `db/models.py:StoredToolResult` validates `details` against a
    union keyed by `type`, on save and on every load. A tool whose result
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
    (`chat/restoration.py:persist_checkpoint_files`), but nothing calls it. A
    feature that starts to suspend runs must keep blobs under the root session
    id, because hard delete finds them only by that prefix.

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
  type to `db/models.py:StoredToolResult` ([[#stored-tool-result-types]]) and
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
  `packets` for the answer with the live stream. Missing tool steps point at
  a deleted tool ([[#tool-id-not-foreign-key]]) or a missing replay branch
  ([[#replay-matches-live-stream]]). Missing citations point at the save path
  ([[citations#persist-emitted-subset]]). A wrong branch points at a branch
  switch that never reached the server ([[#send-parent-on-active-branch]]).
  Query `chat_message` for the session to see the stored tree, and
  `chat_response_item` for the steps of an answer whose `response_status` is
  set. A NULL status on a new answer means the final save failed
  ([[#reserved-row-resolves]]). Blank text and
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
