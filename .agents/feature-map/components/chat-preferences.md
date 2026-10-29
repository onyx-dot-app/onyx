# Chat Preferences

> Per-user preferences that reach the prompt (profile, language, memories) and
> prompt shortcuts, plus the workspace `Settings` store that the admin Chat
> Preferences page and other admin pages edit.

**Verified against:** `6bac4e012f` (2026-10-29)
**Edition:** CE. Search Mode and the LLM gateway switch need Business, and
chat retention needs Enterprise. The settings API enforces these tiers.

---

## User experience

- **A user**, in Settings, enters a name, a role and free-text preferences
  ("I prefer short answers"). The next message in any chat, including the open
  one, uses them. Nobody else sees them.
- **A user** lets the assistant remember facts. With the memory tool on, the
  assistant saves or updates a memory during a chat when it decides to, and the
  user sees a memory event in the answer. The user can edit or delete memories
  in Settings. When the tool adds a memory past the cap, it deletes the oldest.
- **A user** can turn off "reference memories". Saved memories then stay out
  of the prompt, but the memory tool can still write them. To stop new
  memories, the user turns off the memory tool.
- **A user** saves prompt shortcuts and inserts them into the message box. They
  can hide a shared shortcut for themselves.
- **A user** picks a UI and answer language, or follows the workspace default.
- **An admin**, at Admin > Chat Preferences, sets workspace chat options. These
  include the team name and context that every prompt includes, the default
  language, the default assistant's system prompt and built-in tools, and the
  chat naming and search selection models. A change applies to every user on
  their next request.
- **An admin who sets a paid option below its tier** gets a 402 and the stored
  value does not change.
- **In an incognito chat**, a memory request fails openly. The model is told
  that nothing was saved, and it tells the user.

---

## Scope

This component owns:
- the per-user preference columns and their writers, and how they reach the
  prompt context each turn;
- memories and the memory tool's write path;
- input prompts (shortcuts);
- the workspace `Settings` store: the stored record, its read path with env
  overrides, the partial admin PATCH under the write lock, and the public read.
  A feature that adds a field owns what the field means; this component owns
  how the field is stored, read and written.

It does not own:
- [[context-assembly]]: the order and wording of the prompt sections.
- [[agents-personas]]: the default assistant row and the
  `/admin/default-assistant` API.
- [[editions-and-gating]]: the tier rules for paid `Settings` fields, and the
  `tier` and `ee_features_enabled` values on the settings read.
- [[billing]]: the license status that the EE settings read applies.
- [[llm-providers]]: how the chat naming and search selection models resolve,
  and the personal default model string.
- [[tools-framework]]: why the memory tool skips `allowed_tool_ids`.
- [[auth-and-identity]]: the user routes, the IdP profile snapshot, and the
  meaning of `invite_only_enabled` and `anonymous_user_enabled`.
- [[plugins]]: Default Chat selection of MCP and OpenAPI tools.

---

## Architecture

**From setting to prompt.** `db/memory.py:get_memories` builds one
`UserMemoryContext` per turn, called from
`chat/process_message.py:prepare_chat_turn` ([[core-chat-loop]]). Nothing is
cached on the chat session, so a change applies on the next message. A memory
that the tool saves during a turn reaches the prompt on the next turn.

Language falls back from `User.language` to `Settings.default_language` through
`server/settings/store.py:resolve_user_language`.
`server/manage/users.py:set_locale_cookie` copies the resolved language into
the `NEXT_LOCALE` cookie, so the UI and the answers use the same language.
`chat/prompt_utils.py:build_chat_prompt` substitutes `{{user.<key>}}`
placeholders into the agent, project and task prompts on each step, and
`prepare_chat_turn` substitutes them before it reserves tokens. Name, role and email never overwrite an
IdP field with the same key. [[context-assembly]] owns the prompt section
where each value lands.

**Memory write path.**
```
tool_constructor.py: user.enable_memory_tool -> MemoryTool in every turn
MemoryTool._run                              tools/tool_implementations/memory/memory_tool.py
  incognito record mode set? -> error result to the model, nothing saved
  no user id?                -> error result, nothing saved
  process_memory_update      -> decides add or replace (LLM call, no DB write)
  index_to_replace?          -> db/memory.py:update_memory_at_index
       else                  -> db/memory.py:add_memory (drops the oldest past the cap)
  MemoryUpdated details      -> live packet and replay
```

**Two memory switches.** `use_memories` is a read switch.
`chat/process_message.py:prepare_chat_turn` passes the full context to the
run, so the memory tool can still see and change memories, and uses
`without_memories()` only for the token reservation.
`chat/execution.py:create_chat_agent` passes `user.use_memories` as
`inject_memories_in_prompt`; `chat/prompt_utils.py:build_chat_prompt` and
`tools/tool_implementations/search/search_tool.py:SearchTool._run` strip
memories when it is false.
`enable_memory_tool` is the write switch.

