# Chat Persistence

> How a conversation is stored and read back: the session, the message tree and
> its branching, tool call storage and nesting, surfaced documents, feedback,
> sharing, incognito, search over history, and retention.

**Verified against:** `268e4d5a3d` (2026-10-05)
**Domain:** core-loop
**Edition:** CE, with an EE-only retention job
**Owns:**
`backend/onyx/db/chat.py`, `chat_search.py`, `feedback.py`, `tools.py` (the
`ToolCall` half), `models.py` (`ChatSession`, `ChatMessage`, `ToolCall`,
`SearchDoc`, `ChatMessageFeedback`, `DocumentRetrievalFeedback`),
`backend/onyx/db/chat_response.py`, `incognito.py`, `incognito_context.py`,
`backend/onyx/db/incognito.py`,
`backend/onyx/server/query_and_chat/session_loading.py`,
`backend/onyx/server/query_and_chat/chat_backend.py` (session-lifecycle
endpoints), `backend/ee/onyx/background/celery/tasks/ttl_management/tasks.py`

**Read first:** `backend/onyx/db/README.md`. It is the design rationale for
the tree structure and the tool-call nesting, written by the people who built
it. This document maps it to code and adds verification guidance.

---

## 1. What the user experiences

Every conversation the user has ever sent shows up in the sidebar, newest
first, unless it is incognito. Opening one replays it exactly as it looked
live: reasoning, tool calls, documents, the answer, citations.

Editing a sent message does not overwrite it. It creates a sibling branch, and
the conversation continues from the edit. The user can switch between the
original and the edit (or any later edit) and see the rest of the
conversation change to match whichever branch is active. A user who sent one
message to two or three models can pick which model's answer to keep talking
to; that pick also becomes a branch choice.

The user can mark an assistant answer as helpful or not, with optional free
text. They can also mark a specific retrieved document as good or bad for a
question, independent of the whole-answer feedback.

A conversation can be made public by flipping a share toggle. Anyone with the
link then sees a read-only copy, but never a deleted one; deleting a chat
does not revoke a share.

A user can search their own conversation history with a text query. Search
matches both the chat title and the message contents. Incognito sessions
never appear in this search or anywhere else in the owner's own history.

Incognito hides a chat from the owner's own surfaces. Depending on a
workspace-wide admin setting, it may still store the full conversation
(hidden from that surface only) or store no conversation content. In the
second case the session keeps blank message rows and token counts for usage
accounting, and the live conversation ends when the tab closes.

If an admin sets a maximum chat retention window, chats older than that
window are deleted automatically, with no user-visible warning beyond the
data being gone.

---

## 2. Surfaces

### HTTP endpoints (router prefix `/chat`, `chat_backend.py`)

| Method | Path | Handler | Notes |
|---|---|---|---|
| GET | `/chat/get-chat-session/{id}` | `get_chat_session` | Reconstructs the full session, including replayed packets. See §4.2. |
| POST | `/chat/create-chat-session` | `create_new_chat_session` | |
| GET | `/chat/get-user-chat-sessions` | `get_user_chat_sessions` | Sidebar listing. |
| PUT | `/chat/rename-chat-session` | `rename_chat_session` | |
| PATCH | `/chat/chat-session/{id}` | `patch_chat_session` | Sets `shared_status`. |
| DELETE | `/chat/delete-chat-session/{id}`, `/chat/delete-all-chat-sessions` | `delete_chat_session_by_id`, `delete_all_chat_sessions` | Tears down incognito uploads and generated files first. See §5. |
| PUT | `/chat/set-message-as-latest` | `set_message_as_latest` | Branch selection: repoints the parent's `latest_child_message_id`. |
| PUT | `/chat/set-preferred-response` | `set_preferred_response_endpoint` | Picks the winning model in a multi-model turn. |
| POST/DELETE | `/chat/create-chat-message-feedback`, `/chat/remove-chat-message-feedback` | `create_chat_feedback`, `remove_chat_feedback` | Whole-answer feedback. |
| GET | `/chat/search` | `search_chats` | Full-text search over the user's own session titles and message bodies. |
| GET | `/chat/incognito-availability`, POST `/chat/end-incognito-session/{id}` | `get_incognito_availability`, `end_incognito_session` | See §9. |

### Environment / settings

