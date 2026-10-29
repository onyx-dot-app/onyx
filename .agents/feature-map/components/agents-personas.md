# Agents (Persona)

> Agents (`Persona` in the database and most Python code): the configurable row of instructions, tools, knowledge and model that a user talks to. This component owns the row, who can see and change it, sharing, pins and the default assistant.

**Verified against:** `73e0ae3c31` (2026-10-28)
**Edition:** CE for the row, user shares, pins and the default assistant. EE
adds group shares, group ownership and per-agent usage stats.

---

## User experience

- **A user with `ADD_AGENTS`** builds an agent: a name, instructions, an
  optional task prompt that repeats every turn, a model, knowledge (document
  sets, single documents, connector folders, or the user's own files), tools,
  starter messages and an icon. CE grants `ADD_AGENTS` to every user. EE grants
  it through groups.
- **In chat**, picking an agent applies its instructions, scopes search to its
  knowledge, and offers only its tools. An edit applies to the next turn of
  every session that uses the agent. Old messages do not change.
- **Sharing.** The owner shares with users as editor or viewer, or publishes
  the agent to the whole organization. EE group shares need more than
  ownership: to add or remove a group, a user must manage that group
  ([[#group-share-needs-manage-agents]]). A new sharee gets a notification
  once. A sharee can leave the share list. The owner can transfer ownership;
  the previous owner stays on as an editor.
- **Pins.** Each user pins agents to the sidebar in their own order. A new
  account starts with the agents that an admin featured. Featuring an agent
  later does not change the pins of existing users.
- **Admins** feature, unlist, reorder, delete and restore agents. EE shows
  daily messages and unique users for each agent.
- **The default "Assistant"** is the agent for every chat that names no agent.
  An admin edits only its system prompt and tools, at Admin > Chat
  Preferences. Nobody can delete it.

When it fails:
- Attaching knowledge the editor cannot read, or an MCP server the editor
  cannot use, returns a 400 that names the problem.
- A name that the creator already uses returns a 400 that asks for a rename.
- An editor who is not the owner can save the form, but a change to public
  status is dropped without an error. A request from a non-manager that sets
  featured to true returns a 400 ([[#editor-fields-dropped]]). Listed status
  changes only through the admin listed route.
- Deleting another user's agent returns 403. The default assistant: 400.
- With user knowledge turned off, attaching files fails. With
  `DISABLE_VECTOR_DB` set, attaching document sets, documents or folders fails.

---

## Scope

This component owns the agent row and its join rows, the read and edit access
filters, sharing and ownership, pins, labels, display order, featured and
listed status, the default-assistant row, and the connector-folder picker that
the agent editor uses.

Neighbours own the rest:
- [[context-assembly]]: how `system_prompt`, `task_prompt`,
  `replace_base_system_prompt` and `datetime_aware` reach the model.
- [[tools-framework]]: how `persona.tools` becomes live tools, and the memory
  tool that skips the agent's tool list.
- [[plugins]]: which tools the default assistant offers, and per-user tool
  preferences. [[mcp-and-custom-tools]] owns MCP and OpenAPI tool rows.
- [[internal-search]]: how the knowledge scope filters retrieval, including the
  `search_start_date` floor.
- [[access-control]]: document ACLs, which still apply to every viewer.
- [[projects]]: how agent and project files and instructions combine.
- [[chat-preferences]]: the workspace setting that turns off the default
  assistant, and the Admin > Chat Preferences page that edits it. The pin
  route sits with the user routes ([[auth-and-identity]]) and calls
  `set_pinned_personas`.
- [[file-store-and-user-files]]: the chunk ACL sync for agent files, and the
  `/chat/file` read check.

---

## Architecture

```
POST/PATCH /persona               server/features/persona/api.py
  -> create_update_persona        db/persona.py   scoped-manager gate, featured gate
       -> upsert_persona          attach guards, field writes
       -> update_persona_access   CE or EE (fetch_versioned_implementation)
            -> mark_persona_user_files_for_sync
chat turn (build_chat_turn)       loads the persona
  -> capture_persona_tool_configuration   db/tools.py: detached PersonaSearchInfo
  -> construct_tools              [[tools-framework]]
  -> get_custom_agent_prompt      chat/chat_utils.py, with project instructions
```

**Two names.** The database, most Python and the `/persona` routes say
Persona. The product, the paginated listings and the reorder route say Agent
(`server/features/persona/constants.py`). Search the backend for "persona",
not "agent".

**Two read filters.** Listings and edit checks use
`backend/onyx/db/persona.py:_add_user_filters`. Global `MANAGE_AGENTS` skips
it, and so does `READ_AGENTS` for reads. Anonymous users see public, listed
agents. The edit mode (`get_editable=True`) admits owners, owner-group members,
EDITOR shares, org-wide EDITOR publishing, and scoped managers inside their
groups. The read mode admits a share at any level and public agents, but only
when the agent is listed; owners always see their own. `get_persona_by_id` has
its own rules and always admits built-in agents. `get_personas` and
`get_personas_by_ids` apply no access filter.

**Sharing changes reach the index.** A user file attached to an agent carries
the agent's audience in its index ACL. Each write that changes the audience
(share, publish, transfer, leave, delete, restore, file attach) sets
`UserFile.needs_persona_sync`, with one gap (see Known issues). A background task then rewrites the chunk
metadata ([[file-store-and-user-files]]).

**Pins.** `db/pinned_personas.py:set_pinned_personas` replaces the whole pin
set and drops, without an error, the default assistant and ids the user cannot
read. `seed_pinned_personas_from_featured` runs once, at account creation.

---

## Contracts and traps

1. `update-replaces-whole-agent` **The update route replaces the whole
   agent.** `backend/onyx/db/persona.py:upsert_persona` overwrites the description, model, starter
   messages, icon, `search_start_date` and `replace_base_system_prompt` on
   every update. A caller that sends a partial body clears those fields. Prompt
   fields change only when not null. For labels, tools, files, folders and
   documents, null keeps the list; `[]` clears it.
2. `editor-fields-dropped` **Some fields are dropped, not rejected, for
   editors.** On update, `upsert_persona` ignores `is_public` unless the caller
   can delete the agent (`backend/onyx/db/persona.py:can_delete_persona`: owner, owner group or global
   `MANAGE_AGENTS`). It ignores `is_listed` and `is_featured` unless the caller
   has global `MANAGE_AGENTS`. Before that, `backend/onyx/db/persona.py:create_update_persona` returns a
   400 to a non-manager who sends `is_featured: true`, on create and on update.
   `PersonaUpsertRequest` has no `is_listed` field, so the create and update
   routes never change it; the admin `listed` and `featured` routes do.
3. `display-priority-reorder-only` **`display_priority` changes only through
   the reorder route.** `upsert_persona` stores it only when the stored value
   is null, and the web form (`web/src/lib/agents/svc.ts`) always sends null.
   Use `PATCH /admin/agents/display-priorities`
   (`backend/onyx/db/persona.py:update_personas_display_priority`).
4. `create-defaults-public` **A new agent is public unless the request says
   otherwise.** The create branch of `upsert_persona` defaults `is_public` to
   true. An API caller that omits the field publishes the agent to the
   organization.
5. `attach-guards-additions-only` **Attach guards check only additions.** For a
   caller without global `MANAGE_AGENTS`, `upsert_persona` checks that each
   added document set and folder is readable by the caller, and that each
   added file is the caller's own. For every signed-in caller, each added
   MCP-backed tool needs `backend/onyx/db/mcp.py:user_can_access_mcp_server`. Attached items stay when
   the editor loses access. Single documents are filtered for every caller:
   unreadable ids are dropped, and the call fails only when none remain.
6. `sharing-not-document-access` **Sharing an agent does not share its
   documents.** Search still applies the viewer's own ACL ([[access-control]]).
   A viewer of a shared agent can get no results from its document sets.
7. `tool-attached-not-usable` **A tool on the agent is available, not usable.**
   The `db/models.py:Persona__Tool` docstring states this. Disabled and
   unconfigured tools stay attached, and `tools/tool_constructor.py:construct_tools`
   skips them. Never treat the join row as
   proof that a tool runs ([[tools-framework]]). The editor rebuilds `tool_ids`
   from `backend/onyx/db/persona.py:get_tool_ids_on_editable_personas`, so a tool missing from that
   listing is dropped on the next save.
8. `persona-search-info-detached` **`PersonaSearchInfo` must stay a detached
   snapshot.** `db/tools.py:capture_persona_tool_configuration` copies document
   set names, `search_start_date`, document ids and folder ids before the
   search tool runs, so search never lazy-loads ORM data after the session
   closes. Add a new knowledge field there and in
   `context/search/models.py:PersonaSearchInfo` together.
9. `builtins-undeletable` **Built-in agents cannot be deleted or
   transferred.** `backend/onyx/db/persona.py:mark_persona_as_deleted` raises for `builtin_persona`,
   because `get_persona_by_id` admits built-ins for every user and would
   otherwise let anyone delete them. `backend/onyx/db/persona.py:_transfer_persona_ownership` also refuses
   Slack bot agents. Code that assumes agent id 0 exists relies on this.
10. `default-assistant-tool-lock` **Writers of the default assistant's tool
    list lock its row.** `backend/onyx/db/persona.py:lock_default_assistant__no_commit` serializes them,
    and they change `persona__tool` with core SQL, not an ORM collection
    replace, so a parallel delete cannot raise `StaleDataError`. A new writer
    must take the lock before it writes any `tool` row, to keep the lock order.
    [[plugins]] owns which tools the default assistant selects.
11. `edit-clears-provider-cache` **An agent edit must clear the provider
    listing cache.** `server/features/persona/api.py:update_persona` calls
    `server/manage/llm/provider_cache.py:invalidate_provider_listing_cache`, because the cached LLM provider
    listing includes each agent's default model. Any other API writer of
    `default_model_configuration_id` must do the same. Writers outside the API,
    such as seeding and Slack channel agents, stay stale until the entry TTL
    in `server/manage/llm/provider_cache.py` expires.
12. `single-owner` **One owner at most.** The `ck_persona_single_owner` check
    forbids both `user_id` and `owner_group_id`. A transfer sets one and clears
    the other. Both may be null: an ownerless agent that is not built-in is
    vacant, and only a global manager can transfer it. Deactivating or deleting
    a user makes their agents vacant
    (`db/users.py:release_personas_owned_by_user__no_commit`).
13. `group-share-needs-manage-agents` **Changing group shares is a
    `MANAGE_AGENTS` action (EE).**
    `backend/ee/onyx/db/persona.py:_assert_group_share_within_scope` gates it.
    A global `MANAGE_USER_GROUPS` or `MANAGE_AGENTS` holder passes. An owner
    may change share levels but not the set of groups. A scoped manager passes
    only when it manages every group before and after the change, and only
    while the agent is private before and after the change. Any other editor may send the current shares back unchanged.
    `ADD_AGENTS` alone lets a user create an agent, not share it with a group.
    Skills apply a stricter form of this rule with `MANAGE_SKILLS`
    ([[skills]]).

---

## Decisions

- **The default assistant comes from migrations.** Alembic migrations create
  the row with id 0, for example
  `alembic/versions/505c488f6662_merge_default_assistants_into_unified.py`.
  `backend/onyx/seeding/` has no persona logic; do not look there.
- **`Persona` has no temperature or chunk-count field.** A persona
  `num_chunks` appears only in old migration literals. Temperature lives on
  `ModelConfiguration`, `User` and `ChatSession`, not on the agent.
- **Soft delete.** Deleting sets `Persona.deleted`. Chat sessions keep a valid
  foreign key, and an admin can restore the agent. A create that uses the name
  of a deleted agent that the creator owns (any owner, for a global manager)
  reuses that row and its id.
- **Pins are rows, not a JSON array.** `User__PinnedPersona` has foreign keys,
  so a deleted agent cannot leave a dangling pin. Seeding is one statement, so
  a user is never half seeded.
- **Seeding does not use the access filter.** Admins skip `_add_user_filters`
  and would get other users' private featured agents. Seeding uses
  `is_public` directly (`build_seed_pinned_personas_stmt`).

---

## Known issues

- **Name lookups can raise on duplicates.** Names are unique only among
  built-in agents. `backend/onyx/db/persona.py:_get_persona_by_name` calls `scalar_one_or_none` with no
  owner filter for global managers. When two users already have agents with
  the same name, an admin who creates that name gets a 500, not the rename
  message. Not reproduced.
- **The duplicate-chat fallback can raise.** `backend/onyx/db/persona.py:get_best_persona_id_for_user`
  calls `one_or_none` on a query that returns every editable agent. When the
  original agent is not readable and the user can edit more than one agent, it
  raises `MultipleResultsFound`. Not reproduced.
- **Publishing through the update route can skip the file ACL sync.**
  `upsert_persona` writes `is_public`, but only `update_persona_access` marks
  files for sync, and it does so only when the request carries `users` or
  `groups`. A `PATCH /persona/{id}` that changes `is_public` and omits both
  leaves agent file chunks with the old audience. The web form always sends
  both lists. Not reproduced.
- **Group sharees cannot open agent files directly.**
  `backend/onyx/access/access.py:_user_can_access_persona_attached_file`
  admits public agents, owners and direct user shares, but not group shares or
  owner groups. Search still finds the file chunks through the index ACL.

---

## Dependencies

- [[tools-framework]]: turns `persona.tools` into live tools.
- [[internal-search]]: consumes `PersonaSearchInfo`.
- [[authorization]]: `require_permission` and the scoped-manager gates
  (GATE 1 and GATE 2).
- [[access-control]]: document ACLs for agent document sets and files.
- [[llm-providers]]: resolves `default_model_configuration_id`.
- [[file-store-and-user-files]]: indexes agent files and syncs their ACLs.
- [[notifications]]: the share notification.

---

## Recipes

- `add-agent-field` **Add an agent field.** Copy the path of `search_start_date`, which reaches
  the model, the API and search. List the current fields in
  `PersonaUpsertRequest` (`server/features/persona/models.py`). Add the column
  and migration, the request and snapshot models, both branches of
  `upsert_persona` ([[#update-replaces-whole-agent]]),
  `web/src/lib/agents/types.ts`, and `buildAgentUpsertRequest` in
  `web/src/lib/agents/svc.ts`. If search needs it, follow
  [[#persona-search-info-detached]]. If an editor must not set it, gate it like
  `is_featured` ([[#editor-fields-dropped]]).
- `add-audience-write` **Add a write that changes an agent's audience.** Copy
  `mark_persona_as_deleted`: change the row, then call
  `mark_persona_user_files_for_sync` (or `_mark_files_need_persona_sync`) for
  the attached files. Find the current writers with
  `git grep -n "_mark_files_need_persona_sync\|mark_persona_user_files_for_sync" backend/`.
  The chunk sync itself is in [[file-store-and-user-files]].
- `investigate-agent-visibility` **Investigate "user X cannot see agent Y".** Check, in order: `deleted`,
  `is_listed` (the read filter hides unlisted agents from sharees),
  `is_public`, the `persona__user` and `persona__user_group` rows, and the
  user's group membership. Then read `_add_user_filters` for the mode the
  route uses: listings use read mode, the edit form uses edit mode.
- `test-agent-setup` **Set up agents for a test.** Use the integration manager
  `backend/tests/integration/common_utils/managers/persona.py`. For sharing
  and ownership cases, copy the helpers in
  `backend/tests/external_dependency_unit/db/agent_sharing_helpers.py`.

---

## Verification

- `backend/tests/external_dependency_unit/db/` (the `test_agent_sharing_*`
  files) covers sharing, transfer, lifecycle and the attach guards.
- `backend/tests/integration/tests/personas/` covers create, update, labels
  and pagination.
- `web/tests/e2e/agents/` covers the editor.
- By hand: share an agent as viewer with a second user who lacks access to one
  of its document sets. The agent must appear in their list, and a search must
  not return the hidden documents.
