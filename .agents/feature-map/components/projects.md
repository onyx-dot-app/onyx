# Projects

> A durable scope: a named collection of files plus instructions that persists
> across chat sessions, as opposed to a file dropped into one conversation. This
> document owns project structure, ownership, and the session relationship. It
> shares the inline-vs-retrieval mechanics with [[file-store-and-user-files]]
> and [[context-assembly]], which are the fuller authorities on that machinery.

**Verified against:** `268e4d5a3d` (2026-10-05)
**Domain:** core-loop
**Edition:** CE
**Owns:**
`backend/onyx/db/projects.py`,
`backend/onyx/server/features/projects/` (`api.py`, `models.py`, `projects_file_utils.py`),
`web/src/lib/projects/` (`providers.tsx`, `hooks.ts`, `svc.ts`, `types.ts`, `utils.ts`,
`components/`)

**Read first:** [[file-store-and-user-files]] owns the blob store, extraction,
token counting, and the two consumption paths in full detail; this document
only restates the parts of that machinery a project changes. [[context-assembly]]
owns exactly how the injected project message behaves once it is in the prompt
(position, movement, truncation immunity). `backend/onyx/chat/README.md`'s
"Projects" section is the product rationale for why project files never drop.

---

## 1. What the user experiences

The user creates a project, gives it a name, and can attach instructions and
files to it. Every chat started inside the project shares that context: the
model sees the project's instructions and files without the user re-explaining
or re-uploading anything, in every session, indefinitely.

This is the difference from dropping a file into one chat: a chat attachment
belongs to that conversation and eventually drifts out of context as the chat
grows ([[context-assembly]] §4.3); a project file is expected to matter for as
long as the project exists, and the system is built around never losing it
silently.

A small project (a handful of short files) behaves like the files are simply
"always there": the model answers as if they were pasted into every message. A
large project (many files, or a few large ones) instead becomes searchable:
the sidebar shows the file "processing", then the model finds and cites the
relevant part instead of having the whole project stuffed into every prompt.
The user does not choose this distinction; it is decided by the total size of
the project relative to the model's context.

The project's context panel shows a live token count for its files and a
warning when that count exceeds the available context, but this is advisory,
not authoritative. Removing a file from a project, or deleting the project
itself, does not delete the file. Attaching a custom agent to a chat inside a
project overrides the project's own instructions entirely, which is easy to
miss because nothing in the UI calls this out.

---

## 2. Surfaces

### HTTP endpoints (router prefix `/user/projects`, `api.py`)

| Method | Path | Handler | Notes |
|---|---|---|---|
| GET | `/user/projects` | `get_projects` | Lists the caller's own projects. |
| POST | `/user/projects/create` | `create_project` | Name only; max 255 chars (`_validate_project_field_length`). |
| GET | `/user/projects/{project_id}` | `get_project` | 404s if not owned by the caller. |
| PATCH | `/user/projects/{project_id}` | `update_project` | Rename / re-describe. |
| DELETE | `/user/projects/{project_id}` | `delete_project` | Unlinks files and chat sessions; deletes only the `UserProject` row. See §4.7. |
| GET | `/user/projects/{project_id}/details` | `get_project_details` | Project + its files + which personas used in its sessions are featured. |
| GET / POST | `/user/projects/{project_id}/instructions` | `get_project_instructions`, `upsert_project_instructions` | Reads/writes `UserProject.instructions` directly. |
| GET | `/user/projects/files/{project_id}` | `get_files_in_project` | Excludes `FAILED` files. |
| POST / DELETE | `/user/projects/{project_id}/files/{file_id}` | `link_user_file_to_project`, `unlink_user_file_from_project` | Association only; sets `needs_project_sync=True` and triggers a project sync. See §4.7. |
| GET | `/user/projects/{project_id}/token-count` | `get_project_total_token_count` | See §4.8. |
| GET | `/user/projects/session/{chat_session_id}/token-count` | `get_chat_session_project_token_count` | Same sum, resolved via the session's `project_id`. |
| GET | `/user/projects/session/{chat_session_id}/files` | `get_chat_session_project_files` | Empty list if the session has no project. |
| POST | `/user/projects/{project_id}/move_chat_session` | `move_chat_session` | Sets `ChatSession.project_id`. |
| POST | `/user/projects/remove_chat_session` | `remove_chat_session` | Clears `ChatSession.project_id` (the chat itself is not deleted). |