| Setting | Where | Effect |
|---|---|---|
| `HARD_DELETE_CHATS` | `backend/onyx/configs/chat_configs.py` | Session delete removes rows instead of setting `deleted=True`. |
| `maximum_chat_retention_days` | Admin `Settings` (`server/settings/models.py`), EE only | Age past which `perform_ttl_management_task` hard-deletes a session. Each batch of a running chain reads it again and ends the chain when it is `None`. The Community downgrade sets it to `None` (`server/settings/store.py:clear_chat_retention`, see [[billing]] §4.5). |
| Incognito record mode | Admin security settings, read via `resolve_incognito_record_mode` (`chat/incognito.py`) | `FULL_HISTORY` or `USAGE_ONLY`; pinned per session at creation. |

---

## 3. Data model

Three migrations prepare SDK storage: `7a03b6e90c12` adds response items,
`6b4e821c0a93` adds checkpoints, and `9d8f310ac672` adds execution fields to existing tables.
The first two run transactionally. The third builds indexes concurrently on existing chat tables
and supports rerunning after an interrupted index build.

`chat_response_item.message` stores one complete or partial assistant model message per step.
Tool results and their execution statuses live in `tool_call`; they do not need response-item link rows.
`generation_status` records the model generation outcome, independently of the whole response or tool outcome.
`is_answer` identifies the step the runtime accepted as its answer. Partial output need not be an accepted answer.
Response items use `step_index` for generation order and the assistant’s tool-call list for result order.
Every response item belongs to a recorded model step; historical thinking does not create synthetic steps.
Legacy responses have null `response_status` and read thinking from `chat_message.reasoning_tokens`
and `tool_call.reasoning_tokens`, including explicit null values. SDK responses read thinking from response items.
Finalization also retains the existing final-thinking display column. SDK pre-tool thinking stays in response items.
Old API pods can omit SDK pre-tool thinking during deployment overlap; the stored model content remains intact.
No thinking backfill or column-removal migration runs in this release.

A unique `(chat_message_id, step_index)` index orders response lookups and permits one generation per step.
The assistant message orders its tool calls. Each call resolves to a tool row in that response and step,
including pending calls with no result. Stored result IDs remain stable across saves and replay.

For durable chat, the SDK run ID is the assistant `chat_message.id` represented as a string.
Root preparation reserves its response rows. Child startup reserves its question and response before constructing the run.
Output writers update those reserved rows. Resume retains the same response identity.
Standalone SDK runs and temporary incognito runs use generated IDs. Usage-only incognito stores no durable model/tool content or execution checkpoints.
Owner tokens and checkpoint ownership versions protect against stale writers; response IDs do not identify ownership attempts.
`ResponseRecord` retains the SDK names `run_id`, `previous_run_id`, `parent_run_id`, and `child_runs`.
Database operations use integer response IDs; execution records use their string form.
The root agent uses the chat-session ID in both history backends; incognito does not allocate a separate root identity.

Tool names and argument parsing details stay in the saved model message. Tool rows retain queryable arguments and execution results.
`tool_call.result` stores model content, outcome flags, and typed application details together.
`StoredToolResult` validates those details when saving and restores their concrete types when loading.
SDK rendering reads the saved details without looking up the current tool definition.
Search documents retain their existing relation; saved details contain queries, filters, citations, and the selection state.
Rendering loads those documents into a detached result. It does not change the saved conversation or checkpoint input.
Application enums define response, generation, and tool statuses; historical response and tool rows can have null statuses.

`chat_response_checkpoint` stores resume progress alongside response history, rather than another copy of that history.
Its `ownership_version` changes when a checkpoint is published or claimed, preventing stale owners from saving.
The runtime revision inside `state` tracks execution changes and serves a separate purpose.
Checkpoint bindings identify the tenant and response. Saved progress uses the runtime’s field names, including
`pending_tool_calls` and `human_tool_answers`.

### `ChatSession` (`db/models.py:ChatSession`, table `chat_session`)