**Input prompts.** A user creates only private prompts (`POST /input_prompt`
sets `is_public=False`). No route creates a public prompt. The admin route can
only delete one. `POST /input_prompt/{id}/hide` adds an `InputPrompt__User` row
with `disabled=True`, and `fetch_input_prompts_by_user` excludes it for that
user. A shortcut is message text. It never enters the prompt by itself.

**The workspace `Settings` store.** One `Settings` record per tenant lives in
the key-value store, so a new field needs no migration.
`server/settings/store.py:load_settings` validates the stored record, then
applies env overrides and clamps, and reads `anonymous_user_enabled` from the
cache, not from the record.
`backend/onyx/server/settings/api.py:admin_patch_settings` holds `settings_write_lock`, loads with `raise_on_error=True`, merges only the
fields the request sent, applies the tier checks, stores, and returns a fresh
read. `backend/onyx/server/settings/api.py:fetch_settings` returns the record
plus computed values to every user and to anonymous visitors. Several admin
pages write the record; find them with
`git grep -ln "updateAdminSettings\|/api/admin/settings" web/src`. Many backend
paths read it; find them with `git grep -n load_settings backend`.

---

## Contracts and traps

1. `use-memories-read-only` **`use_memories=False` does not stop memory
   writes.** Only `enable_memory_tool` does. A user who asks Onyx to stop
   remembering must turn off the tool. Keep the two flags separate in the UI
   and in the turn code (`inject_memories_in_prompt`).
2. `memory-tool-ignores-tool-choice` **The memory tool ignores per-message tool
   choices.** A user who turns off every tool for one message still has the
   memory tool while `enable_memory_tool` is on
   (`tools/tool_constructor.py:construct_tools`, [[tools-framework]]).
3. `memory-update-by-position` **Memory updates address a position, not an
   id.** `db/memory.py:update_memory_at_index` uses the 0-based index in `id`
   order, the same order as `get_memories`. A change to either order makes the
   model replace the wrong memory. `get_memories` skips rows with empty text
   and the update counts them, so an empty row shifts every later index. The
   web drops empty memories before it saves; `PATCH /user/personalization`
   does not.
4. `no-memory-write-in-incognito` **Never write a memory in incognito.** The
   check in `tools/tool_implementations/memory/memory_tool.py:MemoryTool._run`
   must run before `add_memory` or `update_memory_at_index`. It reads the
   record mode from a context variable that `chat/execution.py:start_chat_turn`
   sets, so it works only in threads that copy the turn's context. A new memory
   writer needs the same check and the explicit error result, so the model
   does not claim it saved something.
5. `personalization-replaces-memory-set` **A personalization save replaces the
   whole memory set.** `PATCH /user/personalization` with a `memories` list
   deletes every row whose id is not in the list
   (`db/user_preferences.py:update_user_personalization`).
   `web/src/hooks/useUserPersonalization.ts` sends the full list on every save,
   even a toggle change.
6. `prompt-section-explicit-position` **A new prompt section needs an explicit
   position.** Add it in `chat/prompt_utils.py:_build_user_specific_section` at
   a chosen place, not at the end, and run a prompt eval ([[context-assembly]]).
7. `settings-fields-public` **Every `Settings` field is public.**
   `backend/onyx/server/settings/api.py:fetch_settings` returns the whole
   `UserSettings` to every user and to anonymous visitors. It hides only
   `craft_instructions`, and only from anonymous callers ([[craft-admin]]). Put
   an admin-only or secret value in its own store, or strip it in
   `fetch_settings`.
8. `settings-write-under-lock` **Every read-modify-write of `Settings` holds the
   lock and fails closed.** A writer outside the admin PATCH must wrap the load
   and the store in `server/settings/store.py:settings_write_lock` and load with
   `raise_on_error=True`, as `server/settings/store.py:clear_chat_retention`
   does. Without the lock, two writers drop each other's field. Without
   `raise_on_error`, a read error stores defaults over every field, including
   access-control fields such as `invite_only_enabled`.
9. `admin-page-sends-whole-settings` **The Chat Preferences page sends the whole
   settings object.** The server merges only the fields it receives, under the
   lock. But `saveSettings` in `web/src/views/admin/ChatPreferencesPage.tsx`
   spreads its copy of every field into each PATCH. A stale page can revert
   another admin's change. `web/src/lib/settings/svc.ts:updateAdminSettings`
   sends only the changed fields; use it in new pages.
