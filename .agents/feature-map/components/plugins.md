# Plugins

> The admin and member surfaces for MCP servers and OpenAPI actions, the
> Plugins pages that also host Craft apps, and the rules that decide whether a
> plugin is on in Default Chat.

**Verified against:** `a4e97fcea1` (2026-10-29)
**Edition:** CE. Craft apps and Craft availability appear only when Craft is
available. MCP approval settings do not need Craft.
Group or user restriction needs EE.

---

## User experience

- **An admin** opens the Agents & Plugins sidebar section. Admin >
  Integrations (`/admin/integrations`) lists the MCP servers and apps from
  `GET /admin/integrations`, with Name, Type, Sign-in, Access and Status, a
  kind filter, search and "Needs setup". "Add" asks for the kind (MCP server,
  OpenAPI app, app from a preset, custom app; the last two only with Craft),
  then posts the kind's form to `POST /admin/integrations`. Only a global
  action manager sees "For the organization"; everyone else adds "For me".
  Admin > Plugins (`/admin/plugins`) lists the plugins that hold integrations,
  built from the `plugins` refs of that list
  (`sections/integrations/AdminPluginsPage.tsx`). Each Organization library
  plugin has an install setting select, which a global action manager changes
  through `PUT /admin/plugins/{id}/installation-policy`. The detail page
  `/admin/integrations/[id]` has Overview, Configuration (sign-in settings and
  the organization connection) and Actions ("Default for new actions", then
  Read-only and Write actions, each Allow, Ask or Blocked).
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
preferences (`db/plugin.py:set_plugin_preferences__no_commit`).

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

**Admin flow.** `web/src/sections/integrations/IntegrationsPage.tsx` lists
integrations. `web/src/lib/integrations/hooks.ts`, `web/src/lib/integrations/svc.ts`
and `web/src/lib/integrations/types.ts` follow the integration API. The add dialog
(`sections/integrations/AddIntegrationModal.tsx`) probes an MCP URL
through `POST /admin/mcp/probe` to suggest the sign-in, and uses
`AddOpenAPIActionModal` as the schema step. The Actions tab
(`sections/integrations/IntegrationActionsTab.tsx`) is built from
`PolicyEditor` and `PolicyToggle`, which take the API values
`allow|ask|blocked`.

