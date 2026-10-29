# Chat Persistence

> How a conversation is stored and read back: the session, the message tree and
> its branches, tool calls, surfaced documents, feedback, sharing, incognito,
> history search and retention. The live loop writes a turn once, at the end, and
> every reload, share link and later turn reads that one record.

**Verified against:** `a4e97fcea1` (2026-10-29)
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
`SearchDoc`, the two feedback tables), the code that writes and reads them,
replay of a saved answer as packets, incognito storage, retention, and the
session lifecycle endpoints: list, read, rename, share, delete, branch switch,
multi-model pick, feedback and incognito teardown.

It also holds the storage for the shared agent runtime: the
`chat_response_item` and `chat_response_checkpoint` tables and child sessions.
No production chat path calls that storage code or sets
`spawned_by_message_id`, but every chat read filters child sessions
([[#history-surface-filters]]). [[agent-runtime]] records what is live.

Neighbours own the rest. [[core-chat-loop]] owns the send endpoint, when rows
are reserved, the error path, stop and resume. [[context-assembly]] turns saved
history into a prompt and owns compression. [[citations]] owns the numbers that
`ChatMessage.citations` stores. [[auth-and-identity]] stores the security
settings that hold incognito availability and the record mode; this component
applies them.

---

## Architecture

```
build_chat_turn                         chat/process_message.py
  create_new_chat_message (user row)    commits at once; survives a failed answer
  reserve_message_id / _multi_model_    assistant row(s) with placeholder text,
                                        committed before the first token
... loop streams ...
llm_loop_completion_handle
  save_chat_turn                        chat/save_chat.py, ONE commit:
    save_chat_display__no_commit        db/chat_display.py: text, reasoning,
                                        SearchDoc rows, message links, citations
    _create_and_link_tool_calls         ToolCall rows, flush, wire parents,
                                        link SearchDocs per tool call
GET /chat/get-chat-session/{id}
  get_chat_messages_by_session          loads all branches, two ToolCall levels
  translate_assistant_message_to_packets  rebuilds packets per answer
```

`backend/onyx/db/README.md` gives the authors' reasons for the tree and the
tool call nesting.

**The tree.** Each session has one root row: `SYSTEM` type, no parent, empty
text (`db/chat.py:get_or_create_root_message`). Messages alternate user and
assistant below it. An edit adds a sibling user row under the same parent. A
regenerate is a send whose parent is the user row, so
`chat/process_message.py:build_chat_turn` reuses that row and adds a sibling
answer. Each row's `latest_child_message_id` marks the active child. Walking
those pointers from the root gives the active conversation
(`db/chat.py:create_chat_history_chain`). A branch switch moves one pointer
(`db/chat.py:set_as_latest_chat_message`). A multi-model pick sets
`preferred_response_id` and moves the same pointer (`db/chat.py:set_preferred_response`).

**Tool calls.** A `ToolCall` hangs from the assistant message when the model
called it directly, or from another `ToolCall` when an agent tool called it.
The save path sets exactly one of the two parents; no database constraint
enforces it. Calls with the same parent and
`turn_number` ran in parallel; `tab_index` orders them. A nested call whose
parent was cancelled by a stop is not saved
(`chat/save_chat.py:_create_and_link_tool_calls`).

**Replay.**
`server/query_and_chat/session_loading.py:translate_assistant_message_to_packets`
re-runs nothing. It emits tool steps grouped by `turn_number`, the answer as
one delta, citations in order of first use, and a stop packet. It picks a
builder per tool by `in_code_tool_id`, with a custom-tool fallback.

**History for the next turn.** A later turn does not see earlier tool output.
`chat/chat_utils.py:_build_tool_call_response_history_message` replaces each
saved tool response with `TOOL_CALL_RESPONSE_CROSS_MESSAGE`. Image generation
is the exception: its file ids and revised prompts stay. Within one turn the
loop keeps the full tool output. The arguments always stay, so a fact a later
turn needs must be in the arguments. The saved arguments are the model's
own. Search query expansion runs inside
`tools/tool_implementations/search/search_tool.py:SearchTool.run` and shows
only in the live `SearchToolQueriesDelta` packet, so history does not hold the
queries that ran or that produced the citation numbers.

**Incognito.** A session pins `incognito_record_mode` when it is created
(`chat/incognito.py:resolve_incognito_record_mode`, read past the settings
cache). `FULL_HISTORY` stores content like a normal chat and only hides it
from the owner. `USAGE_ONLY` (the default) writes rows with blank text and
real token counts, writes no tool calls, sources or citations, and keeps the
conversation in Redis (`chat/incognito_context.py`).
Incognito needs the Redis cache backend and is off on the Postgres one
(`incognito_context_available`). Leaving the chat calls
`end-incognito-session`, which marks uploads for deletion, drops the Redis
context and deletes generated files. Deleting an incognito session runs the
same teardown. A TTL and a server sweep clean up when the call never arrives.
`chat/incognito_context.py:teardown_incognito_session` first adds the session
to a tenant pending set. Under the session lock it writes a tombstone and
deletes the agent state, then deletes the buffered stream keys. When the lock
is busy, it queues a retry, and the periodic incognito cleanup task drains the
pending set (`retry_incognito_teardowns`).

**Deletion and retention.** Soft delete sets `deleted`. Hard delete
(`HARD_DELETE_CHATS` or the `hard_delete` parameter) runs
`db/chat.py:delete_messages_and_files_from_chat_session`: files, then messages
(tool calls cascade), then `SearchDoc` rows no message links to. The EE task
`ee/onyx/background/celery/tasks/ttl_management/tasks.py:perform_ttl_management_task`
hard-deletes in batches the sessions whose last message is older than the
window (`db/chat.py:get_chat_sessions_older_than`). A change to
`maximum_chat_retention_days` needs the Enterprise tier, and the Community
downgrade clears it ([[billing]]).

---

## Contracts and traps

1. `reasoning-attaches-to-next-row` **Reasoning attaches to the row that comes
   after it.** Reasoning before a tool call is stored on that `ToolCall`.
   Reasoning before the answer is stored on the assistant message. With
   parallel calls, each call gets a copy. Replay takes the first call in a
   turn that has reasoning and places it one turn slot earlier when that slot
   is free
   (`server/query_and_chat/session_loading.py:translate_assistant_message_to_packets`). Change both together.
2. `save-chat-turn-one-commit` **`chat/save_chat.py:save_chat_turn`
   commits once.** Text,
   `SearchDoc` rows, links, tool calls and citations land in one transaction.
   Do not commit in the middle. A crash leaves the reserved placeholder, not a
   half-written answer.
3. `reserved-row-resolves` **A reserved assistant row must resolve.** Either
   `save_chat_turn` overwrites it, or
   `chat/process_message.py:_save_errored_message` writes the error. A row that
   keeps the "terminated prior to completion" text with no error is a bug.
4. `incognito-decision-per-field` **Every new content field needs an incognito
   decision.** `db/chat_display.py:save_chat_display__no_commit` blanks text
   and reasoning, clears citations and skips sources when `persist_content` is
   false. `save_chat_turn` then skips tool calls. Token counts and
   `request_params` are kept on purpose for usage metering.
   `db/chat.py:update_chat_session` drops a title with no error. A new column
   stays empty for `USAGE_ONLY` only if you write that rule. Decide from the
   pinned `ChatSession.incognito_record_mode`
   (`db/enums.py:record_mode_persists_content`), never the live setting.
5. `history-surface-filters` **Every history surface must apply the same
   filters.** Owner history skips incognito; workspace surfaces skip only
   content-free sessions (`db/chat.py:content_persisting_sessions_filter`).
   Every read also skips child sessions (`spawned_by_message_id IS NULL`) and
   compression summaries (`db/chat.py:visible_chat_messages_filter`). A new
   list, search or export query that omits one of these leaks rows. Search
   applies the incognito filter to both halves of its union
   (`db/chat_search.py:search_chat_sessions`).
6. `summary-rows-not-messages` **Summary rows sit in the tree but are not
   messages.** Compression
   (`chat/compression.py:get_summary_parent_message_id`) adds a `SUMMARY` row
   as a child of the last user message, so it is a sibling of that turn's
   answers. No pointer selects it. Code that counts children or siblings must
   filter it. `visible_chat_messages_filter` hides it from history views, and
   `build_chat_turn` puts it at the start of the next turn's history as an
   ASSISTANT message.
7. `send-parent-on-active-branch` **A send must name a parent on the active
   branch.** `chat/process_message.py:build_chat_turn` searches only the
   `latest_child_message_id` chain. A client must persist a branch switch before it sends on that
   branch.
8. `replay-matches-live-stream` **Replay must match the live stream.** When a
   tool's live packets change, change its builder in
   `server/query_and_chat/session_loading.py` in the same PR, and check every
   `in_code_tool_id` branch. Replay finds a stopped answer by the text
   "generation was stopped", which
   `chat/process_message.py:llm_loop_completion_handle` appends.
   Change both together, or replay loses `stop_reason=user_cancelled`.
   Dispatch is on the class name ([[tools-framework#replay-by-class-name]]),
   and the `run_python` builder parses the saved result JSON
   ([[code-execution#run-python-result-json]]).
9. `tool-id-not-foreign-key` **`ToolCall.tool_id` is not a foreign key.**
   After a tool is deleted, replay skips its calls, and the steps vanish from
   a reloaded chat silently.
10. `shared-read-hides-deleted` **A shared read never returns a deleted
    session.** `db/chat.py:get_chat_session_by_id` adds `deleted IS FALSE`
    whenever `is_shared` is set, because delete does not unshare. Keep that
    filter.
11. `incognito-torn-down-vs-ended` **A missing incognito key does not mean the
    session ended.** A `USAGE_ONLY` session has no Redis context until its
    first message. To decide whether to accept new work, such as an upload,
    call `chat/incognito_context.py:incognito_session_torn_down`, which checks
    for the tombstone (`server/features/projects/api.py` does this).
    `chat/incognito_context.py:incognito_session_ended` also counts a missing key as ended. Use it only
    where a first message is certain, such as the stream writer in
    `chat/process_message.py`. Mixing the two accepts work after teardown or
    refuses a new session.
12. `incognito-callback-no-side-writes` **Callbacks under the incognito lock
    must not write elsewhere.**
    `chat/incognito_context.py:_update_incognito_state` can rerun the callback
    on lock retry. A save that loses the compare-and-set must not retry with
    the history it loaded.

---

## Decisions

- **Edits branch, they do not overwrite.** The empty root lets the first
  message branch too, and older answers stay for a switch back.
- **Inputs live on the user row; everything the loop produced lives on the
  assistant row.** System prompts, reminders and custom agent prompts are not
  stored. [[context-assembly]] builds them at load time.
- **`SearchDoc` is a snapshot, not a live reference.** It stores what the user
  saw at retrieval time, without chunk text. Replay shows the same source, and
  a new turn that uses it searches again.

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

- [[tools-framework]]: the `in_code_tool_id` that replay dispatches on.
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
- `replay-new-tool` **Replay for a new tool.** Copy the `MemoryTool` branch in
  `translate_assistant_message_to_packets`; list the branches with
  `git grep -n in_code_tool_id backend/onyx/server/query_and_chat/session_loading.py`.
  Emit the same packets the live tool emits ([[#replay-matches-live-stream]]).
  A tool that reuses the search packets joins the search branch instead. That
  branch reads the queries from the `queries` argument, so a tool with another
  argument name loses its queries on reload, and nothing reports it.
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
  Query `chat_message` for the session to see the stored tree. Blank text and
  no tool calls are expected when `chat_session.incognito_record_mode` is
  `usage_only` ([[#incognito-decision-per-field]]); that is not data loss.
- `incognito-test-session` **Set up an incognito session for a test.** Make sure the deployment uses
  the Redis cache backend. Set the admin incognito record mode, then create a
  session with `incognito: true` in the create request. In `USAGE_ONLY` mode,
  the rows hold blank text, and the context sits in the tenant's Redis key
  `incognito_ctx:<session id>` from the first message on. After teardown the
  key holds `tombstone`.

---

## Verification

- Integration: `backend/tests/integration/tests/chat/` and
  `backend/tests/integration/tests/chat_retention/`.
- Unit: `backend/tests/unit/onyx/chat/` (save path and incognito helpers) and
  `backend/tests/unit/onyx/db/`.
- Incognito storage and Slack copy authorization:
  `backend/tests/external_dependency_unit/chat/` and
  `backend/tests/external_dependency_unit/db/`.
- By hand: send, edit, switch branches, and reload. The same branch, tool
  steps and citations must show, and the session has one root row.