10. `settings-record-validates-whole` **One invalid field resets the whole
    record on read.** `load_settings` validates the stored record as one
    `Settings` model. If a field's type or constraint changes so that an old
    stored value fails validation, readers without `raise_on_error` get every field
    at its default, and the admin PATCH fails. Keep a changed field able to
    read its old stored values. Some defaults turn a feature on. A reader that
    gates a costly or unsafe path must load with `raise_on_error=True` and fall
    back to off on error, as
    `configs/llm_configs.py:get_image_extraction_and_analysis_enabled` does.
    The default for image extraction is on. A failed read in a test without a
    database would otherwise start image extraction and its storage writes.
11. `settings-field-removal-breaks-clients` **Do not remove a `Settings` field
    that external clients still send or read.** Older Terraform provider
    releases send `image_analysis_max_size_mb` and read
    `opensearch_indexing_enabled`. The model keeps both, unused, so that those
    clients keep working. Remove such a field only after a provider release
    without it.

---

## Decisions

- **Memories are written without a confirmation.** The tool runs during the
  turn and the answer shows the event. The cap (`MAX_MEMORIES_PER_USER`) keeps
  the prompt section small.
- **No public prompt creation.** Publishing to everyone needs its own
  authorization decision. `insert_input_prompt(is_public=True)` exists, but no
  route calls it that way.
- **The organization profile follows the IdP.** Users cannot edit it. A change
  in the IdP applies at the next login capture.
- **Workspace settings are one key-value record, not a table.** A new option
  needs no migration. The cost is that the whole record is read and written
  together, which is why [[#settings-write-under-lock]] and
  [[#settings-record-validates-whole]] exist.

---

## Known issues

- **A stale settings page can delete a new memory**
  ([[#personalization-replaces-memory-set]]). A memory that the tool saved
  after the page loaded its user data is not in the list, so the next save
  deletes it.
- **`anonymous_user_enabled` can turn itself off.** `load_settings` reads it
  from a cache key with a 30-day TTL, not from the stored record. Only
  `store_settings` refreshes the key. When it expires, the read writes `0` and
  anonymous access is off until the next settings save.
- **The page cannot set the default assistant's task prompt.** The
  default-assistant API takes only the system prompt and tool ids. The trailing
  reminder is a persona field ([[agents-personas]]).
- **Incognito availability is not on this page.** It is a security setting
  (`chat/incognito.py:incognito_allowed_for_user`), which surprises people who
  look for it here. Incognito is also unavailable, whatever the setting, when
  the cache backend is not Redis
  (`chat/incognito_context.py:incognito_context_available`), and anonymous users
  can never start it ([[chat-persistence]]).

---

## Dependencies

- [[context-assembly]]: section order and wording.
- [[agents-personas]]: the default assistant's prompt and tools.
- [[editions-and-gating]]: tier checks on paid `Settings` fields.
- [[auth-and-identity]]: user routes and the IdP profile.
- [[tools-framework]]: memory tool construction.

---

## Recipes

- `new-user-setting` **A user setting that reaches the prompt.** Copy `personal_role`: list its
  path with `git grep -n personal_role backend/onyx`. Add the `User` column and
  a writer in `db/user_preferences.py`, expose it in `server/manage/users.py`,
  carry it in `UserMemoryContext`, and place it in
  `_build_user_specific_section` ([[#prompt-section-explicit-position]]).
- `new-workspace-option` **A workspace option.** Copy `auto_detect_search_filters`: list its readers
  and writers with `git grep -n auto_detect_search_filters`. Add the field to
  `server/settings/models.py:Settings` with a default, and read it with
  `load_settings()` at the point of use. Add the same field to
  `web/src/lib/settings/types.ts:Settings`, the web copy of the model. Every
  user can read it ([[#settings-fields-public]]). For an admin-only value,
  clear it for non-admins in
  `backend/onyx/server/settings/api.py:fetch_settings`, as that function clears
  `craft_instructions` for anonymous callers, or keep it out of `Settings` in a store behind an
  admin route, such as `server/security/store.py:get_security_settings`
  ([[auth-and-identity]]).
- `setup-memories` **Set up memories for a test.** Turn on the memory tool for the user, then
  ask the assistant to remember something, or write rows with
  `db/memory.py:add_memory`. Check the `memory` table for the result.

---

## Verification

- Unit tests: the prompt tests in `backend/tests/unit/onyx/chat/`, the memory
  tool tests in `backend/tests/unit/tools/`, and the settings tests in
  `backend/tests/unit/onyx/server/settings/` and `backend/tests/unit/onyx/server/`.
- External dependency tests: the memory tool tests in
  `backend/tests/external_dependency_unit/tools/`.
- Integration tests: `backend/tests/integration/tests/personalization/`.
- No integration test covers input prompt behaviour or
  `auto_detect_search_filters`.
- By hand: set a name and a preference, then ask "what do you know about me".
  Turn off reference memories and confirm that the next answer ignores them.
  Repeat a memory request in an incognito chat and confirm that nothing is
  saved.