File upload (`POST /user/projects/file/upload`), file delete
(`DELETE /user/projects/file/{file_id}`), file metadata/status, and the file
serving endpoint (`GET /chat/file/{file_id}`) are owned by
[[file-store-and-user-files]] §2; this component only supplies the
`project_id` those calls carry.

### Environment configuration

No environment variable belongs to this component alone. `DISABLE_VECTOR_DB`
(`configs/app_configs.py`) changes whether an oversized project falls back to
search or to `FileReaderTool` metadata, and switches project-sync from Celery
to in-request `BackgroundTasks`
(`api.py:_trigger_user_file_project_sync`), both owned by
[[file-store-and-user-files]] §2.

---

## 3. Data model

```
UserProject (user_project)                 Project__UserFile (project__user_file)
  id PK (autoincrement)                      project_id FK → user_project.id  (PK, part 1)
  user_id FK → user.id                       user_file_id FK → user_file.id  (PK, part 2)
  name                                       created_at
  description
  instructions

ChatSession (chat_session)                 UserFile (user_file)  -- see [[file-store-and-user-files]] §3
  id PK                                      id PK (UUID)
  ...                                        token_count, chunk_count, status, ...
  project_id FK → user_project.id (nullable) projects  -- via Project__UserFile
```

- `UserProject` (`db/models.py:UserProject`) is owned by exactly one `user_id`.
  There is no group, team, or share table anywhere in this component. See §5.
- `Project__UserFile` (`db/models.py:Project__UserFile`) is the many-to-many
  join, a composite-PK table (`project_id`, `user_file_id`). A `UserFile` can
  belong to zero, one, or more projects at once
  (`db/models.py:UserFile.projects`); this is a genuine many-to-many, not a
  single-project pointer.
- `ChatSession.project_id` (`db/models.py:ChatSession.project_id`) is a
  **nullable** foreign key to `user_project.id`. A session either belongs to
  exactly one project or to none; it is never itself a member of many.
- `UserProject.instructions` is a plain `String` column (`db/models.py:UserProject.instructions`),
  read by `db/projects.py:get_project_instructions` and
  `chat_utils.py:get_custom_agent_prompt` (§4.5).
- No new table belongs to this component beyond the join; a proposal to add
  one is a signal to re-check whether the existing `Project__UserFile` /
  `ChatSession.project_id` shape can express it (root `CLAUDE.md` on avoiding
  migrations).

---

## 4. How it works

### 4.1 Creating a project and adding files