| Column | Notes |
|---|---|
| `id` | UUID. Client-mintable for incognito uploads that precede the session (`db/chat.py:create_chat_session`). |
| `user_id` | Nullable: anonymous chats. |
| `persona_id` | The agent/persona in use. |
| `description` | Title. Never written for a content-free incognito session (`db/chat.py:update_chat_session`). |
| `onyxbot_flow` | True for Slack-originated sessions. |
| `incognito_record_mode` | `IncognitoRecordMode` enum or NULL. NULL is an ordinary chat. Pinned at creation; never re-read from the live admin setting after that (`chat/incognito.py:resolve_incognito_record_mode`). |
| `deleted` | Soft-delete flag, only meaningful when `HARD_DELETE_CHATS` is off. |
| `shared_status` | `ChatSessionSharedStatus.PUBLIC` / `PRIVATE` (`db/enums.py`). |
| `current_alternate_model` | |
| `slack_thread_id` | |
| `project_id` | FK to `user_project`. |
| `llm_override`, `temperature_override`, `reasoning_effort_override`, `prompt_override` | Per-session overrides; take precedence over the persona but are outranked by per-request overrides. |
| `time_created`, `time_updated` | |

There is no separate chat-folder table. Scoping is by `project_id` and by the
sidebar's own client-side grouping; there is no `ChatFolder` model in
`db/models.py`. Sharing is the `shared_status` column above; there is no
separate share-link table.

### `ChatMessage` (`db/models.py:ChatMessage`, table `chat_message`)

| Column | Notes |
|---|---|
| `id` | Integer PK. |
| `chat_session_id` | FK. |
| `parent_message_id` | NULL for the public session root or a child session's first question. Otherwise links to the preceding message. |
| `latest_child_message_id` | Which child branch is "active" for this node. Only this pointer, not the whole tree, is walked to render the live conversation. |
| `last_summarized_message_id` | Set on a compression-summary message; the last original message it replaces. |
| `preferred_response_id` | User-message-only: which assistant child (of a multi-model turn) was chosen. `set_preferred_response` (`db/chat.py`) writes this and also advances `latest_child_message_id`. |
| `model_display_name` | Assistant-message-only, which model produced this row. |
| `request_params` | Requested reasoning effort plus the actual provider kwargs. Attribution, not content: kept even when `persist_content=False` (`backend/onyx/db/chat_response.py:save_chat_turn`). |
| `reasoning_tokens` | See §5, reasoning attaches forward. |
| `message` | Text. Blank string for a content-free incognito row. |
| `token_count` | |
| `message_type` | `MessageType`: `SYSTEM` (root only, never sent to the LLM as-is), `USER`, `ASSISTANT`, `SUMMARY`, `TOOL_CALL_RESPONSE`, `USER_REMINDER` (`configs/constants.py:MessageType`). |
| `files` | `FileDescriptor` list: user attachments or referenced generated files on assistant responses. |
| `citations` | `{citation_number: search_doc_id}`, assistant message only. |
| `error` | |
| `time_sent` | |
| `is_clarification` | Deep-research clarification-question flag. |
| `processing_duration_seconds` | |

### `ToolCall` (`db/models.py:ToolCall`, table `tool_call`)

| Column | Notes |
|---|---|
| `id` | |
| `chat_session_id` | |
| `parent_chat_message_id` | Canonical response owner for every SDK call, including calls made by child agents. Legacy nested calls can omit it. |
| `parent_tool_call_id` | Optional display nesting under the tool that invoked the child. It does not replace canonical response ownership. |
| `turn_number` | SDK step index within the owning response. Calls in one step can execute in parallel. Legacy rows retain their display grouping. |
| `tab_index` | Ordering within a parallel group, for UI tabs. |
| `tool_id` | Not a FK; deleting the `Tool` row does not cascade here. |
| `tool_call_id` | The provider-facing call id string (must round-trip to the LLM). |
| `reasoning_tokens` | The reasoning that preceded this call. See §5. |
| `tool_call_arguments` | JSONB. For a sub-agent, this is the agent's task/instructions. |
| `result` | JSONB. SDK tool result: model content, call identity, outcome flags, and typed application details. |
| `tool_call_response` | Legacy output text, mapped as `legacy_response`. SDK saves leave it empty. The Python `tool_call_response` property returns `result.text` when a result exists. |
| `tool_call_tokens` | Token count of the arguments only; only top-level rows count toward the session total. |
| `generated_images` | Legacy image replay data. SDK results store images in their typed details. |

### `SearchDoc` (`db/models.py:SearchDoc`, table `search_doc`)

