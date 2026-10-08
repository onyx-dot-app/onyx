# Agents (Persona)

> The configurable unit a user talks to: a prompt, a tool set, a knowledge scope,
> and a model choice, bundled into one row the product calls an Agent and the
> database calls a `Persona`. This document owns the row and its lifecycle;
> [[context-assembly]] owns how its prompt fields reach the LLM, and
> [[tools-framework]] owns how its tool set becomes a live tool.

**Verified against:** `268e4d5a3d` (2026-10-05)
**Domain:** agents-personas
**Edition:** CE for the row, tools, document sets, and the default assistant.
EE for group sharing (`Persona__UserGroup`), scoped-manager permissions, and
per-agent usage stats.
**Owns:**
`backend/onyx/db/persona.py`, `persona_sharing.py`, `pinned_personas.py`,
`backend/onyx/server/features/persona/` (`api.py`, `models.py`, `constants.py`),
`backend/onyx/server/features/default_assistant/`,
`web/src/app/admin/agents/`, `web/src/app/app/agents/`,
`web/src/app/ee/agents/stats/`, `web/src/lib/agents/`

---

## 1. What the user experiences

An admin or a regular user (if permitted) opens `/app/agents/create` and builds
an agent: a name, a description, a system prompt, an optional task prompt
(reminder text appended every turn, see [[context-assembly]]), a model, and a
knowledge scope of document sets, individual documents, or hierarchy nodes
(folders, spaces, channels). They attach tools: internal search, web search,
image generation, custom OpenAPI actions, MCP tools. They can add starter
messages that appear as clickable suggestions, an icon, and labels for
grouping in the picker.

Creating an agent needs the `ADD_AGENTS` permission. Community Edition grants
it to every user. Enterprise Edition grants it through group permissions
(`onyx/auth/permissions.py:CE_UNGATED_PERMISSIONS`). Sharing an agent or making
it public needs more access. The owner can share the agent with named users or
groups as editor or viewer, or publish it org-wide. Anyone who can see it can
pin it to their own sidebar; pin order is per-user.

In chat, picking an agent from `/app/agents` (or the sidebar) changes what the
assistant already knows how to do: its custom instructions apply, its search
is scoped to its document sets or attached items, and only its tools are
offered. Editing a live agent affects every session that references it going
forward; existing chat history is untouched.