`POST /user/projects/create` (`api.py:create_project`) inserts a bare
`UserProject` row; instructions and files are added afterward through separate
calls. Uploading with a `project_id`
(`db/projects.py:create_user_files`) inserts the `UserFile` row and, in the
same transaction, a `Project__UserFile` row, **except for incognito uploads**,
which never join a project even if a `project_id` is passed
(`create_user_files`'s `if project_id and incognito_session_id is None` guard).
An existing file can also be linked or unlinked after the fact
(`api.py:link_user_file_to_project`, `unlink_user_file_from_project`) without
re-uploading. Everything upstream of this, storage backend, extraction, token
counting, is [[file-store-and-user-files]] §4.1-4.5.

### 4.2 Where the inline-vs-retrieval decision is made, and the threshold

The decision is made once per turn, in
`process_message.py:extract_context_files`, for whichever files
`process_message.py:resolve_context_user_files` resolved for this turn (§4.5
covers precedence). It compares the aggregate token count of those files
against:

```
(llm_max_context_window - reserved_token_count) * 0.6
```

Below that ceiling, files are inlined (§4.3). At or above it, `use_as_search_filter`
is set and the project becomes retrieval-only for this turn (§4.4). The 60%
factor exists because the tokenizer used at upload time is only approximate,
and to keep a project-heavy turn from starving the rest of the token budget;
[[context-assembly]] §4.3 and §4.8 own the full reasoning and the reservation
order. This is a **per-turn, per-model** decision: a project below the ceiling
for one model can be above it for a model with a smaller context window
(`extract_context_files` uses `min(llm.config.max_input_tokens for llm in llms)`
across a multi-model turn, `process_message.py:build_chat_turn`).

### 4.3 Path A: inlined

Below the ceiling, `backend/onyx/chat/prompt_utils.py:_create_context_files_message` renders the
project's files into the same `document`-keyed JSON block
[[context-assembly]] §4.4 describes, and inserts it as a `MessageType.USER`
message. Per `context-assembly.md` §4.3 and `backend/onyx/chat/README.md`'s
"Projects" section, this message **moves forward** with the conversation every
cycle, the same way the custom agent prompt does, and is **never dropped**
under truncation, unlike a chat attachment which is allowed to fade. The
reasoning: project files are assumed to be central to what the user is doing,
not a needle-in-a-haystack fact worth risking a silent drop to save space.

### 4.4 Path B: retrieved

At or above the ceiling, the files are flagged `use_as_search_filter=True`
(`process_message.py:extract_context_files`), and
`process_message.py:determine_search_params` sets `SearchParams.project_id_filter`
to the active project's id (only for the default persona; see §4.5) and turns
the search tool `SearchToolUsage.ENABLED` for the turn. The model must retrieve
project content through the internal search tool
([[tools-framework]], [[internal-search]]) instead of reading it from the
prompt. `context/search/models.py:UserFileFilters.project_id_filter` is what
the document index applies: it scopes search to the project's files, it does
not additionally search team knowledge alongside them.

**Project files are always vectorized on upload, independent of this
decision.** Indexing runs through
`indexing/adapters/user_file_indexing_adapter.py:UserFileIndexingAdapter`,
driven by the `user_file_processing` Celery worker's
`PROCESS_SINGLE_USER_FILE` task
(`background/celery/tasks/user_file_processing/tasks.py:process_user_file_impl`
→ `_process_user_file_with_indexing`), which runs the same
`run_indexing_pipeline` used for connector documents ([[indexing-pipeline]]).
So a project that fits in context today is still fully searchable if the user
later switches to a model with a smaller window, without a reindex being
triggered by that switch. `UserFileChunkEnricher.enrich_chunk`
(`user_file_indexing_adapter.py`) stamps each chunk with the project ids that
own the file at enrichment time (`user_file_id_to_project_ids`, fetched via
`db/user_file.py:fetch_user_project_ids_for_user_files`), which is what
`project_id_filter` matches against at search time.

### 4.5 Project instructions and persona precedence

`chat_utils.py:get_custom_agent_prompt(persona, chat_session)` resolves the
custom agent prompt for a turn:

1. If the active persona is not the default persona
   (`persona.id != DEFAULT_PERSONA_ID`), its own `system_prompt` is used,
   **even inside a project**, unless `persona.replace_base_system_prompt` is
   set, in which case there is no separate custom agent prompt at all (it
   becomes the whole system prompt).
2. Only if the default persona is active does it fall back to
   `chat_session.project.instructions`.

**Verified: a custom persona fully supersedes the project.** This is stated
twice in the source: once in `get_custom_agent_prompt`'s own docstring, and
independently in `process_message.py:resolve_context_user_files`'s docstring,
which extends the same precedence to files: "A custom persona fully
supersedes the project... its files are never loaded and never made
searchable." `resolve_context_user_files` and `determine_search_params` both
implement this a second time in code (`if persona.id != DEFAULT_PERSONA_ID:
return list(persona.user_files)`), so a project attached to a chat running a
custom agent contributes nothing to that turn: no instructions, no files, no
search scoping. The project still shows the chat in `ProjectChatSessionList`
(§4.6); it is purely organizational in that case.

### 4.6 The session relationship

`ChatSession.project_id` is set once a chat is created inside a project or
moved into one (`api.py:move_chat_session`), and cleared by
`api.py:remove_chat_session`; both leave the chat session itself intact.
Selecting a project when starting a chat scopes that session to the project
for its lifetime unless explicitly moved out; it is not re-derived from the
URL on every load.

The frontend deliberately does not keep `projectId` in the URL once a chat is
open (`PARAMS_TO_SKIP`, `app/app/services/lib.tsx`), so
`web/src/lib/projects/hooks.ts:useActiveProject` resolves the active project
two ways: from the URL's `projectId` param when on a project's own page, or by
searching the loaded project list for the one whose `chat_sessions` contains
the open chat id when inside a chat. `web/src/views/AppPage.tsx` reads this
through `useActiveProject()` and gates on it directly: deep research is
disabled for any chat resolved into a project
(`deepResearchEnabledForCurrentWorkflow = !isLoadingProjects && activeProject
=== null && deepResearchEnabled`), so a project chat cannot start a deep
research run.

`web/src/lib/projects/components/ProjectChatSessionList.tsx` renders the
sessions in the currently open project (via `useProjectsContext`), and offers
per-chat delete and move-to-another-project actions
(`svc.ts:moveChatSession`, `removeChatSessionFromProject`); moving out of a
project is a metadata change to `ChatSession.project_id`, not a content
change to the chat.

### 4.7 File lifecycle

- **Add**: `link_user_file_to_project` inserts a `Project__UserFile` row if
  absent, sets `user_file.needs_project_sync=True`, and triggers
  `api.py:_trigger_user_file_project_sync`.
- **Remove (unlink)**: `unlink_user_file_from_project` removes the
  `Project__UserFile` row the same way, and triggers the same sync. **This
  does not delete the `UserFile` row, its blob, or its indexed chunks.**
  Instead, `tasks.py:project_sync_user_file_impl` re-reads the file's current
  project memberships (`project_ids = [project.id for project in
  user_file.projects]`, now excluding the unlinked project) and calls
  `_sync_metadata_and_reconcile_secondary` with a `MetadataUpdateRequest`
  carrying the fresh `project_ids` set. This is a **metadata-only** update
  against the existing chunks (no re-chunk, no re-embed): the chunk's stored
  project scoping is corrected in place, so `project_id_filter` for the
  removed project no longer matches it. The chunks are not deleted; they
  simply stop being visible to that project's scoped search (and to any other
  project or persona that never referenced them). The same task also handles
  persona attach/detach (`persona_ids`) in one pass.