| Column | Notes |
|---|---|
| `id` | |
| `document_id`, `chunk_ind`, `semantic_id`, `link`, `blurb` | Snapshot of the chunk at retrieval time, not a live reference. |
| `source_type`, `boost`, `hidden`, `doc_metadata`, `score`, `match_highlights` | |
| `is_relevant`, `relevance_explanation` | LLM relevance judgment, if run. |
| `is_internet` | |
| `primary_owners`, `secondary_owners` | |

Linked to `ChatMessage` through `ChatMessage__SearchDoc` (the message's final
displayed set) and to `ToolCall` through `ToolCall__SearchDoc` (what a
specific tool call surfaced). A doc can be linked to both simultaneously.
`SearchDoc` does not store chunk content: replaying a session shows the same
citation, but selecting it for a new turn re-runs retrieval
(`db/models.py:SearchDoc` docstring).

### Feedback

`ChatMessageFeedback` (table `chat_feedback`): `chat_message_id`,
`is_positive`, `required_followup`, `feedback_text`, `predefined_feedback`.
Assistant-message-only (`db/feedback.py:create_chat_message_feedback` raises
if `message_type != ASSISTANT`).

`DocumentRetrievalFeedback` (table `document_retrieval_feedback`):
`chat_message_id`, `document_id`, `document_rank`, `clicked`, `feedback`
(`SearchFeedbackType`: `ENDORSE`/`REJECT` adjust `Document.boost`,
`HIDE`/`UNHIDE` toggle `Document.hidden`). This is feedback on a document in
general, keyed by `document_id`, separate from `SearchDoc`'s per-turn
snapshot.

### Entity diagram

```
ChatSession
  └─< ChatMessage (parent_message_id → self, tree)
        ├─< ChatResponseItem                     model generations
        ├── ChatResponseCheckpoint               suspended execution progress
        ├─< ToolCall (parent_chat_message_id)      results and execution status
        │     ├── parent_tool_call_id → ToolCall  optional child display nesting
        │     └── ToolCall__SearchDoc → SearchDoc
        ├── ChatMessage__SearchDoc → SearchDoc       message's displayed docs
        ├─< ChatMessageFeedback
        └─< DocumentRetrievalFeedback
```

### The message tree

Reproduced from `db/README.md`:

```
                 [Empty Root Message]  (allows the first message to be branched/edited too)
              /           |           \
[First Message] [First Message Edit 1] [First Message Edit 2]
       |                  |
[Second Message]  [Second Message of Edit 1 Branch]
```

Every public chat session has one root `ChatMessage` with `parent_message_id IS
NULL` and `message_type=SYSTEM`
(`db/chat.py:get_or_create_root_message`). Editing a message creates a new
sibling under the same parent, not a mutation of the original row. Each
`ChatMessage.latest_child_message_id` marks which child is the selected branch;
walking the chain of `latest_child_message_id` pointers from the root gives
the currently displayed conversation. `set_as_latest_chat_message`
(`db/chat.py`) is what a branch switch calls: it repoints the parent's
pointer to the selected child, nothing else moves.

Child sessions start with a user question linked to the invoking tool call. They
do not need an empty SYSTEM root. Their later questions link to prior child responses.

`set_preferred_response` accepts only an assistant child in the user message's
chat session. It validates the type, session, and parent before changing either
`preferred_response_id` or `latest_child_message_id`. Invalid selections leave
both pointers unchanged. The endpoint checks ownership of the user message first.

---

## 4. How it works

### 4.1 Writing a turn

```text
prepare_chat_turn                        chat/prepare.py
  -> create_new_chat_message             db/chat.py: accepted user input
  -> reserve_chat_response_ids           db/chat.py: assistant rows

ChatRunStore                             chat/run_store.py
  -> save_response_record__no_commit      db/chat_response.py: progressive execution
  -> checkpoint storage                  db/chat_checkpoint.py: suspended progress

ChatResponsePersistence                  chat/persistence.py: final root output
  -> ChatHistoryStore                    chat/history_store.py
  -> save_chat_response_to_db             db/chat_response.py
  -> save_chat_turn                      db/chat_response.py: final transaction
```

Preparation commits accepted user input before slow file loading. It reserves each
assistant response before execution starts, so streamed output has a stable identity.
Child startup also reserves its question and response before constructing a run.

