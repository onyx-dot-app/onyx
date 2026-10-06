# Chat Preferences

> The configuration surface that feeds the prompt without touching an agent: the
> admin chat-preferences panel, per-user settings, input prompts, and memories.
> [[context-assembly]] owns how this content is assembled into the final prompt;
> this document owns where each piece is set, stored, and how it reaches that
> assembly step.

**Verified against:** `268e4d5a3d` (2026-10-05)
**Domain:** core-loop
**Edition:** CE, with tier gates (Business/Enterprise) on a few admin toggles
**Owns:**
`backend/onyx/db/user_preferences.py`, `backend/onyx/db/input_prompt.py`,
`backend/onyx/db/memory.py`, `backend/onyx/server/features/input_prompt/`,
`backend/onyx/server/features/default_assistant/`, `backend/onyx/server/settings/`,
`web/src/views/admin/ChatPreferencesPage.tsx`, `web/src/views/SettingsPage.tsx`,
`web/src/hooks/useUserPersonalization.ts`

**Read first:** [[context-assembly]] §4.1, which names
`_build_user_information_section` and the order it assembles: Basic Information,
Organization Profile, Team Information, Language, User Preferences, Memories.
This document works backwards from that function to the surfaces that set each
piece.

---

## 1. What the user experiences

**An admin**, at `/admin/chat-preferences`, sets workspace-wide defaults: which
tools the default agent may use, its system prompt, a team name and description
that gets folded into every prompt, whether search auto-detects filters,
whether multi-model chat and deep research are on, retention and query-history
policy, and file-size limits. Nothing here is per-user; every toggle applies to
every chat that uses the default agent (a persona picked by the user still
carries its own prompt and tools, see [[agents-personas]]).

**A user**, at `/app/settings/chat-preferences` and the neighboring "General"
tab, sets things that describe themselves to the model: their preferred name
and role, free-text preferences ("I prefer concise answers"), whether the
assistant should reference or update memories about them, saved prompt
snippets ("shortcuts") they can insert into the message box, their default
model, temperature, reasoning effort, UI language, and app mode. None of this
is visible to other users. It changes what the model is told about *this*
person, not what the workspace's agent is allowed to do.