**Member flow.** `lib/plugins/member.ts:useMemberPlugins` reads only member
endpoints (MCP servers, tools, the user's OAuth token status and Craft apps),
never admin listings. `buildMemberPlugins` joins them into one list and drops
tools whose `Tool.enabled` is false. Its `mcpConnection` and `openAPIConnection` helpers classify
each plugin as connected (with an owner: user, workspace, session or none),
needing OAuth, needing credentials, unconfigured, checking or unavailable.

**Member OAuth.** `lib/plugins/memberConnection.ts:runMemberPluginOAuth` runs
the flow through `lib/oauth/launch.ts:launchOAuth`: a new tab on the web, the
system browser in the desktop app. It waits for the provider callback page to
report the OAuth `state`. The attempt ends on completion, on cancel, or after
ten minutes. The caller then checks the saved connection before it reports
success. `/app/plugins/oauth/complete` is only the landing page for a callback
that no waiting page closed; it checks the saved connection and shows the
result.

**Default Chat at turn time.** Chat reads no tool preference row.
`integrations/chat_tools.py:build_integration_chat_tools` gives the default
assistant the integrations of each plugin the user runs (visible and enabled in
`db/plugin_access.py:load_user_plugin_states`), with the settings of its
persona 0 link. A custom agent uses each plugin of its links that the user can
see, whatever the user's on/off choice. `PATCH /tool/{id}/preferences` sets
the on/off of the plugins that hold the custom tool. On the web,
`lib/plugins/chat.ts:effectiveChatPreferredToolId` drops an unavailable preferred plugin tool in
Default Chat when the user's preference turns it off.

**Tool options of an existing chat.** The server owns them.
`lib/tools/hooks.ts:useToolConfiguration` reads them from the chat-session detail
(`tool_options`, held in the chat session store). The composer keeps built-in
tool states by tool id and plugin states by plugin id. A plugin toggle in
`ChatPluginsPopover` (`lib/plugins/chat.ts:setChatPluginEnabled`) switches the
plugin ids of the MCP server or OpenAPI tool (`plugin_ids` on the rows of the
MCP server lists and `/api/tool`). When something is off, `allowed`
names each built-in tool that is on and each plugin of the catalog that is on;
the hook reads both member catalogs (all plugins and the agent's), because the
server leaves out each plugin that the list does not name.

When a signed-in user changes tools or filters in an existing chat, the store
keeps the change as an unconfirmed edit, and the chat's save loop PATCHes
`/api/chat/chat-session/{id}/tool-options` at once with only the changed
part: `allowed` and `preferred`, or `internal_search_filters`. One request runs
at a time per chat; later edits go out together in the next one. The server
merges the fields that the body sets. The response is the stored options, or
null for a chat that stores no content, whose only copy stays in the tab. A
chat load that started before a save was confirmed does not replace the saved
copy. `flushToolOptions` resolves when the chat's save loop ends, so a caller
can wait for the saved choice. A send that creates a chat hands its
configuration to that chat's composer, which saves it. Session storage keeps
only the configuration of a chat that does not exist yet.

---

## Contracts and traps

1. `default-chat-is-persona-tool` **Default Chat for an integration is the
   install setting of its plugin.** Built-in tools are `Persona__Tool` rows on
   the default assistant. The `/admin/tool/custom` aliases map
   `default_chat_enabled` to DEFAULT
   (`server/features/tool/api.py:_set_default_chat`).
2. `default-chat-full-admin-only` **Only `FULL_ADMIN_PANEL_ACCESS` changes
   Default Chat.** `server/features/tool/api.py:_check_default_chat_permission`
   and the `/admin/default-assistant` routes enforce it. An omitted
   `default_chat_enabled` leaves the selection unchanged.
3. `default-assistant-lock` **Built-in tool writes follow the default-assistant
   lock rule.** [[agents-personas]] owns that rule. On the web,
   `web/src/lib/agents/hooks.ts:enqueueDefaultAssistantSave` orders saves from
   every hook instance.
4. `missing-preference-means-enabled` **A missing preference row means
   enabled.** Both preference tables default to true. Preferences apply only to
   Default Chat and Craft; custom agents ignore them.
   `server/features/tool/api.py:update_tool_user_preferences` sets the
   user's choice on the plugins that hold the custom tool.
   Craft no longer reads `enabled_in_craft`: the sandbox proxy and the Craft
   MCP config use the integrations of the plugins the user runs
   (`integrations/craft.py:list_runnable_integrations`).
5. `openapi-enabled-default-chat-only` **OpenAPI tools use `Tool.enabled` only
   for Default Chat.** `server/features/tool/models.py:CustomToolCreate`
   rejects `enabled=false`. A row stored with `enabled=false`
   stays off in Default Chat (the upgrade leaves it out of the persona 0
   plugin links) but works on custom agents. Selecting it for Default Chat sets it to true
   (`backend/onyx/db/persona.py:_attach_default_chat_tools__no_commit`). MCP
   and built-in tools stay attached when disabled, and construction skips them.
6. `discovery-does-not-select` **Tool discovery writes only actions.**
   A refresh (`backend/onyx/integrations/service.py:refresh_actions__no_commit`)
   never writes `Persona__Tool` or agent settings. A new action follows the
   admin default row and the agent's `default` setting.
7. `no-workspace-enable-from-url` **A URL never turns an integration on.**
   Only the admin's Enabled switch on the Overview tab (`PATCH
   /admin/integrations/{id}` with `enabled`) changes it. A query flag alone must
   never enable tools for the whole workspace.
8. `connection-status-is-credential-state` **`connection_status` is credential
   state, not a UI decision.** It is `not_connected`, `connected` or
   `reauth_required`, and null only without a user. Whether a Connect action
   exists comes from `web/src/lib/mcp/auth.ts:getMcpAuthenticationFlow`.
   Admin-performed OAuth or API-token servers have no member flow.
9. `member-directory-no-admin-endpoints` **The member directory must not call
   admin endpoints.** A scoped manager or a member cannot read them, and Craft
   app admin records are for full admins only.
10. `old-admin-routes-redirect` **Old admin plugin URLs only redirect.**
    `redirects()` in `web/next.config.js` sends `/admin/mcp-actions*`,
    `/admin/openapi-actions`, `/admin/craft/apps` and
    `/admin/plugins/{mcp,openapi,external-app}/[id]` to `/admin/integrations`.
    A server, tool or app id is not an integration id, so they go to the list,
    not a detail. New links go to `/admin/integrations`.
11. `action-policies-mcp-and-craft` **Action policies apply to Craft and to MCP
    and OpenAPI tools in Chat.** The Allow, Ask and Blocked
    settings in the plugin editors go to the Craft proxy
    ([[craft-external-apps]]) and to the chat approval gate
    ([[mcp-and-custom-tools#chat-approval-needs-waiting-client]]).
    `integrations/chat_tools.py:build_integration_chat_tools` gives each
    integration tool, `CustomTool` too, the approval scope of an Ask action and
    leaves out a Blocked action. The Actions tab
    (`web/src/sections/integrations/IntegrationActionsTab.tsx`) shows the
    policies with or without Craft, and so does the "Users Can Save Always
    Allow" switch on the Configuration tab. The member approval
    tab (`sections/plugins/MemberPluginDetailModal.tsx`) shows for a connected
    MCP server whose `users_can_manage_policies` is on, with or without Craft.
    It reads and writes
    `/action-policies/integration/{id}` (`server/features/integrations/api.py`),
    which checks plugin visibility but not Craft. The Craft catalog list
    (`/build/action-policies`) and task choices cover the integrations of the
    plugins the user runs (`integrations/craft.py:list_task_plugin_views`). The
    plugin UI must not show
    read or write badges to members.
12. `shared-oauth-config-shared-connection` **OpenAPI tools that shared an
    `OAuthConfig` before the upgrade have one connection each.** The migration
    copies the user's token to the integration of each tool. A member who
    connects or disconnects one such plugin changes only that plugin. On a
    provider that rotates refresh tokens, the other copies go to Needs
    reconnect after the first refresh. An expired grant needs a new sign-in
    only when the token status has `can_refresh` not true
    (`lib/plugins/member.ts`).

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

- `integration-kind-form` **An add form for a new integration kind.** Add the
  shape to `IntegrationShape` in `web/src/lib/integrations/types.ts`, its
  `config` to `IntegrationConfig`, and a branch in
  `web/src/sections/integrations/AddIntegrationModal.tsx:config`. Add its label under
  `admin.integrations.shape` in all nine locales.
- `plugin-kind` **A plugin kind.** Copy the `openapi` kind; list the kinds in
  `PluginReference` in `web/src/lib/plugins/types.ts`. Extend the `MemberPlugin`
  union and its connection helper in `web/src/lib/plugins/member.ts`. Decide whether it is a Chat kind
  (`ChatPluginReference`).
- `mcp-auth-type-ui` **The UI for a new MCP auth type.** Copy the `API_TOKEN`
  branches in `web/src/lib/mcp/auth.ts:getMcpAuthenticationFlow`, the
  `mcpConnection` helper in `web/src/lib/plugins/member.ts`, and the sign-in
  fields in `web/src/sections/integrations/signIn.ts`.
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
- Backend: `backend/tests/external_dependency_unit/integrations/test_integrations_api.py`,
  `backend/tests/external_dependency_unit/integrations/test_plugin_settings_api.py`
  and `backend/tests/integration/tests/integrations/test_integrations_api.py`.
- Playwright: `web/tests/e2e/mcp/`, which covers Default Chat.
- By hand, enable a server for Default Chat from the plugin page and confirm
  that Admin > Chat Preferences shows its tools selected. Then turn it off as a
  member and confirm that a custom agent with the server still uses it.