Execution saves upsert model generations and tool records as work progresses.
This makes child references and suspended work available before the root finishes.
Final root persistence writes display text, documents, citations, execution content,
and completion status in one transaction. It updates the reserved response row.
Usage-only incognito keeps conversation content in temporary storage instead.

Tool calls retain their response owner and step. Child calls can also link to their
invoking parent tool for nested display. Result content is stored once on `ToolCall`;
model generations retain the original call names, arguments, and order.

### 4.2 Reading a session back

`GET /chat/get-chat-session/{id}` loads the session's message tree and builds
`ChatMessageDetail` objects. `translate_assistant_message_to_packets` selects one
of two readers for assistant responses:

- SDK responses load recorded generations and tool results through `read_chat_execution`.
  Shared chat renderers project that content into browser packets.
- Legacy responses reconstruct display from old message and tool columns, grouping
  calls by `turn_number`. Their thinking placement is approximate.

Neither path reruns tools or models. Saved output can arrive in larger text chunks
than live output, but uses the same browser packet types. SDK replay preserves
interleaved text, thinking, call identity, and partial work.

SDK replay skips child-response queries for messages without tool calls. Root
sessions also skip ancestor queries. Loading plain chat history must not add
one query per assistant message.

Coordinator setup reuses its validated branch for child-agent discovery. It
registers the root separately and skips ancestry reads when no children exist.
Discovery tests must check selected-branch visibility as well as query counts.

The response also carries `current_stream` (`CurrentStreamInfo.stream_id`) when the
processing fence shows an unfinished stream. The client uses it to reconnect through
`resume-stream`.

---

### 4.3 Naming a session

`chat_backend.py:rename_chat_session` loads the session's history and override,
then generates its title outside the read session. `get_default_utility_llm(..., flow_type=LLMModelFlowType.CHAT_NAMING)` prefers
the admin CHAT_NAMING default and returns `None` when it is unset.
Only then does the endpoint construct and cost-check the session client.
Configured utility clients receive one provider cost check in the factory.
Naming keeps its existing rate-limit check and text fallback on failure. Sessions whose
incognito mode does not persist content skip the naming call.

## 5. Contracts and invariants

1. **Public message trees contain user input and assistant responses.**
   Each response belongs to a user message. Model steps and tools belong to that response.
   SUMMARY rows store compaction cutoffs and stay out of public message history.
   Prompt-only instructions and reminders are assembled for requests, not saved as user input.
2. **Public sessions use one empty SYSTEM root.** `get_or_create_root_message`
   provides it for branching the first question. Child sessions begin with their
   first user question instead. Multiple public roots indicate corrupt state.

3. **Input is on the user message; everything produced during inference is on
   the assistant message.** Response text, tool calls, feedback, and
   citations never live on a `USER` row.
4. **Thinking preserves its recorded placement.** SDK response items retain thinking within the assistant model message.
   Legacy thinking precedes its tool-call group or final answer. For parallel legacy calls, the loader selects
   the first nonempty thinking value in the group. Legacy display text does not provide exact model block order
   or provider signatures and must not be treated as a recorded SDK generation.
5. **Final projection is atomic.** `save_chat_turn` commits display text, documents,
   tool records, and citations together. Progressive execution saves and checkpoint
   writes use separate transactions before finalization.
6. **Reserved responses must reach a recorded outcome.** Normal completion, cancellation,
   and failure save partial work or an error. Root startup failures record an error;
   failed child startup removes unused question/response reservations.
7. **SDK tool calls have canonical response ownership.** `parent_chat_message_id`
   identifies the response; `turn_number` identifies its step. Optional
   `parent_tool_call_id` adds child-agent display nesting. Both links can be set.

8. **Incognito must not persist content.** `save_chat_turn(...,
   persist_content=False)` blanks `message`/`reasoning_tokens`, and drops
   `tool_calls`, `citation_to_doc`, `all_search_docs`, and
   `emitted_citations` before doing anything else. `request_params` is kept
   deliberately (attribution, not content). Any new field added to
   `save_chat_turn` or `ChatMessage` needs an explicit incognito decision, not
   a default.
9. **Replay must match the live stream.** `translate_assistant_message_to_packets`
   is the only source of truth for `GET /chat/get-chat-session/{id}`; it must
   stay in sync with whatever [[streaming-protocol]] packets the live loop
   emits for each tool.
