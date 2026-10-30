# Plugins

> The admin and member surfaces for MCP servers and OpenAPI actions, the
> Plugins pages that also host Craft apps, and the rules that decide whether a
> plugin is on in Default Chat.

**Verified against:** `a4e97fcea1` (2026-10-29)
**Edition:** CE. Craft apps, Craft availability and Craft approval settings
appear only when Craft is available. Group or user restriction needs EE.

---

## User experience

- **An admin** opens Admin > Plugins and sees the MCP servers and OpenAPI
  actions in one directory. A global action manager sees all of them. A scoped
  manager sees those they own, and can view without editing those that an
  agent shared with or owned by one of their groups uses. A full admin also
  sees Craft apps. The admin adds a plugin from a catalog of
  suggested MCP servers, a custom MCP URL, or an OpenAPI schema. Edits stay as
  drafts until Save. Leaving a saved plugin with unsaved edits asks for
  confirmation.
- **A full admin turns a plugin on for Default Chat.** Default Chat is the chat
  with no custom agent. The switch on the plugin and the tool list in Admin >
  Chat Preferences change the same selection, so a change in one shows in the
  other. A scoped action manager can edit a plugin but cannot change Default
  Chat. When a server needs sign-in, enabling it opens authentication first.
  If sign-in fails or is cancelled, the tools stay off.
- **A member** opens Plugins from the sidebar or the composer's Actions menu.
  The member sees which plugins are connected and which need sign-in, connects
  an account in a new tab, and can turn a plugin off for their own Default
  Chat or Craft sessions. Turning it off keeps their credentials. A plugin
  that an admin left off cannot be turned on by a member.
- **In chat**, a "Tools need credentials" prompt lists tools on the current
  agent that need the user to connect. The user can keep chatting without
  them. A tool call that fails on credentials shows an error in the tool step
  ([[mcp-and-custom-tools]]).

---

## Scope

This component owns the plugin admin directory and editors, the member plugin
directory and its connection states, member OAuth in a new tab, and the
suggested-server catalog. It also owns two rules whose backend code other
components map: the Default Chat selection of plugin tools, and per-user plugin
preferences (`MCPServerUserPreference`, `ToolUserPreference`).

Its neighbours own:
- [[mcp-and-custom-tools]]: the plugin API, credentials, setup and tool sync.
- [[agents-personas]]: the default assistant and its `Persona__Tool` rows.
- [[chat-preferences]]: Admin > Chat Preferences, the other editor of the
  Default Chat tool list.
- [[craft-admin]]: the Craft app admin routes, the external-app admin page
  and the external-app editor components. The Plugins pages host them.
- [[craft-external-apps]]: what a Craft action policy means at request time,
  and approvals.
- [[chat-frontend]]: the composer that hosts the plugin menu.

---

## Architecture

**Admin flow.** `PluginsPage` lists plugins. The setup modal
(`sections/actions/modals/MCPPluginSetupModal.tsx`) probes the URL through
`POST /admin/mcp/probe` and then calls `/admin/mcp/setup`. The detail page
(`sections/actions/MCPServerDetailPage.tsx`) uses the same setup call for
authentication edits, through
`sections/actions/modals/MCPAuthenticationPage.tsx`. The setup call saves
nothing until sign-in and tool discovery succeed ([[mcp-and-custom-tools]]
owns that flow). `web/src/app/admin/plugins/layout.tsx` keeps the directory
behind every detail modal, including after an OAuth return.