- **Delete a file entirely**: `DELETE /user/projects/file/{file_id}`
  (`api.py:delete_user_file`) refuses while the file has any project or
  persona association, forcing an unlink first. Once unassociated, it deletes
  the file from every document index, then both blobs, then the `UserFile`
  row, in that order (owned in full by [[file-store-and-user-files]] §4.9,
  contract 4).
- **Delete a project**: `DELETE /user/projects/{project_id}`
  (`api.py:delete_project`) unlinks every `Project__UserFile` row
  (`for uf in list(project.user_files): project.user_files.remove(uf)`) and
  every chat session (`chat.project_id = None`), then deletes only the
  `UserProject` row. No `UserFile` row, blob, or index entry is touched; the
  files fall back to being ordinary unassociated files, still owned by the
  user and still indexed exactly as before. A project delete can never orphan
  a blob or a chunk, but it also never cleans one up: the files persist as
  "recent" files until the user deletes them individually.

### 4.8 Token accounting

`db/projects.py:get_project_token_count` sums `UserFile.token_count` over
every file joined to the project (`UserFile.projects.any(id=project_id)`),
served by `GET /user/projects/{project_id}/token-count` and
`GET /user/projects/session/{chat_session_id}/token-count`. `UserFile.token_count`
itself is computed at upload time (or recomputed on indexing) by
[[file-store-and-user-files]] §4.5; this component only aggregates it.

The frontend (`web/src/views/AppPage.tsx`, `projectContextTokenCount` state,
consumed by `ProjectContextPanel`) compares this sum against
`availableContextTokens`, which comes from a **separate** calculation,
`chat_backend.py:_get_available_tokens_for_persona` (served by
`GET /chat/available-context-tokens/{session_id}`, owned by
[[core-chat-loop]]/[[context-assembly]]). That function estimates
`model_max_input_tokens - system_and_agent_prompt_tokens - num_tools * 256 -
2000`, a rough headroom estimate for the UI. **This is not the same formula as
the actual inline/retrieval decision** in §4.2, which applies the 60% ceiling
against `reserved_token_count` from `calculate_reserved_tokens`. The UI's
"project exceeds context" message is therefore advisory: it can disagree at
the margin with which path a given turn actually takes. See §9.

---

## 5. Contracts and invariants

1. **Project files must never be silently dropped from context.** Per
   [[context-assembly]] contract 3, only user-uploaded chat attachments may
   drift out under truncation; a project file that fits in context stays for
   the life of the turn and every subsequent turn. A change that lets a
   project file compete with chat history for truncation space breaks this.
2. **The inline and retrieval paths must agree on file identity.** The inline
   path cites `UserFile.id`; the retrieval path indexes the same id
   ([[file-store-and-user-files]] contract 3). A project crossing the
   threshold mid-conversation (by growing, or by the user switching to a
   smaller-context model) must not break citation resolution across that
   boundary.