An admin viewing `/admin/agents` sees every agent they may manage, can
feature one (surfaces it in "trending" and seeds it into new users' pins),
control its listing and display order, and delete it. `web/src/app/ee/agents/stats/[id]`
shows that agent's daily message and unique-user counts (EE only).

The **Assistant** is the seeded, ownerless, `builtin_persona=True` agent at
`Persona.id == DEFAULT_PERSONA_ID` (0). Every chat session that specifies no
agent uses it. An admin can edit its system prompt and its tool list from
`/admin/default-assistant`, but cannot delete it: the UI never offers the
delete action (`AgentRowActions.tsx`,
`!agent.builtin_persona && can(agent, "delete")`), and
`db/persona.py:mark_persona_as_deleted` also refuses any built-in persona for
every caller, admin included. See §5.

---

## 2. Surfaces

### HTTP endpoints

The naming split is real: the product says Agent, the router paths say
`persona`, except two newer routers that say `agents` (`onyx/server/features/persona/constants.py:ADMIN_AGENTS_RESOURCE`
= `/admin/agents`, `AGENTS_RESOURCE` = `/agents`).

| Method | Path | Handler | Notes |
|---|---|---|---|
| GET | `/persona` | `api.py:list_personas` | Basic listing; `scope_exempt` so a scoped MCP PAT can resolve an agent name. |
| GET | `/persona/{id}` | `api.py:get_persona` | |
| POST | `/persona` | `api.py:create_persona` | |
| PATCH | `/persona/{id}` | `api.py:update_persona` | |
| DELETE | `/persona/{id}` | `api.py:delete_persona` | Soft delete (`Persona.deleted = True`). |
| PATCH | `/persona/{id}/public` | `api.py:patch_user_persona_public_status` | |
| PATCH | `/persona/{id}/share` | `api.py:share_persona` | Sets user/group shares and, for owners/admins, `is_public`. |
| POST | `/persona/{id}/transfer-ownership` | `api.py:transfer_persona_ownership_endpoint` | |
| DELETE | `/persona/{id}/share/me` | `api.py:leave_persona_shares` | A sharee removes themselves. |
| GET/POST | `/persona/labels` | `api.py:get_labels`, `create_label` | |
| GET | `/persona/{id}/avatar` | `api.py:get_persona_avatar` | |
| POST | `/admin/persona/upload-image` | `api.py:upload_file` | |
| GET | `/admin/persona` | `api.py:list_personas_admin` | |
| PATCH | `/admin/persona/{id}/listed` | `api.py:patch_persona_visibility` | |
| PATCH | `/admin/persona/{id}/featured` | `api.py:patch_persona_featured_status` | |
| PATCH | `/admin/persona/{id}/undelete` | `api.py:undelete_persona` | |
| PATCH | `/admin/persona/label/{id}`, DELETE same | `api.py:patch_persona_label`, `delete_label` | |
| GET | `/agents` | `api.py:get_agents_paginated` | Newer paginated listing, still backed by `Persona`. |
| GET | `/admin/agents` | `api.py:get_agents_admin_paginated` | |
| PATCH | `/admin/agents/display-priorities` | `api.py:patch_agents_display_priorities` | |
| GET | `/admin/default-assistant/configuration` | `default_assistant/api.py:get_default_assistant_configuration` | |
| PATCH | `/admin/default-assistant` | `default_assistant/api.py:update_default_assistant` | Only touches `tool_ids` and `system_prompt`. |
| GET | `/analytics/assistant/{id}/stats` | `ee/onyx/server/analytics/api.py:get_assistant_stats` | Backs the stats page. EE only. |
| GET | `/analytics/admin/persona/messages`, `/unique-users` | `ee/onyx/server/analytics/api.py` | Finer-grained analytics feeding the same page. |

Pinning lives in [[chat-preferences]] territory
(`PATCH /user/pinned-assistants`, `onyx/server/manage/users.py`), not this
component's router, but it operates on `User__PinnedPersona`, owned here.

### Frontend routes

| Route | File |
|---|---|
| `/admin/agents` | `web/src/app/admin/agents/page.tsx` re-exports `web/src/views/admin/AgentsPage.tsx` |
| `/app/agents` | `web/src/app/app/agents/page.tsx` |
| `/app/agents/create` | `web/src/app/app/agents/create/page.tsx` |
| `/app/agents/edit/[id]` | `web/src/app/app/agents/edit/[id]/page.tsx` |
| `/ee/agents/stats/[id]` | `web/src/app/ee/agents/stats/[id]/page.tsx`, renders `AgentStats.tsx` |

Shared frontend logic lives in `web/src/lib/agents/`: `svc.ts` (fetch calls,
including `buildAgentUpsertRequest`, the client-to-wire field mapping),
`hooks.ts` (SWR hooks), `types.ts`, and `components/` (`AgentButton`,
`AgentViewer`, `AgentViewerModal`, `ShareAgentModal`, `MoveCustomAgentChatModal`,
`NoAgentModal`).

### Permissions

`Permission.MANAGE_AGENTS`, `ADD_AGENTS`, `READ_AGENTS`, `READ_AGENT_ANALYTICS`
gate the endpoints above (`onyx/auth/permissions.py`). `MANAGE_AGENTS` can be
`GLOBAL`, `SCOPED` (a curator managing specific groups), or `NONE`
(`onyx/auth/scoped_permissions.py`); `db/persona.py:_assert_persona_update_within_managed_scope`
and `persona_edit_within_scope` implement the scoped case.

---

## 3. Data model

```
Persona (persona)
 ├─< Persona__DocumentSet >── DocumentSet
 ├─< Persona__Tool        >── Tool
 ├─< Persona__User        >── User            (share, with PersonaSharePermission)
 ├─< Persona__UserGroup   >── UserGroup        (EE share, with PersonaSharePermission)
 ├─< Persona__UserFile    >── UserFile
 ├─< Persona__HierarchyNode >── HierarchyNode
 ├─< Persona__Document    >── Document
 ├─< Persona__PersonaLabel >── PersonaLabel
 ├─< User__PinnedPersona  >── User            (per-user pin + display_order)
 ├── user_id  ──> User            (owner, SET NULL)
 ├── owner_group_id ──> UserGroup (owner, SET NULL, mutually exclusive with user_id)
 └── default_model_configuration_id ──> ModelConfiguration (SET NULL)
```

### `Persona` columns that change behaviour

Verified against `backend/onyx/db/models.py:Persona` and the
parameter list of `db/persona.py:upsert_persona`.

| Column | Effect |
|---|---|
| `system_prompt` | The agent's instructions. Becomes the moving custom-agent-prompt user message, or the whole system prompt if `replace_base_system_prompt` is set. See [[context-assembly]] §4.1-4.2. |
| `replace_base_system_prompt` | Switches `system_prompt` from an injected user message to a full system-prompt replacement; the custom agent prompt stops moving. |
| `task_prompt` | Folded into the trailing reminder every cycle (`prompt_utils.py:build_reminder_message`), not the system prompt. |
| `datetime_aware` | Gates whether `{{CURRENT_DATETIME}}` is resolved into the prompt. |
| `tools` (via `Persona__Tool`) | The tool set `tool_constructor.py:construct_tools` builds from. A row here is availability, not usability; see §5. |
| `document_sets` (via `Persona__DocumentSet`) | Default knowledge scope offered to the search tool as `document_set_names` in `PersonaSearchInfo`. |
| `attached_documents` (via `Persona__Document`) | Individual documents scoped into search, independent of document sets. |
| `hierarchy_nodes` (via `Persona__HierarchyNode`) | Folders/spaces/channels scoped into search. |
| `search_start_date` | A floor on `updated_at_range` for this agent's searches. [[internal-search]] states it is never negotiated downward. |
| `user_files` (via `Persona__UserFile`) | Files attached at agent-build time, distinct from files a user uploads mid-chat. |
| `default_model_configuration_id` | The agent's LLM override, resolved by `get_llm_for_persona`. Only applied at generation time, not for auto-detected filters. |
| `starter_messages` | `list[StarterMessage]` (a Pydantic type, not a table: `name` + `message`), rendered as clickable suggestions. |
| `icon_name` / `uploaded_image_id` | Mutually usable icon sources; `remove_image` clears the uploaded one. |
| `labels` (via `Persona__PersonaLabel`) | Grouping in the agent picker; labels are a separate CRUD (`PersonaLabel`, `get_labels`/`create_label`). |
| `is_public` / `public_permission` | Org-wide visibility and the permission level (`EDITOR`/`VIEWER`) granted by it. |
| `user_shares` / `group_shares` (via `Persona__User` / `Persona__UserGroup`) | Named sharing, each row leveled independently of `is_public`. |
| `owner_group_id` (EE) | Group ownership, mutually exclusive with `user_id` (`ck_persona_single_owner` check constraint). |
| `is_featured` | Highlighted in discovery UI; also the seed set for `seed_pinned_personas_from_featured`. Requires `MANAGE_AGENTS` to set. |
| `is_listed` | Hides an agent from user-facing listings without deleting it. |
| `display_priority` | Manual ordering; `PATCH /admin/agents/display-priorities` is the only writer in the normal flow. |
| `builtin_persona` | Marks the seeded default assistant; cannot be edited/deleted through the ordinary flow (see §5). |
| `deleted` | Soft-delete flag. |

**Not real fields**, despite being plausible: there is no `temperature` or
`num_chunks` column on the current `Persona` table. `num_chunks` existed on an
older, per-assistant schema (still visible as a literal in the historical
migration `alembic/versions/505c488f6662_merge_default_assistants_into_unified.py`)
but the current model has no such column; retrieval breadth is not a
persona-level knob today. `temperature_default` / `temperature_override_enabled`
exist on `LLMProvider` and per-user override, not on `Persona`
(`onyx/db/models.py`, unrelated tables). `onyx/db/models.py:Persona` has no
temperature or chunk-count field.

### Join and support tables

| Table | Class | Notes |
|---|---|---|
| `persona__document_set` | `Persona__DocumentSet` | |
| `persona__tool` | `Persona__Tool` | "Available", not "usable"; see docstring on the class itself. |
| `persona__user` | `Persona__User` | Carries `permission: PersonaSharePermission` (`EDITOR`/`VIEWER`). |
| `persona__user_group` | `Persona__UserGroup` | EE. Same permission enum. |
| `persona__user_file` | `Persona__UserFile` | |
| `persona__hierarchy_node` | `Persona__HierarchyNode` | |
| `persona__document` | `Persona__Document` | |
| `persona__persona_label` | `Persona__PersonaLabel` | |
| `user__pinned_persona` | `User__PinnedPersona` | `display_order` is dense per-user; every write replaces the whole set. |
| `persona_label` | `PersonaLabel` | The label rows themselves. |

`StarterMessage` (`onyx/db/models.py:StarterMessage`) is a Pydantic model stored inline
via `PydanticListType`, not a separate table.

---

## 4. How it works

### 4.1 Access filtering: `_add_user_filters`

Every access-controlled, user-facing persona listing goes through
`db/persona.py:_add_user_filters`. A single-agent fetch (`GET /persona/{id}`)
does not use it. It uses `get_persona_by_id`, which has its own access rules:
owner, owner-group member, builtin agent, and, when `is_for_edit` is false,
direct share, group share, or `is_public`. The helpers `get_personas` and
`get_personas_by_ids` do not apply it. Their docstrings warn that they can
return personas from all users. `_add_user_filters` builds
one query combining: global `MANAGE_AGENTS`/`READ_AGENTS` short-circuits,
ownership (`user_id` or `owner_group_id` membership), `EDITOR`-level direct or
group shares, org-wide `is_public` with `EDITOR` `public_permission`, and, for
scoped managers, `within_managed_scope_clause`. Anonymous users see only
`is_public and is_listed` rows. `get_editable=False` additionally requires
`is_listed` for every path except ownership (the owning user or an owner-group
member). An unlisted agent stays reachable to its owner. Users with global
`MANAGE_AGENTS`, or `READ_AGENTS` when `get_editable=False`, skip the filter.
Other users do not see it in listings.

### 4.2 Create/update: `create_update_persona` → `upsert_persona`

`api.py:create_persona` / `update_persona` call
`db/persona.py:create_update_persona`, which gates featured-status changes on
`MANAGE_AGENTS`, checks scoped-manager bounds
(`_assert_persona_update_within_managed_scope`), then calls `upsert_persona`
with the content fields in §3. Display priority is not part of this flow
(`update_personas_display_priority` sets it), and share rows go through
`update_persona_access`. `upsert_persona` re-fetches attached tools,
document sets, and user files by id and enforces two access guards on the
attach side:

- **Tool attach**: a newly attached tool backed by an MCP server requires
  `user_can_access_mcp_server`; already-attached tools survive even if access
  is later revoked (`existing_tool_ids` check, `tool_constructor.py`
  docstring on `construct_tools`).
- **Knowledge attach** (`knowledge_guard_applies`): a non-`MANAGE_AGENTS`
  editor may only add document sets, hierarchy nodes, or user files they can
  themselves access (user files: they must own them). Attached documents go
  through `get_accessible_documents_by_ids` for every caller. Already-attached
  document sets, nodes, and files survive removal of the editor's own access.

`update_persona_access` (versioned via `fetch_versioned_implementation` so EE
can add group-share support) applies `is_public`/`public_permission` and
reconciles `Persona__User` rows through `apply_persona_user_share_diff`,
which diffs desired shares against existing rows, notifies genuinely new
sharees (`NotificationType.PERSONA_SHARED`), and never re-notifies on a
level-only change.

### 4.3 Tool construction

`onyx/tools/tool_constructor.py:construct_tools` (via `_construct_tools_impl`)
turns `persona.tools` into a live tool dict, keyed by `Tool.id`:

- Skips any `Persona__Tool` row where `Tool.enabled` is `False`, and any tool
  not in the caller's `allowed_tool_ids` whitelist when one is supplied.
- For the built-in search tool, builds `PersonaSearchInfo` from
  `persona.document_sets`, `persona.search_start_date`,
  `persona.attached_documents`, and `persona.hierarchy_nodes`
  (`tool_constructor.py:_build_search_tool`), a detached Pydantic snapshot
  taken before the tool runs.
- Injects `MemoryTool` unconditionally when `user.enable_memory_tool` is set,
  **bypassing both `persona.tools` and `allowed_tool_ids`**
  (`tool_constructor.py`, the `if user.enable_memory_tool:` block). See
  [[tools-framework]] for the rest of the construction contract.

### 4.4 Prompt reach

`chat/chat_utils.py:get_custom_agent_prompt(persona, chat_session)` resolves
the custom agent prompt once per turn, before the loop starts: a non-default
persona's `system_prompt` always wins (even inside a project), unless
`replace_base_system_prompt` makes it the system prompt outright; the default
persona inside a project falls back to `chat_session.project.instructions`.
Full detail, including the moving-message mechanics and the token-budget
interaction, is [[context-assembly]] §4.1-4.2; this component only owns the
persona row those functions read.

### 4.5 The default assistant

`db/persona.py:get_default_behavior_persona` filters by
`Persona.id == DEFAULT_PERSONA_ID` (`0`,
`onyx/configs/constants.py:DEFAULT_PERSONA_ID`). `get_default_assistant` does
not filter by id. It selects rows with `builtin_persona.is_(True)` and
`deleted.is_(False)` and calls `one_or_none()`. The default assistant is not
seeded by `backend/onyx/seeding/` (that package is currently empty of persona
logic); the seed data and its historical reworks live in Alembic migrations,
for example `alembic/versions/505c488f6662_merge_default_assistants_into_unified.py`,
which inserts the unified "Assistant" row, and
`alembic/versions/2cdeff6d8c93_set_built_in_to_default.py`. There is no
separate `onyx/seeding/` YAML-driven persona seed; the seeding package is
empty, and the migration history is the source of truth.

`default_assistant/api.py:update_default_assistant` lets an admin edit only
its `tool_ids` and `system_prompt` (`db/persona.py:update_default_assistant_configuration`),
explicitly not display priority or built-in status (`upsert_persona`'s own
docstring repeats this limit for the general update path).

### 4.6 Pinning

`db/pinned_personas.py:set_pinned_personas` replaces a user's whole pin set
per call: unauthorized or nonexistent ids are dropped silently (not
rejected), duplicates collapse to first position, and `DEFAULT_PERSONA_ID` is
always excluded because the sidebar never renders it.
`seed_pinned_personas_from_featured` seeds a brand-new user's pins from every
currently `is_featured and is_public and is_listed` persona, running once at
account creation; an admin featuring an agent later only affects future
signups.

### 4.7 Deletion and ownership transfer

`api.py:delete_persona` requires `ADD_AGENTS` (with `allow_scope=True`) and
calls `db/persona.py:mark_persona_as_deleted`, a soft delete
(`persona.deleted = True`) that also flags any attached user files for
persona-scope resync. `mark_persona_as_deleted` refuses any `builtin_persona`
for every caller, admins included. `db/persona.py:_transfer_persona_ownership` refuses to
transfer a `builtin_persona` or a Slack-bot-prefixed persona
(`SLACK_BOT_PERSONA_PREFIX`), and only the current owner (or an admin, for a
vacant persona) may transfer.

### 4.8 Per-agent stats (EE)

`web/src/app/ee/agents/stats/[id]/AgentStats.tsx` calls
`GET /analytics/assistant/{id}/stats`
(`ee/onyx/server/analytics/api.py:get_assistant_stats`), gated by
`_assert_may_view_agent_analytics` → `user_can_view_assistant_stats`
(`READ_AGENT_ANALYTICS` plus the same ownership check as `can_delete_persona`).
It returns daily message counts and daily/overall unique-user counts, sourced
from `ee/onyx/db/analytics.py:fetch_assistant_message_analytics`,
`fetch_assistant_unique_users`, `fetch_assistant_unique_users_total`, which
read `ChatMessage`/`ChatSession` rows filtered by `persona_id`. The two
`/analytics/admin/persona/{messages,unique-users}` endpoints expose the same
underlying counts at finer grain for the admin panel.

---

## 5. Contracts and invariants

1. **A `Persona__Tool` row records availability, not usability.** Disabling a
   `Tool` (`Tool.enabled = False`) does not remove the association row.
   `construct_tools` must keep filtering on `enabled` at construction time; a
   persona's stale tool attachment must never resurrect a disabled tool into a
   live turn. See [[tools-framework]] §5.
2. **`search_start_date` is a floor, never negotiable downward.** Any new
   caller-supplied date filter must be intersected with it, not replace it.
   [[internal-search]] enforces this on the retrieval side; this component
   only owns the column.
3. **A shared or public persona does not bypass per-user ACL.** Sharing a
   persona's *configuration* (prompt, tools, document-set membership) is not
   the same as sharing the *documents* in that scope. Every search still
   compiles the acting user's own ACL (`[[access-control]]`); a viewer of a
   shared agent still cannot see documents they lack access to, even if the
   agent's document set includes them.
4. **`PersonaSearchInfo` must stay a detached Pydantic snapshot.** It is built
   from `persona.document_sets`, `search_start_date`, `attached_documents`,
   and `hierarchy_nodes` before the search tool runs, specifically so
   `SearchTool` and the search pipeline never lazy-load ORM relationships
   after the DB session that loaded them may have closed. [[internal-search]]
   states why this matters at the retrieval layer.
5. **Built-in agents cannot be deleted, by anyone.** The admin frontend
   hides the delete action for `builtin_persona` rows (`AgentRowActions.tsx`),
   and `db/persona.py:mark_persona_as_deleted` also raises for any
   `builtin_persona`, for every caller including admins. `api.py:delete_persona`
   surfaces this as a 400 (`OnyxErrorCode.BAD_REQUEST`, "Built-in agents
   cannot be deleted."). Anything that depends on the default assistant
   always existing (chat sessions with no persona set, `get_llm_for_persona`
   fallbacks) can rely on the backend refusing deletion.
6. **A persona's owner fields are mutually exclusive.** `ck_persona_single_owner`
   enforces `user_id IS NULL OR owner_group_id IS NULL` at the DB level. Any
   code path that sets both is a bug the constraint will catch, but only at
   commit time.
7. **Featured, transfer, and undelete are each gated independently.** Setting
   `is_featured` requires global `MANAGE_AGENTS` regardless of ownership;
   transferring ownership requires being the current owner (or admin, for a
   vacant persona) and refuses `builtin_persona`; undelete is an admin action
   (`/admin/persona/{id}/undelete`), separate from create.

---

## 6. Relationships

**Depends on**
- [[tools-framework]]: `construct_tools` turns `persona.tools` into the live
  tool set; `Persona__Tool` availability versus usability is defined there.
- [[internal-search]]: consumes `PersonaSearchInfo` and enforces the
  `search_start_date` floor and knowledge-scope filtering.
- [[access-control]]: the ACL check that a shared persona's document scope
  still respects, per viewer.
- [[llm-providers]]: `default_model_configuration_id` resolves through
  `get_llm_for_persona`.
- [[core-chat-loop]]: `build_chat_turn` loads the persona and its eager-loaded
  relations once per turn.

**Depended on by**
- [[context-assembly]]: `persona.system_prompt`, `task_prompt`,
  `replace_base_system_prompt`, `datetime_aware` drive nearly every branch of
  system-prompt and custom-agent-prompt assembly.
- [[chat-frontend]]: the agent picker, `/app/agents/*` pages, and the
  in-chat agent switcher all read this component's snapshots.
- [[projects]]: a project's default agent falls back to project instructions
  only when the default persona is active; a custom persona always
  supersedes a project (`get_custom_agent_prompt`).
- [[skills]] and [[mcp-and-custom-tools]]: skills and MCP tools become
  attachable `Tool` rows that personas reference the same way as any other
  tool.

---

## 7. Blast radius

| If your change… | Also check |
|---|---|
| adds a `Persona` column | A migration; `PersonaUpsertRequest`/`PersonaSnapshot`/`FullPersonaSnapshot` in `server/features/persona/models.py`; `upsert_persona`'s parameter list; both `web/src/lib/agents/types.ts` and `svc.ts:buildAgentUpsertRequest`; the create and edit forms under `web/src/app/app/agents/`; whether `tool_constructor.py` or [[context-assembly]] needs to read the new field; whether it needs an incognito or ACL decision. |
| changes sharing (`is_public`, share levels, group sharing) | `_add_user_filters` (every listing query), `get_persona_access_level` and `derive_persona_sharing_status` in `persona_sharing.py`, the EE `update_persona_access` implementation, and [[access-control]] for whether document-level ACL still applies independently. |
| changes the default assistant | `get_default_assistant`/`get_default_behavior_persona`, `update_default_assistant_configuration`, the `disable_default_assistant` workspace setting (owned by chat-preferences, not this component), and every chat entry path that assumes persona id 0 exists. |
| changes tool attachment (`Persona__Tool`) | [[tools-framework]]'s enabled/disabled distinction; `get_tool_ids_on_editable_personas` (rebuilds the tool-id set the editor round-trips); the MCP-access guard in `upsert_persona`. |
| changes `search_start_date` or knowledge-scope fields | [[internal-search]]'s floor enforcement and `PersonaSearchInfo`'s field list must move together. |
| changes pinning | `db/pinned_personas.py` and the `PATCH /user/pinned-assistants` route it backs; the seeded-pin logic in `seed_pinned_personas_from_featured`. |
| changes per-agent stats | `ee/onyx/db/analytics.py` fetch functions and `AgentStats.tsx`; confirm `user_can_view_assistant_stats` still matches `can_delete_persona`'s ownership semantics. |

---

## 8. How to verify a change

### Tests

```bash
cd backend && uv run pytest tests/integration -k persona
cd backend && uv run pytest tests/unit -k persona
cd web && bun run playwright tests/e2e/agents
```

Relevant existing e2e coverage: `web/tests/e2e/agents/create_and_edit_agent.spec.ts`,
`persona_avatar.spec.ts`, `persona_chat.spec.ts`, `user_file_attachment.spec.ts`,
`llm_provider_rbac.spec.ts`, plus `web/tests/e2e/admin/default-agent.spec.ts` and
`disable_default_agent.spec.ts`, and page objects
`web/tests/e2e/pages/AdminAgentsPage.ts`, `AgentEditorPage.ts`.

### Manual reproduction

1. Sign in as `admin_user@example.com` / `TestPassword123!` at
   `http://localhost:3000`.
2. Go to `/app/agents/create`. Create an agent with a custom system prompt, a
   document set scoped to a small, known set of documents, and the internal
   search tool attached.
3. Chat with the new agent. Ask something the custom prompt should visibly
   affect, and confirm the instruction shows up in the response.
4. Ask a question answerable only from documents outside the attached
   document set. Confirm the agent does not surface them.
5. Ask a question answerable from a document inside the scope. Confirm it
   does, with a citation.
6. In `/admin/agents`, confirm the agent lists correctly, feature it, and
   confirm it appears in a newly registered user's pinned sidebar.
7. Open `/ee/agents/stats/[id]` for the agent (EE) and confirm the chat turn
   from step 3 shows up in the message/user counts.

### What "working" looks like

- The agent's prompt and knowledge scope are both visibly in effect in chat,
  not just saved in the admin form.
- A disabled or removed tool never becomes callable through a persona that
  still lists it.
- Sharing changes take effect for the intended audience only; an unshared
  user cannot fetch the agent by id.

---

## 9. Footguns

- **Persona versus Agent.** The database table, most Python identifiers, and
  the older router (`/persona`) all say Persona. The product, the newer
  router (`/agents`, `/admin/agents`), and every user-facing string say
  Agent. Grepping for "agent" in the backend misses most of the logic;
  grepping for "persona" in the frontend misses the newer surfaces.
- **The default assistant's protection from deletion is enforced twice.**
  The UI hides the delete action, and the backend delete path
  (`mark_persona_as_deleted`) independently refuses any `builtin_persona`.
  See §5.
- **`onyx/seeding/` does not seed personas.** The package exists and is
  empty of persona logic; the default assistant and any historical seeded
  personas come from Alembic migrations, not a seeding module. Do not assume
  a `seeding/personas.yaml` exists.
- **There is no persona-level `temperature` or `num_chunks` field today.**
  `num_chunks` is a fossil from a pre-unification schema, visible only in old
  migration literals. Do not add logic that reads a persona for retrieval
  breadth or sampling temperature; those live elsewhere (per-provider,
  per-user overrides), not on `Persona`.
- **A tool attached to a persona is not necessarily a usable one.**
  `Persona__Tool`'s own class docstring says this outright: a disabled tool,
  or one whose backing service (MCP server, image-gen credentials) is gone,
  stays attached. Only `construct_tools`'s runtime filtering decides what is
  actually callable.
- **`MemoryTool` never appears in `persona.tools`.** It is injected purely
  from `user.enable_memory_tool`, bypassing both the persona's tool list and
  any `allowed_tool_ids` whitelist. A persona that looks like it has no tools
  attached can still have memory active for that user.
- **Sharing an agent does not share its documents.** A user who can open a
  shared agent and see its configured document sets still hits their own ACL
  on every search; an admin who assumes "shared agent" implies "shared
  knowledge" will be surprised the first time a viewer's search comes back
  empty.
- **Featuring is not the same as pinning, and pin seeding is one-shot.**
  Featuring an agent after users already exist does not retroactively pin it
  for them; only new signups pick it up
  (`seed_pinned_personas_from_featured`'s own docstring states this).
- **`display_priority` is set by the admin reorder endpoint in the normal flow.**
  The upsert API accepts `display_priority`, but `upsert_persona` only stores it
  on creation or when the existing value is null. The standard frontend form
  (`buildAgentUpsertRequest`) always sends `null`. Only
  `PATCH /admin/agents/display-priorities` changes a set value. A form change
  that tries to reorder through the regular update silently does nothing.
