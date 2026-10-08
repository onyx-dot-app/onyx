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
| `parent_message_id` | Nullable. NULL only for the empty root message. |
| `latest_child_message_id` | Which child branch is "active" for this node. Only this pointer, not the whole tree, is walked to render the live conversation. |
| `last_summarized_message_id` | Set on a compression-summary message; the last original message it replaces. |
| `preferred_response_id` | User-message-only: which assistant child (of a multi-model turn) was chosen. `set_preferred_response` (`db/chat.py`) writes this and also advances `latest_child_message_id`. |
| `model_display_name` | Assistant-message-only, which model produced this row. |
| `request_params` | Requested reasoning effort plus the actual provider kwargs. Attribution, not content: kept even when `persist_content=False` (`backend/onyx/db/chat_response.py:save_chat_turn`). |
| `reasoning_tokens` | See §5, reasoning attaches forward. |
| `message` | Text. Blank string for a content-free incognito row. |
| `token_count` | |
| `message_type` | `MessageType`: `SYSTEM` (root only, never sent to the LLM as-is), `USER`, `ASSISTANT`, `TOOL_CALL_RESPONSE`, `USER_REMINDER` (`configs/constants.py:MessageType`). |
| `files` | `FileDescriptor` list, user message only. |
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
| `parent_chat_message_id` | Set only for a **top-level** call (one the LLM issued directly on this turn). |
| `parent_tool_call_id` | Set only for a **nested** call (issued by a sub-agent tool, itself a `ToolCall`). Exactly one of `parent_chat_message_id` / `parent_tool_call_id` is non-NULL. |
| `turn_number` | Same turn number + same parent = called in parallel. Different turn number = called sequentially. |
| `tab_index` | Ordering within a parallel group, for UI tabs. |
| `tool_id` | Not a FK; deleting the `Tool` row does not cascade here. |
| `tool_call_id` | The provider-facing call id string (must round-trip to the LLM). |
| `reasoning_tokens` | The reasoning that preceded this call. See §5. |
| `tool_call_arguments` | JSONB. For a sub-agent, this is the agent's task/instructions. |
| `tool_call_response` | Text. For a sub-agent, this is its final report, not its internal steps (those are the nested `ToolCall` rows). |
| `tool_call_tokens` | Token count of the arguments only; only top-level rows count toward the session total. |
| `generated_images` | Image-tool replay data. |

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
        ├─< ToolCall (parent_chat_message_id)      top-level calls
        │     └─< ToolCall (parent_tool_call_id)    nested/sub-agent calls
        │           └── ToolCall__SearchDoc → SearchDoc
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

Every session has exactly one root `ChatMessage` with `parent_message_id IS
NULL` and `message_type=SYSTEM`
(`db/chat.py:get_or_create_root_message`). Editing a message creates a new
sibling under the same parent, not a mutation of the original row. Each
`ChatMessage.latest_child_message_id` marks which child is the "live" branch;
walking the chain of `latest_child_message_id` pointers from the root gives
the currently displayed conversation. `set_as_latest_chat_message`
(`db/chat.py`) is what a branch switch calls: it repoints the parent's
pointer to the selected child, nothing else moves.

---

## 4. How it works

### 4.1 Writing a turn

```
prepare_chat_turn                        chat/prepare.py
  ├─ create_new_chat_message (user msg)   db/chat.py
  └─ reserve_message_id /
     reserve_multi_model_message_ids      db/chat.py        → assistant row(s) exist before streaming
...
ChatResponsePersistence                  chat/persistence.py
  └─ history store                       chat/history_store.py
        └─ save_chat_turn                 db/chat_response.py  → single db_session.commit()
              ├─ create_db_search_doc (per unique SearchDoc)
              ├─ add_search_docs_to_chat_message
              ├─ _create_and_link_tool_calls
              │     ├─ create_tool_call_no_commit  (per ToolCall, no parent yet)
              │     ├─ db_session.flush()          (assigns ids)
              │     ├─ set parent_tool_call_id from the id map
              │     └─ add_search_docs_to_tool_call
              └─ assistant_message.citations = {...}
```

The user message is created and committed independently
(`create_new_chat_message`), so it can exist even if the assistant message
later errors. The assistant row is reserved before the first token is
streamed (`reserve_message_id`, `reserve_multi_model_message_ids`), with a
placeholder message ("Response was terminated prior to completion...") and a
placeholder `token_count`. `save_chat_turn` then overwrites that same row and
commits once for the whole turn: message text, reasoning, tool calls, search
docs, and citations all land in one transaction. `_create_and_link_tool_calls`
creates every `ToolCall` first with no `parent_tool_call_id`, flushes to get
real ids, then wires up `parent_tool_call_id` from a `tool_call_id → id`
map built after the flush; it drops any child whose parent went missing
(possible when a stop cancels mid-tool-execution) rather than leave an
orphaned FK.

### 4.2 Reading a session back