3. **A custom persona fully supersedes project instructions and project
   files**, verified in both `chat_utils.py:get_custom_agent_prompt` and
   `process_message.py:resolve_context_user_files`. Any new code path that
   reads project state for a turn must check `persona.id != DEFAULT_PERSONA_ID`
   the same way, or it will leak project content into a custom-agent turn that
   is supposed to be fully agent-scoped.
4. **Unlinking or deleting a project must not leave a stale project scope on
   an indexed chunk.** `project_sync_user_file_impl` must run to completion
   (or be retried) after any `Project__UserFile` change, or a chunk's stored
   `project_ids` will disagree with the join table and either over- or
   under-scope search.
5. **Removing a file from a project is not the same operation as deleting the
   file**, and the API enforces the ordering: `delete_user_file` refuses while
   any `Project__UserFile` or `Persona__UserFile` row exists. A caller that
   wants a file gone from everywhere must unlink it from every project and
   persona first.
6. **A project belongs to exactly one user.** Every project query filters on
   `UserProject.user_id == user_id` or, in no-auth mode, allows any project to
   resolve by id alone (`db/projects.py:check_project_ownership`). There is no
   sharing path; see §9.
7. **The token count shown to the user is an approximation, not the ceiling
   used to route a turn.** `get_project_token_count`'s sum and the UI's
   `availableContextTokens` estimate are computed independently of
   `extract_context_files`'s actual 60%-ceiling comparison. Do not treat the
   UI number as proof of which path a turn will take.

---

## 6. Relationships

**Depends on**
- [[file-store-and-user-files]]: owns the blob store, upload, extraction,
  token counting, the storage side of both consumption paths, and file
  deletion. This component supplies only the project scoping around those
  files.
- [[context-assembly]]: owns the exact prompt position, movement, and
  truncation-immunity of the injected project message, and the reasoning
  behind never dropping it.
- [[indexing-pipeline]]: `UserFileIndexingAdapter` runs the shared indexing
  pipeline for project files.
- [[internal-search]]: `project_id_filter` composition and how the search
  tool is gated on/off for a project turn.
- [[agents-personas]]: persona precedence over project instructions and
  files; `Persona__UserFile` is the parallel join this component's
  `Project__UserFile` sits next to.
- [[chat-persistence]]: `ChatSession.project_id` is a column on a table that
  component owns.
- [[access-control]]: project ownership is a strict single-user check; no
  ACL model applies to a project itself.

**Depended on by**
- [[core-chat-loop]]: `build_chat_turn` calls `resolve_context_user_files` and
  `extract_context_files` every turn to decide what a project contributes.
- [[chat-frontend]]: `web/src/lib/projects/svc.ts` and `providers.tsx` are the
  sole client for every project and project-file endpoint; `AppPage.tsx`
  reads `useActiveProject` to gate deep research and to render
  `ProjectContextPanel` / `ProjectChatSessionList`.

---

## 7. Blast radius

| If your change… | Also check |
|---|---|
| changes the inline threshold (the 60% ceiling or `reserved_token_count`) | [[context-assembly]] §4.8's reservation ordering; re-verify a project just below the old ceiling does not silently flip to retrieval-only for existing users without a status change they can see |
| changes project file indexing (`UserFileIndexingAdapter`, `PROCESS_SINGLE_USER_FILE`, project sync) | [[indexing-pipeline]], [[internal-search]]'s `project_id_filter` composition, and citation resolution across the inline/retrieval boundary (contract 2) |
| changes instruction precedence (`get_custom_agent_prompt`, `resolve_context_user_files`) | [[agents-personas]]; re-verify the two independent implementations of the precedence rule (prompt resolution and file resolution) still agree, since one changing without the other reintroduces a project leak into custom-agent turns |
| changes deletion or unlinking (`delete_project`, `delete_user_file`, `unlink_user_file_from_project`) | [[file-store-and-user-files]] contract 4; re-verify a project delete still never touches a `UserFile` row, and an unlink still triggers `project_sync_user_file_impl` rather than leaving `needs_project_sync=True` unresolved |
| adds a project-level setting (sharing, a token cap, a new instruction field) | §5 contract 6: there is currently no sharing model at all; decide explicitly whether the new setting is per-user or introduces the first multi-user project state |
| changes how the frontend resolves the active project (`useActiveProject`, `PARAMS_TO_SKIP`) | `AppPage.tsx`'s deep-research gate, which depends on `activeProject === null`; a resolution bug here can silently enable or disable deep research for the wrong sessions |