10. **Deleting a session must not orphan `ToolCall` or `SearchDoc` rows.**
    `delete_messages_and_files_from_chat_session` deletes `ChatMessage` rows
    (cascading `ToolCall` via `ondelete="CASCADE"` on `parent_chat_message_id`
    and `chat_session_id`), then calls `delete_orphaned_search_docs` to sweep
    `SearchDoc` rows left with no `ChatMessage__SearchDoc` link.
11. **A shared (public) session must never expose a soft-deleted one.**
    `get_chat_session_by_id(is_shared=True)` filters on `deleted.is_(False)`
    unconditionally; `include_deleted` only applies to the owner/admin path.

---

## 6. Relationships

**Depends on**
- [[tools-framework]]: supplies `tool_id` / `in_code_tool_id` and the tool
  implementations that `session_loading.py` dispatches on for replay.
- [[citations]]: builds `citation_to_doc` that `save_chat_turn` persists into
  `ChatMessage.citations`.
- [[context-assembly]]: reads this history back out to build the next turn's
  prompt (injects system/reminder messages that this component never stores).
- [[streaming-protocol]]: the `Packet` vocabulary that replay reconstructs.
- [[background-jobs]]: hosts the EE chat-TTL Celery chain.
- [[multi-tenancy]]: every table here is tenant-scoped like the rest of the
  schema.

**Depended on by**
- [[core-chat-loop]]: reserves responses before streaming, saves progressive
  execution and final display, and loads the selected history branch.
- [[chat-frontend]]: renders both the live packet stream and the replayed one
  from `GET /chat/get-chat-session/{id}`; consumes `latest_child_message_id`
  to drive branch switching in the UI.
- [[access-control]]: `get_chat_session_by_id`'s `user_id` / `is_shared` gate
  is the enforcement point for who can read a session.
- [[chat-frontend]] and the public API also drive `set-message-as-latest` and
  `set-preferred-response` directly from user actions.

---

## 7. Blast radius

| If your change… | Also check |
|---|---|
| adds a column to `ChatMessage` | write a migration; decide what `save_chat_turn` writes into it; decide the incognito behavior (blank it or keep it, and say why); add it to `translate_db_message_to_chat_message_detail` and the `ChatMessageDetail` API model if the frontend needs it; check whether `session_loading.py` needs to replay it |
| changes the tree (adds a new kind of branch, changes what `latest_child_message_id` means) | `set_as_latest_chat_message`, `set_preferred_response`, every caller that walks the chain in [[core-chat-loop]] and [[context-assembly]], and the frontend's branch-switch UI in [[chat-frontend]] |
| adds a new tool call "kind" (e.g. a new nesting pattern) | `save_response_content` (response ownership and parent resolution), `translate_assistant_message_to_packets`'s per-tool dispatch, and [[tools-framework]] |
| changes replay (`session_loading.py`) | confirm the packets it builds still match what the live loop in [[core-chat-loop]] emits for the same tool; check every `tool.in_code_tool_id` branch, not just the one you touched |
| changes retention or deletion | `delete_messages_and_files_from_chat_session`, `delete_orphaned_search_docs`, the EE `perform_ttl_management_task` chain, and the incognito teardown paths in `chat_backend.py:_teardown_incognito_after_delete` |
| changes incognito record modes | every `record_mode_persists_content` call site (`db/chat.py`, `backend/onyx/db/chat_response.py`, `chat/incognito.py`), and the search/history exclusion filters in `db/chat.py:content_persisting_sessions_filter` and `db/chat_search.py` |
| changes sharing (`shared_status`) | `get_chat_session_by_id(is_shared=True)`'s `deleted` guard; [[access-control]] |

---

## 8. How to verify a change

### Tests

```bash
# Integration (preferred). Run the env-file commands from the repo root.
uv run --env-file .vscode/.env pytest backend/tests/integration/tests/chat
uv run --env-file .vscode/.env pytest backend/tests/integration/tests/chat_retention

# Unit
cd backend && uv run pytest tests/unit/onyx/chat/test_response_projection.py
cd backend && uv run pytest tests/unit/onyx/db/test_chat_sessions.py tests/unit/onyx/db/test_chat_message_cleanup.py
cd backend && uv run pytest tests/unit/onyx/chat/test_incognito_record_mode.py tests/unit/onyx/chat/test_incognito_liveness_predicates.py

# External dependency unit (incognito, needs Postgres/Redis up)
uv run --env-file .vscode/.env pytest backend/tests/external_dependency_unit/chat/test_incognito_persistence.py
uv run --env-file .vscode/.env pytest backend/tests/external_dependency_unit/db/test_incognito_history_exclusion.py
```

