# Projects

> A named set of files and instructions that one user keeps across chat sessions. This component owns the project row, its links to files and sessions, and the per-turn choice between inline files and retrieval.

**Verified against:** `73e0ae3c31` (2026-10-28)
**Edition:** CE

---

## User experience

- **A user** creates a project, writes instructions, and adds files. Each chat
  started in the project, or moved into it, gets the instructions and files.
  The user does not upload them again.
- **Small projects** behave as if the files were pasted into every message.
  The default assistant answers from them with no search. A custom agent
  keeps its own search setting.
- **Large projects** become searchable. The model searches the project files
  and cites the parts it finds. The user does not choose the mode; the total
  size of the files against the model's context decides it on each turn.
- **The project panel** shows a token count and a warning when the files
  exceed the available context. The warning is an estimate
  ([[#token-warning-disagrees]]).
- **Custom agents in a project** get both sets of files and both sets of
  instructions. Agent instructions win when the two conflict.
- **Removing a file** from the project, or deleting the project, keeps the
  file in the user's recent files. To delete a file that is still in a project
  or on an agent, the user must remove it from each one first. The delete call
  returns the project and agent names instead of deleting.
- **Deep research** is off in project chats. The UI turns it off, and the
  backend rejects a deep research request for a project session.

When it fails: a file that is still processing, or a sync that is late, can
make answers miss or include a file. The user sees no error
([[#sync-after-link-change]]).

---

## Scope

This component owns the project row, the project-to-file links, moving chat
sessions into and out of a project, project instructions, the per-turn choice
of context files, and the decision whether they go inline or through
retrieval.

Neighbours own the rest:
- [[file-store-and-user-files]]: upload, extraction, token counts, indexing,
  file deletion, and the project and agent metadata sync on chunks. The upload
  and file routes sit in the projects API module but belong there.
- [[context-assembly]]: where the project message sits in the prompt, and why
  it is never truncated. It shares the chat file helpers with this
  component.
- [[internal-search]]: how `project_id_filter` and `persona_id_filter` filter
  retrieval.
- [[agents-personas]]: agent files and instructions.
- [[chat-persistence]]: the `ChatSession` table.

---

## Architecture

```
build_chat_turn                          chat/process_message.py
  resolve_context_user_files             project files + custom agent files, deduped by UserFile.id
  get_custom_agent_prompt                chat/chat_utils.py: project + agent instructions
  calculate_reserved_tokens
  extract_context_files                  all-or-nothing fit check
     fits    -> file_texts, image_files  -> project message (context-assembly)
     too big -> use_as_search_filter     -> no file text in the prompt
  determine_search_params                project_id_filter, persona_id_filter, search usage
```

**The fit check.** `extract_context_files` sums `token_count` for every file
that is not metadata-only, such as spreadsheets. It compares the sum with
`(context window - reserved tokens) * 0.6`. The window is the smallest across
the models of a multi-model turn. Below the limit, every file goes inline.
At or above it, no file goes inline, and search uses the files as a filter.
The 60% factor covers the error of the generic tokenizer used at upload, and
leaves room for chat history.

**Search usage.** `determine_search_params` sets the filters only when files
overflow. For the default assistant in a project, search is on when files
overflow, and off when the files fit or the project has no files. A custom
agent keeps its own search setting. Overflow adds the project and agent
filters to the agent's own knowledge; it does not add a tool the agent lacks.
`build_chat_turn` clears a forced search tool when search is off. Inside
`SearchTool.run`, an inferred source scope gets `USER_FILE` added back when
project or agent files need retrieval, unless the user's own source filter
leaves it out. A project-only search (`project_id_filter` set,
`persona_id_filter` not set) ignores the user's selected filters
(`tools/tool_implementations/search/search_tool.py:SearchTool._is_project_only_search`).

**Files are indexed at upload, not on overflow.** Each project file is indexed
when it is uploaded, whatever the project size. Upload marks a spreadsheet
over the token limit `SKIPPED`, and it is not indexed. A project that grows
past the limit, or a switch to a model with a smaller context, needs no new
indexing. Chunks carry the ids of the projects that hold the file. When
`DISABLE_VECTOR_DB` is set, overflow files are listed for `FileReaderTool`
instead. With the vector DB on, only the metadata-only overflow files get tool
metadata.

**Link and unlink.** `link_user_file_to_project` and
`unlink_user_file_from_project` change the join row, set
`UserFile.needs_project_sync`, and start a sync that rewrites the chunk
`project_ids` in place ([[file-store-and-user-files]]).

---

## Contracts and traps

1. `one-file-selection` **Choose context files in one place.**
   `chat/process_message.py:build_chat_turn` calls
   `chat/files.py:resolve_context_user_files` once, and the result
   feeds prompt loading, the `read_file` id list and the Python tool's file
   staging. A path that collects project or agent files on its own can drop a
   source or count a file twice.
2. `never-truncated` **Project files are never dropped by truncation.** Below
   the limit they stay in context for every turn ([[context-assembly]]). A
   change that lets them compete with chat history for space breaks the
   product promise.
3. `shared-file-identity` **Inline and retrieved files share one identity.**
   The inline message cites `UserFile.id`, and the index stores the document
   under `str(UserFile.id)`. A project that crosses the limit between turns
   must still resolve old citations.
4. `token-warning-disagrees` **The UI token warning and the fit check
   disagree.** `db/projects.py:get_project_token_count` sums every file,
   including spreadsheets. The panel compares it with
   `server/query_and_chat/chat_backend.py:_get_available_tokens_for_persona`,
   which subtracts a fixed estimate for tools and input. The real check
   applies the 60% factor to a different reservation and skips metadata-only
   files. Do not use the warning to decide which path a turn took.
5. `sync-after-link-change` **A sync must finish after each link change.** If
   `background/celery/tasks/user_file_processing/tasks.py:project_sync_user_file_impl`
   does not run, chunks keep the old
   `project_ids`, and search in the old project still finds the file. A beat
   task retries files that are `COMPLETED` and still need a sync.
6. `single-user-ownership` **Ownership is one user.** Every project route
   filters on `UserProject.user_id`. `db/projects.py:check_project_ownership` admits any
   project when the user id is null (no-auth mode). Check ownership before
   each new read.
7. `incognito-never-joins` **Incognito uploads never join a project.**
   `db/projects.py:create_user_files` skips the join row when an incognito session id is set,
   even with a `project_id`.
8. `client-finds-project-by-session` **The web client finds the project of an
   open chat by search.** The URL drops `projectId` once a chat opens.
   `web/src/lib/projects/hooks.ts:useActiveProject` finds the project whose
   `chat_sessions` holds the chat. The deep research gate uses it. A gate that
   reads only the URL misses project chats.

---

## Decisions

- **Agent instructions win over project instructions.**
  `get_custom_agent_prompt` labels both and tells the model to follow the
  agent on a conflict. When the agent replaces the base system prompt, only
  the project instructions go in this message, so the agent text is not sent
  twice.
- **No deep research in projects.** `chat/process_message.py` raises for a
  project session, and `web/src/views/AppPage.tsx` turns it off when a project
  is active.

---

## Known issues

- **Projects cannot be shared.** No share table or team project exists. A
  feature that needs a shared project must add the first multi-user model.
- **Deleting a project does not sync chunks.**
  `server/features/projects/api.py:delete_project` removes the
  join rows without setting `needs_project_sync`, so the chunks keep the
  deleted project id. Project ids are not reused, so search is not affected,
  but the metadata is stale.
- **Deleting a project frees no storage.** The files stay, indexed, until the
  user deletes each one.

---

## Dependencies

- [[file-store-and-user-files]]: file rows, token counts, indexing and sync.
- [[context-assembly]]: renders and places the project message.
- [[internal-search]]: applies the project and agent filters.
- [[agents-personas]]: agent files and instructions.
- [[chat-persistence]]: `ChatSession.project_id`.

---

## Recipes

- `add-context-file-source` **Add a new source of context files**, such as
  files from another container. Extend `resolve_context_user_files`, which combines project files
  with custom agent files, so that every consumer gets the new source
  ([[#one-file-selection]]). If the files must be searchable on overflow,
  extend `determine_search_params` and the filter in [[internal-search]].
- `investigate-project-file-answer` **Investigate "the answer ignored (or used) a project file".** Find which
  path the turn took: sum `UserFile.token_count` for the project's files that
  are not metadata-only and compare it with the fit limit
  ([[#token-warning-disagrees]]). On the inline path, check that the file is
  `COMPLETED` and has text. On the retrieval path, check the file's chunks for
  the project id. A removed file that search still finds means a late sync:
  check `needs_project_sync` and `last_project_sync_at` on the `user_file`
  row ([[#sync-after-link-change]]).
- `test-project-setup` **Set up a project for a test.** Use the integration manager
  `backend/tests/integration/common_utils/managers/project.py`. For the
  inline path, upload one small text file. For the retrieval path, upload
  files until the sum passes the limit, or pick a model with a small context
  window.

---

## Verification

- `backend/tests/integration/tests/projects/` covers create, upload, link and
  delete.
- `backend/tests/external_dependency_unit/server/features/projects/` covers
  ownership when a chat moves between projects.
- By hand: add a small file and check that the answer needs no search. Add
  files until the total passes the limit and check that the answer runs a
  search and cites the file. Remove a file and check that search in the
  project does not find it.