---

## 8. How to verify a change

### Tests

```bash
cd backend && uv run pytest tests/unit -k "projects_file_utils or projects_upload_task or user_file_project_sync"
uv run --env-file .vscode/.env pytest backend/tests/integration/tests/projects
cd web && bun run playwright chat/folded_projects_popover.spec.ts chat/project_files_visual_regression.spec.ts
```

`backend/tests/integration/tests/projects/test_projects.py` and
`backend/tests/integration/common_utils/managers/project.py` are the
project-specific integration surface; prefer extending these over new unit
tests. See `backend/AGENTS.md` for the authoritative commands.

### Manual reproduction

1. Confirm services are up: `tail -f backend/log/api_server_debug.log` and
   `backend/log/user_file_processing_debug.log`.
2. Sign in at `http://localhost:3000` as `admin_user@example.com` /
   `TestPassword123!`.
3. Create a project, attach a small text file (well under the active model's
   context window), and set project instructions. Ask a question that depends
   on both. Confirm the instructions are followed and the file's content
   answers correctly without a search tool call.
4. Add enough additional file content to push the project over the 60%
   ceiling for the active model. Confirm the new file's status moves
   `PROCESSING` → `COMPLETED` (`GET /user/projects/file/statuses`), and that a
   question depending on it now triggers an internal search tool call instead
   of being answered from raw context.
5. Attach a custom agent to the chat and ask a question the project
   instructions would normally answer. Confirm the agent's own instructions
   win and the project's instructions have no visible effect.
6. Unlink the small file from the project. Confirm it still appears under
   "recent" files (unassociated), and that a follow-up question scoped to the
   project no longer surfaces content from it.
7. Delete the project. Confirm its files still exist as recent files and are
   not re-indexed or re-deleted as a side effect.

### What "working" looks like

- A project below the threshold answers from context with no tool call; a
  project above it triggers a visible search tool call, and both answers cite
  correctly.
- A custom agent attached to a project-scoped chat never reflects the
  project's instructions or files.
- Unlinking or deleting never removes a `UserFile`, its blob, or leaves an
  index entry still scoped to a project it was removed from.

---

## 9. Footguns

- **A custom persona fully supersedes the project.** Attaching a custom agent
  to a chat inside a project silently drops the project's instructions and
  files from that turn, with no indication in the UI that this happened. This
  is intentional (`chat_utils.py:get_custom_agent_prompt`,
  `process_message.py:resolve_context_user_files`), not a bug, but it is the
  single most surprising behavior in this component.
- **The token count shown in the project context panel is not the number the
  inline/retrieval decision actually uses.** `get_project_token_count`'s sum
  compares against a rough UI estimate
  (`chat_backend.py:_get_available_tokens_for_persona`), while the real
  routing decision applies a 60% ceiling to a different reserved-token
  calculation (§4.8). Do not use the UI's "exceeds context" message as a
  substitute for checking `extract_context_files` directly when debugging
  which path a project actually took.
- **Deleting a project deletes nothing but the `UserProject` row and the
  join.** Every file survives as an ordinary unassociated file, still fully
  indexed. If you expect "delete project" to reclaim storage or purge search
  results, it does not; the user must delete files individually.
- **Unlinking a file from a project does not remove its chunks; it
  re-stamps their project scoping via a metadata-only sync.** A stale
  `needs_project_sync=True` (a failed or delayed `PROCESS_SINGLE_USER_FILE_PROJECT_SYNC`
  task) means the chunk still carries the old project id and can keep
  answering questions scoped to a project the user thought they removed it
  from. Check `UserFile.needs_project_sync` and `last_project_sync_at` when
  debugging a file that "won't leave" a project's search results.
- **Deep research is unconditionally disabled for any chat resolved into a
  project** (`AppPage.tsx`'s `deepResearchEnabledForCurrentWorkflow` gate). A
  user who expects deep research to "just work" inside a project chat is
  hitting this gate, not a bug in the deep research flow itself.
- **Incognito uploads never join a project, even when a `project_id` is
  passed** ([[file-store-and-user-files]] §9). An incognito attachment
  missing from a project's file list is by design.
- **There is no sharing model for projects at all.** Every project query is
  scoped to a single `user_id` (`check_project_ownership`); there is no
  concept of a shared or team project. Do not assume one exists when
  designing a feature that touches project visibility.