The user cannot loosen anything the admin locked down (for example, a disabled
built-in tool stays disabled regardless of a user's own preference), but they
can add information (memories, preferences, name) that an admin never sees or
controls.

---

## 2. Surfaces

### HTTP endpoints

| Method | Path | Handler | Scope |
|---|---|---|---|
| PATCH | `/admin/settings` | `backend/onyx/server/settings/api.py` | Admin. Workspace `Settings` blob (company name/description, `auto_detect_search_filters`, `multi_model_chat_enabled`, `deep_research_enabled`, `search_ui_enabled`, retention, query-history policy, file limits, `anonymous_user_enabled`, `disable_default_assistant`). |
| GET | `/settings` | `backend/onyx/server/settings/api.py` | Public read of the same blob, consumed by both admin and app UI. |
| GET `/admin/default-assistant/configuration`, PATCH `/admin/default-assistant` | `backend/onyx/server/features/default_assistant/api.py:get_default_assistant_configuration`, `update_default_assistant` | Admin. Default persona's `tool_ids` and `system_prompt`. |
| POST/DELETE | `/admin/llm/default-chat-naming` | `backend/onyx/server/manage/llm/api.py` | Admin. Sets or clears the model used to auto-name new chats; unrelated to prompt content but lives on this page. |
| PATCH | `/user/personalization` | `backend/onyx/server/manage/users.py:update_user_personalization_api` | User. `personal_name`, `personal_role`, `use_memories`, `enable_memory_tool`, `memories`, `user_preferences` in one call. |
| PATCH | `/user/language` | `backend/onyx/server/manage/users.py:update_user_language_api` | User. Also sets the `NEXT_LOCALE` cookie via `set_locale_cookie`. |
| PATCH | `/shortcut-enabled`, `/temperature-override-enabled`, `/temperature-default`, `/reasoning-effort-default`, `/auto-scroll`, `/paste-as-tile`, `/user/theme-preference`, `/user/chat-background`, `/user/default-app-mode`, `/user/default-model` | `backend/onyx/server/manage/users.py` | User. One column each, all in `backend/onyx/db/user_preferences.py`. |
| GET/POST/PATCH/DELETE | `/input_prompt`, `/input_prompt/{id}`, `/input_prompt/{id}/hide` | `backend/onyx/server/features/input_prompt/api.py` (`basic_router`) | User. Create, edit, delete their own shortcuts; `hide` disables a public one for themselves without deleting it. |
| DELETE | `/admin/input_prompt/{id}` | `backend/onyx/server/features/input_prompt/api.py` (`admin_router`) | Admin. Delete a public shortcut. There is no admin *create* endpoint (see §9). |
| GET | `/chat/incognito-availability` | `backend/onyx/server/query_and_chat/chat_backend.py:get_incognito_availability` | Reads `incognito_allowed_for_user`, which composes a **security** setting (`IncognitoAvailability`), not a chat-preferences one. See §9. |

### Environment / tier gates

| Gate | Effect |
|---|---|
| `useTierAtLeast(Tier.BUSINESS)` | Gates the admin "search mode" toggle (`ChatPreferencesPage.tsx`). |
| `useTierAtLeast(Tier.ENTERPRISE)` | Gates the retention-days field. |
| Business/Enterprise checks live in [[editions-and-gating]]; this document does not re-derive them. |

Admin-configured settings can change prompt content. For example, the default
assistant's `system_prompt` is the base prompt (`get_default_base_system_prompt`).
They do not change the assembly template (see [[context-assembly]] §4.1).

---

## 3. Data model

### `User` preference columns (`backend/onyx/db/models.py:User`)

| Column | Type | Read by |
|---|---|---|
| `personal_name`, `personal_role` | `str \| None` | `db/memory.py:get_memories` → `UserInfo.name/role` |
| `use_memories` | `bool`, default `True` | `process_message.py` (strips memories from prompt context if `False`, see §4.3) |
| `enable_memory_tool` | `bool`, default `True` | `tool_constructor.py` (gates injecting `MemoryTool`, see §4.4) |
| `user_preferences` | `Text \| None` | `db/memory.py:get_memories` → `UserMemoryContext.user_preferences` |
| `language` | `str`, default `"en"` | `db/memory.py:supported_language_or_none` → `UserInfo.language` |
| `temperature_default`, `temperature_override_enabled` | `float \| None`, `bool \| None` | LLM call params, not the prompt text |
| `reasoning_effort_default` | `ReasoningEffort \| None` | LLM call params |
| `default_model`, `default_app_mode`, `theme_preference`, `chat_background`, `auto_scroll`, `shortcut_enabled`, `paste_as_tile` | various | UI/session behavior, not the prompt |
| `craft_enabled` | `bool \| None` | Craft gate, [[editions-and-gating]] |
| `hidden_assistants`, `visible_assistants`, `chosen_assistants` | `list[int]` | [[agents-personas]] |

### `Memory` (`backend/onyx/db/models.py:Memory`)

| Column | Notes |
|---|---|
| `id`, `user_id` | FK `user.id`, `ondelete="CASCADE"` |
| `memory_text` | The stored fact |
| `conversation_id`, `message_id` | Nullable provenance fields |
| `created_at`, `updated_at` | |

Capped at `MAX_MEMORIES_PER_USER = 10` (`db/memory.py`); `add_memory` deletes the
oldest row (lowest `id`) before inserting past the cap.

### `InputPrompt` and `InputPrompt__User` (`backend/onyx/db/models.py:InputPrompt`)

| Column | Notes |
|---|---|
| `id`, `prompt`, `content`, `active` | `prompt` is the shortcut name/trigger, `content` the inserted text |
| `is_public` | `True` = visible to every user; `False` = owned by one user |
| `user_id` | Nullable; null for public prompts |
| Unique constraints | `(prompt, user_id)` for user-owned; a partial unique index on `prompt` where `user_id IS NULL` for public prompts |

`InputPrompt__User(input_prompt_id, user_id, disabled)`: per-user override that
hides a prompt (typically a public/seeded one) without deleting the shared row.

### Workspace settings (`backend/onyx/server/settings/models.py:Settings`)

Not a table. A single JSON blob in the key-value store, key `KV_SETTINGS_KEY`
(`backend/onyx/server/settings/store.py:load_settings`, `store_settings`).
Relevant fields: `company_name`, `company_description`,
`auto_detect_search_filters`, `multi_model_chat_enabled`,
`deep_research_enabled`, `search_ui_enabled`, `maximum_chat_retention_days`,
`query_history_type`, `anonymous_user_enabled`, `disable_default_assistant`.
A schema change here is a KV-blob field addition, not a migration; see root
`CLAUDE.md` on avoiding migrations.

---

## 4. How it works

### 4.1 Setting-to-prompt map

Every row is one setting, traced from its UI control through storage to where
[[context-assembly]]'s `_build_user_information_section`
(`backend/onyx/chat/prompt_utils.py`) or `build_system_prompt` places it.

| Setting | Set at | Stored in | Reaches the prompt via |
|---|---|---|---|
| Personal name / role | `web/src/views/SettingsPage.tsx:GeneralSettings` | `User.personal_name`, `User.personal_role` | `db/memory.py:get_memories` → `UserInfo.name/role` → `BASIC_INFORMATION_PROMPT` (§4.2) |
| Organization profile (department, title, city, ...) | Not set by a user; captured from the IdP login snapshot | Directory snapshot read by `auth/login_claims_capture.py:get_idp_profile` | `UserInfo.organization_profile` → `ORGANIZATION_PROFILE_PROMPT` |
| Team name / team context | Admin, `/admin/chat-preferences` ("Team Context" section) | `Settings.company_name`, `Settings.company_description` (KV store) | `prompts/prompt_utils.py:get_company_context` → `TEAM_INFORMATION_PROMPT` |
| Language | User, `GeneralSettings` language selector; `PATCH /user/language` | `User.language` | `db/memory.py:supported_language_or_none` → `UserInfo.language` → `prompt_utils.py:build_language_section` |
| User preferences (free text) | User, `ChatPreferencesSettings` "Personal Preferences" field | `User.user_preferences` | `UserMemoryContext.user_preferences` → `USER_PREFERENCES_PROMPT` |
| Memories | Written automatically by `MemoryTool`; read toggle is user-controlled | `Memory` table | `UserMemoryContext.memories` → `USER_MEMORIES_PROMPT` (only if `user.use_memories`, §4.3) |
| Default agent system prompt | Admin, `/admin/chat-preferences` "System Prompt" modal | `Persona.system_prompt` for the default persona | `prompt_utils.py:get_default_base_system_prompt` → base of `build_system_prompt` |
| Default agent tool set | Admin, `/admin/chat-preferences` tool toggles | `Persona.tools` (default persona) | Gates which per-tool guidance sections `build_system_prompt` appends |
| `auto_detect_search_filters` | Admin, "Auto-detect filters" toggle | `Settings.auto_detect_search_filters` (KV) | Not a prompt section: read directly in `process_message.py` and `server/features/search/api.py` to decide whether a turn runs filter auto-detection at all |
| Reminder text (persona task prompt) | **Not settable on this page.** Owned by [[agents-personas]] (`Persona.task_prompt`), edited per-agent | `Persona.task_prompt` | `prompt_utils.py:build_reminder_message`, placed last by [[context-assembly]] §4.5 |

The last row is a deliberate non-finding: the admin default-assistant modal only
exposes `system_prompt` and `tool_ids` (`DefaultAssistantUpdateRequest`,
`default_assistant/api.py:update_default_assistant`); it does not expose
`task_prompt`. A user or admin who wants to change the trailing reminder must
do it on the agent itself, not from chat-preferences.

### 4.2 Basic information and organization profile

`db/memory.py:get_memories(user, db_session)` builds one `UserMemoryContext`
per turn (called from `process_message.py:build_chat_turn`, owned by
[[core-chat-loop]]). It reads `user.personal_name`, `user.personal_role`,
`user.email` for basic info, and calls
`auth/login_claims_capture.py:get_idp_profile(user.email)` for the
organization profile: a best-effort read of the IdP directory snapshot
captured at login, returned as ordered `{label: value}` pairs plus a
`{{user.<key>}}` placeholder map (`IdpProfileViews`). Neither the admin panel
nor the user settings page can edit the organization profile directly; it
follows the identity provider.

### 4.3 `use_memories`: read-gate, not write-gate

`process_message.py:build_chat_turn` strips memories from the assembled prompt
when `user.use_memories` is `False`, via `user_memory_context.without_memories()`
(`db/memory.py:UserMemoryContext.without_memories`), while keeping name, role,
and preferences intact. The **full** context (including memories) is still
passed into `run_llm_loop` so the `MemoryTool` can still read and update
existing memories mid-turn (`inject_memories_in_prompt=user.use_memories`,
`process_message.py`); disabling the toggle stops memories from being *shown*
to the model, not from being written or read internally.

### 4.4 Memories: write path and the tool bypass

`user.enable_memory_tool` gates whether `tool_constructor.py` injects
`MemoryTool` at all: `if user.enable_memory_tool: ... tool_dict[memory_tool_db_model.id] = [memory_tool]`
(`backend/onyx/tools/tool_constructor.py`). [[tools-framework]] §5 and §9
establish that this injection **bypasses `allowed_tool_ids`**: a user who
disables every other tool for a specific message still gets `MemoryTool` if
`enable_memory_tool` is on. This document does not restate that mechanism; the
consequence that matters here is privacy: **memories are written
automatically, mid-turn, without a per-message confirmation**. They surface in
later prompts via `USER_MEMORIES_PROMPT` while `use_memories` is on. When
`use_memories` is off, `process_message.py` strips them from the prompt context
(`without_memories()`), but the memory tool can still write them.

The actual write happens after the tool call resolves, in
`chat/llm_loop.py` (around the `MemoryToolResponse` handling): a new memory
calls `db/memory.py:add_memory`, an update to an existing one calls
`update_memory_at_index`. Both require `user_memory_context.user_id` to be
set; an incognito turn (see §4.6) skips the write entirely and returns an
explicit refusal string instead
(`"Error: memories cannot be saved from an incognito chat..."`), so the model
tells the user the memory was not saved rather than silently dropping it.

The `MemoryTool` itself only decides **whether** to add or update
(`process_memory_update` in `secondary_llm_flows/memory_update.py`, called
from `memory_tool.py:MemoryTool.run`) and emits a streaming delta; it does not
touch the database directly (`memory_tool.py`'s docstring: "memories are
passed in via override_kwargs").

### 4.5 Input prompts (shortcuts)

Any user can create their own input prompt (`POST /input_prompt`, always
`is_public=False`, `db/input_prompt.py:insert_input_prompt`). There is **no**
route that lets a user or an admin create a public prompt through this API;
`insert_input_prompt(is_public=True, ...)` exists as a function but nothing in
`backend/onyx/server` calls it with `is_public=True`. Public prompts, if any
exist, come from seed data outside this component. An admin's only lever over
existing input prompts is deletion of public ones
(`DELETE /admin/input_prompt/{id}` →
`db/input_prompt.py:remove_public_input_prompt`).

Any user, including one who did not create a public prompt, can hide it for
themselves: `POST /input_prompt/{id}/hide` →
`db/input_prompt.py:disable_input_prompt_for_user`, which upserts an
`InputPrompt__User` row with `disabled=True`. `fetch_input_prompts_by_user`
left-joins that table and excludes rows the caller has disabled
(`db/input_prompt.py`).

Input prompts are inserted into the message compose box by the user; they are
not part of the assembled LLM context. They reach the model only as ordinary
user-message text once sent, so this component has no direct dependency on
[[context-assembly]] for this sub-flow.

### 4.6 Incognito

Incognito is **not** configured on the chat-preferences surfaces. Its
admin-facing on/off switch (`IncognitoAvailability`: `OFF`, `EVERYONE`, `GROUPS`; default `OFF`)
and its record mode (`IncognitoRecordMode`) live in the workspace's security
settings, read by `chat/incognito.py:incognito_allowed_for_user` via
`get_security_settings()`, distinct from `server/settings/models.py:Settings`.
The only surface this component shares with incognito is the availability
check the frontend calls before offering the option:
`GET /chat/incognito-availability` →
`chat_backend.py:get_incognito_availability` →
`incognito.py:incognito_allowed_for_user(user, db_session)`. Once a session is
pinned incognito, `_build_user_information_section` still runs normally; what
changes is persistence, not prompt assembly (see [[context-assembly]] §4.10).
The one incognito interaction this component owns is the memory-write refusal
in §4.4.

---

## 5. Contracts and invariants

1. **A user preference does not override an admin restriction, except for
   `MemoryTool`.** A disabled built-in tool on the default agent (admin,
   `ChatPreferencesPage.tsx` tool toggles) stays disabled for every user. There is
   no per-user "re-enable this tool" path for those tools. `tool_constructor.py`
   injects `MemoryTool` whenever `user.enable_memory_tool` is true, even if the
   default persona's tool configuration omits it (§4.4).
2. **Every setting that reaches the prompt must render deterministically.**
   [[context-assembly]] explains why prompt text position is load-bearing (a
   measured swing from ~30% to ~90% instruction-follow by moving one
   sentence); a new setting added to `_build_user_information_section` must
   pick an explicit position in that ordered list, not append arbitrarily.
3. **Memories are per user and must respect incognito.** `Memory.user_id` is
   never null; `add_memory`/`update_memory_at_index` are never called when
   `get_current_incognito_record_mode() is not None` (§4.4).
4. **Disabling a feature takes effect on the next turn, not only for new
   sessions.** `use_memories`, `enable_memory_tool`, and every admin toggle in
   `Settings` are read fresh per turn (`get_memories`, `load_settings`), not
   cached on the `ChatSession`. A change mid-conversation must be visible on
   the very next message in that same session.
5. **`use_memories=False` hides memories from the prompt, it does not stop
   the write path.** Do not conflate the two; see §4.3.
6. **Public input prompts have no create endpoint in this API surface.** If
   one is added, it needs its own authorization decision (who can publish to
   everyone), not a silent flip of the existing `is_public` field.

---

## 6. Relationships

**Depends on**
- [[context-assembly]]: the assembly order and rules this component's settings
  feed into; `_build_user_information_section`, `build_system_prompt`,
  `select_reminder_text` all live there.
- [[agents-personas]]: the default persona's `system_prompt`, `tool_ids`, and
  `task_prompt`; a non-default persona's own prompt fully supersedes anything
  set here (see [[context-assembly]] §4.2).
- [[tools-framework]]: `MemoryTool` construction and its `allowed_tool_ids`
  bypass; `enable_memory_tool` is this component's half of that story.
- [[auth-and-identity]]: `get_idp_profile` reads the login-time directory
  snapshot that becomes the organization profile.
- [[editions-and-gating]]: tier gates on the admin panel's Business/Enterprise
  toggles.

**Depended on by**
- [[core-chat-loop]]: `build_chat_turn` calls `get_memories` and reads
  `user.use_memories` every turn; `process_message.py` reads
  `auto_detect_search_filters` every turn.
- [[chat-frontend]]: renders both settings surfaces and the shortcut picker in
  the compose box.
- [[chat-persistence]]: memories are written alongside a turn but live in
  their own `Memory` table, not on `ChatMessage`.

---

## 7. Blast radius

| If your change… | Also check |
|---|---|
| adds a new setting that reaches the prompt | Storage (`User` column, KV blob field, or new table), the API endpoint, both UIs (admin and/or `/app/settings/chat-preferences`), `prompt_utils.py:_build_user_information_section` or `build_system_prompt`'s explicit position for it, and an eval per [[context-assembly]] §8 |
| changes memory behavior (`enable_memory_tool`, `use_memories`, `MAX_MEMORIES_PER_USER`, incognito refusal) | `tool_constructor.py`'s injection, `llm_loop.py`'s `MemoryToolResponse` handling, [[tools-framework]]'s bypass documentation, and the incognito refusal path |
| changes a workspace setting (`Settings` fields) | Every reader of `load_settings()` (`process_message.py`, `server/features/search/api.py`, `prompt_utils.py:get_company_context`); a stale cached read after `store_settings` is a common failure mode |
| adds or edits an input prompt field | `InputPrompt`'s unique constraints (user-owned vs. public partial index); `InputPrompt__User` per-user disable state |
| changes the default assistant's tool set or system prompt | [[agents-personas]] (the row this modifies is a `Persona`); every user whose chats use the default agent |

---

## 8. How to verify a change

### Tests

```bash
# Prompt assembly unit tests directly relevant to this component
cd backend && uv run pytest tests/unit/onyx/chat/test_organization_profile_prompt.py -v
cd backend && uv run pytest tests/unit/onyx/chat/test_user_language_prompt.py -v

# Memory tool
cd backend && uv run pytest tests/unit/tools/test_memory_tool_packets.py -v
uv run --env-file .vscode/.env pytest backend/tests/external_dependency_unit/tools/test_memory_tool_integration.py -v

# Broader prompt/context unit coverage
cd backend && uv run pytest tests/unit -k "prompt or memory or personalization"
```

There is no functional integration test for `auto_detect_search_filters` or
for `input_prompt` API behavior.
`backend/tests/integration/tests/permissions_access/test_basic_access.py` only
covers the `/input_prompt` `BASIC_ACCESS` gate. A change to either behavior needs new integration coverage,
not just the existing unit tests.

### Manual reproduction

1. `tail -f backend/log/api_server_debug.log`.
2. As admin, set a team name and team context at `/admin/chat-preferences`,
   then ask a question in a chat as a normal user; the answer or a debug trace
   should reflect the team context (the `## Team Information` section of the
   system prompt is not shown in the UI, so use tracing/logging, not the chat
   window, to confirm placement).
3. As a user, set personal name, role, and a preference at
   `/app/settings/chat-preferences`; ask "what do you know about me" and
   confirm the reply reflects the name/role/preference.
4. Toggle `use_memories` off with existing memories present; confirm a
   follow-up turn no longer references them, then toggle it back on and
   confirm they return without asking again.
5. Ask the assistant to remember something with the memory tool enabled;
   confirm a new `Memory` row appears
   (`psql -c "select * from memory where user_id = '<uuid>'"`) and that the
   next turn's prompt includes it.
6. Disable `enable_memory_tool`; confirm the assistant can no longer save a
   new memory even mid-conversation, on the very next turn.
7. Change the UI language; confirm the next turn's reply is in that language
   and the `NEXT_LOCALE` cookie was set.

### What "working" looks like

- Admin settings apply workspace-wide on the next turn, not just new sessions.
- A user's memory and preference changes are private to them and never appear
  in another user's prompt.
- Disabling memory read or write takes effect immediately, not after a
  session reload.

---

## 9. Footguns

- **`MemoryTool` bypasses the per-message tool whitelist.** [[tools-framework]]
  §9 documents the mechanism; the consequence here is that a user cannot
  "turn off tools for this message" and expect memory writes to stop too.
  Only `enable_memory_tool` stops it.
- **`use_memories=False` does not stop memory writes.** It only hides
  memories from the assembled prompt. A user who wants "stop remembering
  things about me" must disable `enable_memory_tool`, not `use_memories`.
- **The admin default-assistant modal cannot set `task_prompt`.** Only
  `system_prompt` and `tool_ids` are exposed
  (`default_assistant/api.py:update_default_assistant`). Anyone looking for
  where the trailing reminder is configured will not find it on this page;
  it lives on the persona in [[agents-personas]].
- **There is no admin endpoint to publish an input prompt to everyone.**
  `insert_input_prompt(is_public=True, ...)` exists in
  `db/input_prompt.py` but nothing in `backend/onyx/server` calls it with
  `is_public=True`. Any public prompts in a deployment came from seed data,
  not this API.
- **Workspace settings are a single KV blob, not a table.** A `PATCH
  /admin/settings` call replaces the whole `Settings` object client-side
  (`saveSettings` in `ChatPreferencesPage.tsx` spreads `toSettings(currentSettings)`
  before merging updates); a client that reads a stale copy and PATCHes it back
  can silently revert a concurrent admin's change.
- **Organization profile is not editable from either UI.** It follows the IdP
  login snapshot (`get_idp_profile`); changing a user's job title in the
  identity provider only takes effect on their next login capture, not
  immediately.
- **Incognito's toggle lives outside this component entirely**, in security
  settings, not workspace `Settings`. Do not look for it on
  `/admin/chat-preferences`.