### Manual reproduction

1. Confirm services are up: `tail -f backend/log/api_server_debug.log`.
2. Open `http://localhost:3000`, sign in as `admin_user@example.com` /
   `TestPassword123!`.
3. Send a message, then edit it. Confirm a new branch appears and the
   conversation continues from the edit.
4. Switch back to the original branch. Confirm the assistant's original
   answer is still there (not regenerated).
5. Share the session (toggle sharing), open the share link in a private
   window, confirm it renders read-only.
6. Reload the page. The replayed view (reasoning, tool calls, documents,
   citations) must be visually identical to what streamed live.
7. Inspect rows directly:
   ```bash
   PGPASSWORD="${POSTGRES_PASSWORD:-password}" psql -h "${POSTGRES_HOST:-localhost}" -U postgres -c \
     "SELECT id, parent_message_id, latest_child_message_id, message_type, left(message, 40) FROM chat_message WHERE chat_session_id = '<session-id>' ORDER BY id;"
   PGPASSWORD="${POSTGRES_PASSWORD:-password}" psql -h "${POSTGRES_HOST:-localhost}" -U postgres -c \
     "SELECT id, parent_chat_message_id, parent_tool_call_id, turn_number, tab_index, tool_id FROM tool_call WHERE chat_session_id = '<session-id>' ORDER BY id;"
   ```
   Confirm exactly one root row (`parent_message_id IS NULL`), and that
   `ToolCall` rows show the parallel/sequential/nested pattern you expect.
8. Start an incognito chat, send a message, confirm it never appears in
   `/chat/get-user-chat-sessions` or `/chat/search`, then close the tab and
   confirm `chat_message` rows for that session are blank (`USAGE_ONLY`) or
   absent from the sidebar (`FULL_HISTORY`).

### What "working" looks like

- Exactly one root `ChatMessage` per session.
- `latest_child_message_id` chain matches what the UI currently displays.
- Replayed packets are pixel-identical to the live stream for the same turn.
- No `SearchDoc` rows survive with zero `ChatMessage__SearchDoc` links after a
  delete.
- An incognito session never shows up in the owner's history, search, or
  project lists.

---

## 9. Footguns

- **Reasoning attaches to the following message or tool call, not the
  preceding one.** Counting on reasoning "belonging" to the turn that
  produced it will misattribute it after a branch edit. Read `db/README.md`
  again before changing anything near `reasoning_tokens`.
- **The empty root message means message counts are off by one** from what a
  naive count of "turns" suggests. Do not assume `len(messages)` is `2 *
  num_turns`.
- **Tool content and application details have different consumers.** SDK history
  replays the saved result content to the model. Rendering reads its typed details.
  Legacy history may use placeholders because it lacks saved model-facing results.
- **A `ToolCall` with `parent_tool_call_id` set is a sub-agent's internal
  call, not a retry.** `turn_number` distinguishes retries/sequences;
  `parent_tool_call_id` distinguishes nesting depth. Conflating the two will
  misrender the tool-call tree.
- **Incognito silently blanks rows.** A missing `message` or empty
  `tool_calls` list on a `ChatMessage` is not automatically a bug: check
  `ChatSession.incognito_record_mode` before assuming data loss.
- **`tool_id` on `ToolCall` is not a foreign key.** A deleted `Tool` leaves
  old calls pointing at a missing definition. SDK rendering uses saved typed
  details and still works. Legacy rendering may log and skip those calls.
- **Deleting a session does not unshare it.** `shared_status` is untouched by
  delete; only the `deleted` / hard-delete guard on `get_chat_session_by_id`
  keeps a deleted session from being readable through the share link.
- **The chat-retention TTL job is EE-only** (`ee/onyx/background/celery/tasks/ttl_management`).
  CE deployments have no automatic chat expiry regardless of any setting.

[[core-chat-loop]] [[citations]] [[context-assembly]] [[streaming-protocol]]
[[chat-frontend]] [[tools-framework]] [[access-control]] [[multi-tenancy]]
[[background-jobs]]