`GET /chat/get-chat-session/{id}` (`chat_backend.py:get_chat_session`) does
not re-run the turn. It loads every `ChatMessage` for the session
(`db/chat.py:get_chat_messages_by_session`, which eager-loads two levels of
`ToolCall` via `selectinload(ChatMessage.tool_calls).selectinload(ToolCall.tool_call_children)`),
converts each to a `ChatMessageDetail`
(`translate_db_message_to_chat_message_detail`), and for every assistant
message calls `translate_assistant_message_to_packets`
(`session_loading.py`) to rebuild a `Packet` sequence from the persisted state. It is
not a byte-for-byte replay of the live stream: the saved answer text is one
`AgentResponseDelta`, where the live loop emits many streamed deltas. The
sequence is: tool calls grouped by `turn_number` (with per-turn
reasoning inserted just before the group, see §5), then the answer, then
citations, then an `OverallStop`. Which packet-builder runs is dispatched
per-tool by `tool.in_code_tool_id` (search, web search, open URL, image
generation, file reader, research agent, coding agent, memory, python, or a
generic custom-tool fallback). The frontend renders these replayed packets
with the same renderer it uses for the live stream.

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

## 5. Contracts and invariants

1. **Messages alternate user and assistant.** The empty `SYSTEM` root row is
   persisted (`get_or_create_root_message`). Prompt-time `SYSTEM`,
   `USER_REMINDER`, and custom-agent-prompt messages are never persisted. They
   are constructed at load time (`db/README.md`, `chat/README.md`,
   [[context-assembly]]).
2. **The empty root message must exist exactly once per session.**
   `get_or_create_root_message` reads the root row and inserts one if none
   exists. It does not use an atomic uniqueness constraint, so two
   concurrent first loads could each insert a root. Code must expect one
   root. `MultipleResultsFound` on a later read is treated as data
   corruption, not a recoverable case.
3. **Input is on the user message; everything produced during inference is on
   the assistant message.** Response text, tool calls, feedback, and
   citations never live on a `USER` row.
4. **Reasoning attaches to the message or tool call that came *after* it, not
   before.** With parallel tool calls, the same reasoning text is duplicated
   onto each of them (`db/README.md`;
   `session_loading.py:translate_assistant_message_to_packets` picks the
   first tool call in a turn that has `reasoning_tokens` and re-derives which
   turn slot to render it under). This is unintuitive and worth re-reading
   `db/README.md` before touching it.
5. **`save_chat_turn` commits exactly once per assistant message.** All of
   message text, `SearchDoc` rows, `ToolCall` rows, and citations land in that
   one transaction. Do not add a code path that commits partway through.
6. **A reserved assistant row must always resolve.** Either `save_chat_turn`
   overwrites it with real content, or the error path
   (`_save_errored_message`, owned by [[core-chat-loop]]) sets `error`. A row
   left at the "terminated prior to completion" placeholder with no error is
   a bug.
7. **A `ToolCall`'s parent is exactly one of `parent_chat_message_id` /
   `parent_tool_call_id`.** Same turn number + same parent = parallel;
   different turn number = sequential; a non-null `parent_tool_call_id` means
   this call happened *inside* an agent tool call, not as a retry of it.
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
- [[core-chat-loop]]: `save_chat_turn` is its single persistence entry point;
  it reserves rows here before streaming and loads history from here to build
  each cycle's context.
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
| adds a new tool call "kind" (e.g. a new nesting pattern) | `_create_and_link_tool_calls` (parent resolution and orphan handling), `translate_assistant_message_to_packets`'s per-tool dispatch, and [[tools-framework]] |
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
- **Tool responses are not stored in the LLM-facing history**, only the
  `ToolCall.tool_call_response` field on the DB row for replay purposes. What
  the model saw in later cycles was a fixed placeholder
  ([[core-chat-loop]] §9); do not confuse "what's in the DB" with "what the
  model remembers."
- **A `ToolCall` with `parent_tool_call_id` set is a sub-agent's internal
  call, not a retry.** `turn_number` distinguishes retries/sequences;
  `parent_tool_call_id` distinguishes nesting depth. Conflating the two will
  misrender the tool-call tree.
- **Incognito silently blanks rows.** A missing `message` or empty
  `tool_calls` list on a `ChatMessage` is not automatically a bug: check
  `ChatSession.incognito_record_mode` before assuming data loss.
- **`tool_id` on `ToolCall` is not a foreign key.** A deleted `Tool` leaves
  old `ToolCall` rows pointing at a dead id;
  `translate_assistant_message_to_packets` handles this with a `try`/`except`
  per tool call, logging and skipping rather than failing the whole replay.
- **Deleting a session does not unshare it.** `shared_status` is untouched by
  delete; only the `deleted` / hard-delete guard on `get_chat_session_by_id`
  keeps a deleted session from being readable through the share link.
- **The chat-retention TTL job is EE-only** (`ee/onyx/background/celery/tasks/ttl_management`).
  CE deployments have no automatic chat expiry regardless of any setting.

[[core-chat-loop]] [[citations]] [[context-assembly]] [[streaming-protocol]]
[[chat-frontend]] [[tools-framework]] [[access-control]] [[multi-tenancy]]
[[background-jobs]]