**Member flow.** `lib/plugins/member.ts:useMemberPlugins` reads only member
endpoints (MCP servers, tools, the user's OAuth token status and Craft apps),
never admin listings. `buildMemberPlugins` joins them into one list and drops
tools whose `Tool.enabled` is false. Its `mcpConnection` and `openAPIConnection` helpers classify
each plugin as connected (with an owner: user, workspace, session or none),
needing OAuth, needing credentials, unconfigured, checking or unavailable.

**Member OAuth.** `lib/plugins/memberConnection.ts:runMemberPluginOAuth` opens
a new tab and waits for `/app/plugins/oauth/complete` to report back by
`postMessage` or by a `BroadcastChannel` named for the attempt. A closed opener
link is not taken as cancellation, because a provider's opener policy can sever
it while sign-in continues. The attempt ends on completion, on cancel, or after
five minutes. The completion page and the caller each check the saved
connection before they report success.

**Default Chat at turn time.** `tools/tool_constructor.py:_construct_tools_impl`
loads the user's preferences only for the default assistant and skips a tool
whose preference has `enabled_in_chat` false. On the web,
`lib/plugins/chat.ts:effectiveChatForcedToolId` drops a forced plugin tool in
Default Chat when the user's preference turns it off.

---

## Contracts and traps

1. `default-chat-is-persona-tool` **Default Chat is `Persona__Tool` rows on the
   default assistant.** There is no plugin or server flag.
   `db/tools.py:get_default_chat_tool_ids` and
   `backend/onyx/db/mcp.py:get_default_chat_mcp_server_ids` derive the state. A
   server counts as on when any of its tools is selected.
2. `default-chat-full-admin-only` **Only `FULL_ADMIN_PANEL_ACCESS` changes
   Default Chat.** `server/features/tool/api.py:_validate_default_chat_permission`,
   `server/features/mcp/api.py:_validate_mcp_setup` and the
   `/admin/default-assistant` routes enforce it. An omitted
   `default_chat_enabled` or `enable_chat` leaves the selection unchanged.
3. `default-assistant-lock` **Plugin writes follow the default-assistant lock
   rule.** [[agents-personas]] owns that rule.
   `server/features/tool/api.py:_lock_default_chat_selection` applies it before
   the tool row write.
   `backend/onyx/db/persona.py:set_default_chat_tool__no_commit` changes one
   tool and keeps the rest. On the web,
   `web/src/lib/agents/hooks.ts:enqueueDefaultAssistantSave` orders saves from
   every hook instance.
4. `missing-preference-means-enabled` **A missing preference row means
   enabled.** Both preference tables default to true. Preferences apply only to
   Default Chat and Craft; custom agents ignore them.
   `server/features/tool/api.py:update_tool_user_preferences` and
   `server/features/mcp/api.py:update_mcp_user_preferences` refuse to turn on
   a plugin that is not on in Default Chat (or not available in Craft).
   The sandbox proxy (`sandbox_proxy/resolvers/mcp_server.py`) and
   `backend/onyx/db/mcp.py:get_craft_enabled_mcp_servers` enforce
   `enabled_in_craft`.
5. `openapi-enabled-default-chat-only` **OpenAPI tools use `Tool.enabled` only
   for Default Chat.** `server/features/tool/models.py:CustomToolCreate`
   rejects `enabled=false` and `server/features/tool/api.py:update_tools_status`
   rejects OpenAPI ids. A row stored with `enabled=false`
   stays off in Default Chat
   (`server/features/tool/tool_visibility.py:is_tool_available_for_persona`)
   but works on custom agents. Selecting it for Default Chat sets it to true
   (`backend/onyx/db/persona.py:_attach_default_chat_tools__no_commit`). MCP
   and built-in tools stay attached when disabled, and construction skips them.
6. `discovery-does-not-select` **Tool discovery does not select new tools.**
   `server/features/mcp/api.py:_sync_mcp_server_tools` never writes
   `Persona__Tool`. A tool that a remote
   server adds after the admin enabled the server is off in Default Chat until
   a full admin enables the server again. Setup selects discovered tools only
   when it is asked to (`server/features/mcp/api.py:_publish_mcp_setup`).
7. `explicit-enable-intent` **Only an explicit Enable action turns a server on
   through authentication.** `sections/actions/mcpChatEnableIntent.ts` writes a
   one-time record to session storage, bound to the user, the server and the
   origin, that expires after five minutes. The detail page and the
   authentication page enable the server only when they verify that record. A
   query flag alone must never enable tools for the whole workspace.
8. `connection-status-is-credential-state` **`connection_status` is credential
   state, not a UI decision.** It is `not_connected`, `connected` or
   `reauth_required`, and null only without a user. Whether a Connect action
   exists comes from `web/src/lib/mcp/auth.ts:getMcpAuthenticationFlow`.
   Admin-performed OAuth or API-token servers have no member flow.
9. `member-directory-no-admin-endpoints` **The member directory must not call
   admin endpoints.** A scoped manager or a member cannot read them, and Craft
   app admin records are for full admins only.
10. `old-admin-routes-redirect` **`/admin/mcp-actions` and
    `/admin/openapi-actions` only redirect.** Their pages map to the plugin
    routes through the helpers in `web/src/lib/plugins/routes.ts` and keep query
    parameters. New links go to `/admin/plugins`.
11. `action-policies-craft-only` **Action policies apply only in Craft.** The
    Auto-approve, Ask and Disabled settings in the plugin editors go to the
    Craft proxy ([[craft-external-apps]]). `MCPTool` and `CustomTool` in Chat
    never read them and run every call with no approval. The plugin UI must not
    show read or write badges to members or promise an approval in Chat.
12. `shared-oauth-config-shared-connection` **OpenAPI tools that share an
    `OAuthConfig` share each user's connection.** `OAuthUserToken` is unique on
    the configuration and the user, not the tool. A member who connects or
    disconnects one such plugin changes the state of every plugin linked to the
    same configuration. An expired grant needs a new sign-in only when the token
    status has `can_refresh` not true (`lib/plugins/member.ts`).

---

## Dependencies

- [[mcp-and-custom-tools]]: every plugin API this UI calls.
- [[agents-personas]]: the default assistant and `/admin/default-assistant`.
- [[chat-preferences]]: Admin > Chat Preferences edits the same selection.
  Both use `web/src/lib/agents/hooks.ts:useDefaultAssistantConfiguration` and
  write through `PATCH /admin/default-assistant/tools`.
- [[chat-frontend]]: hosts the Actions menu and the credentials prompt.
- [[craft-admin]]: the Craft app admin routes behind the external-app pages.
- [[craft-external-apps]]: the meaning of the approval settings in the same UI.
- [[auth-and-identity]]: OpenAPI per-tool OAuth status for member connections.

---

## Recipes

- `suggested-mcp-server` **A suggested MCP server.** Copy the `linear` entry in
  `web/src/lib/plugins/catalog.ts:SUGGESTED_MCP_PLUGINS`; that array is the
  current set. Add the id to the `SuggestedMCPPlugin` id union. Selecting the
  entry only fills the setup form. It creates no credentials.
- `plugin-kind` **A plugin kind.** Copy the `openapi` kind; list the kinds in
  `PluginReference` in `web/src/lib/plugins/types.ts`. Extend the `MemberPlugin`
  union and its connection helper in `web/src/lib/plugins/member.ts`, and the
  detail routes in `lib/plugins/routes.ts`. Decide whether it is a Chat kind
  (`ChatPluginReference`).
- `mcp-auth-type-ui` **The UI for a new MCP auth type.** Copy the `API_TOKEN`
  branches in `web/src/lib/mcp/auth.ts:getMcpAuthenticationFlow`, the
  `mcpConnection` helper in `web/src/lib/plugins/member.ts`, and
  `web/src/sections/actions/modals/mcpAuthForm.ts`.
- `investigate-missing-default-chat-tool` **Investigate "a plugin is on, but its
  tool is missing in Default Chat".** Check, in order: the tool has a
  `Persona__Tool` row on the default assistant
  ([[#default-chat-is-persona-tool]]); a tool that the remote server added
  later is not selected ([[#discovery-does-not-select]]); the user has a
  preference row that turns it off ([[#missing-preference-means-enabled]]).

---

## Verification

- Web unit tests sit next to the code in `web/src/sections/plugins/`,
  `web/src/sections/actions/` and `web/src/lib/plugins/`.
- Backend: `backend/tests/unit/onyx/server/features/tool/` and the Default Chat
  and preference tests in `backend/tests/unit/onyx/server/features/mcp/`.
- Playwright: `web/tests/e2e/mcp/`, which covers Default Chat.
- By hand, enable a server for Default Chat from the plugin page and confirm
  that Admin > Chat Preferences shows its tools selected. Then turn it off as a
  member and confirm that a custom agent with the server still uses it.
