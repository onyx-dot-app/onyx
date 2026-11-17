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
  `/admin/integrations/[id]` has Overview (name, description, switch),
  Configuration (sign-in settings, the preset account settings and the
  organization connection) and Actions ("Default for new actions", then
  Read-only and Write actions, each Allow, Ask or Blocked). The tabs stay
  mounted, so a tab switch keeps a draft. The Configuration Save sends the
  sign-in fields only when they changed, because the backend replaces each
  one it gets.
- **A full admin turns a plugin on for Default Chat.** Default Chat is the chat
  with no custom agent. The switch on the plugin and the tool list in Admin >
  Chat Preferences change the same selection, so a change in one shows in the
  other. A scoped action manager can edit a plugin but cannot change Default
  Chat. When a server needs sign-in, enabling it opens authentication first.
  If sign-in fails or is cancelled, the tools stay off.
- **A member** opens Plugins (`/app/plugins`) from the sidebar or the
  composer's Actions menu: one list of custom-skill plugins and plugins that
  hold integrations, in Organization library, My uploads and Shared with you,
  with All, Skills and Integrations filters and search. A plugin page
  (`/app/plugins/[pluginId]`) has Overview, Skills, Integrations and Versions;
  a tab with nothing to show is hidden. The Integrations tab shows one status
  per integration: Connected, Not connected (Connect), Needs reconnect (the
  reason and Reconnect) or Not set up ("Ask your admin"). When the admin lets
  users save it, each action that asks offers "Always allow". A member with
  manage:actions adds a personal integration ("For me" only); its plugin goes
  to My uploads. The Overview tab has the user's on/off switch ("Use this
  plugin"), off with a reason when the plugin is Required. The owner of a
  private plugin that holds only integrations gets Share and Publish; Publish
  is off for a user without global manage:actions.
- **In chat**, the tools popover lists the current agent's plugins that hold
  integrations and switches each one; the choice is saved for the agent. An
  "integrations need sign-in" prompt lists the integrations of the plugins
  that are on and need the user to connect. An integration with no usable
  credential gives the model no action, so the user can keep chatting.

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

**Member flow.** `web/src/sections/plugins/MemberPluginsPage.tsx` and
`web/src/sections/plugins/MemberPluginDetailPage.tsx` read only member endpoints: the user's skills
(`GET /skills`, as the Skills page) and `GET /integrations`.
`lib/plugins/directory.ts:memberPluginEntries` joins them by plugin id (a
custom skill's id is its plugin id). The API decides which plugins the user
sees, and each ref's `installation_policy` is the user's own setting (group
overrides and shares included). `lib/plugins/directory.ts:pluginSwitch` gives
the switch state, locked for Required: a skill plugin uses `PUT /skills/{id}/enabled`, a plugin that holds only
integrations `PUT /plugins/{id}/enabled`. `sections/plugins/SharePluginModal.tsx`
reads and replaces the shares through `/plugins/{id}/access`.
`sections/plugins/IntegrationConnectionRow.tsx` shows the
status of one integration and its action; the API key form
(`web/src/sections/plugins/IntegrationCredentialsModal.tsx`) is made from `credential_fields` and
`PUT /integrations/{id}/connection`; Disconnect is `DELETE` on the same path.
`web/src/sections/plugins/AlwaysAllowList.tsx` reads and writes `/action-policies/integration/{id}`.

**Member OAuth.** `lib/integrations/connect.ts:connectWithOAuth` calls
`POST /integrations/{id}/oauth/start` (`organization: false`, the page as
`return_path`) through `lib/oauth/launch.ts:launchOAuth`: a new tab on the
web, the system browser in the desktop app. When the browser blocks the tab,
it loads the provider in the same tab. Each redirect URI
(`/craft/v1/apps/oauth/callback` for presets, `/oauth-config/callback` for
manual clients, `/mcp/oauth/callback` for MCP) renders
`sections/oauth/IntegrationOAuthCallback.tsx`. It posts `{code, state}` to
`POST /integrations/oauth/callback`, reports to the waiting tab, and goes to
`return_path` (a path of this app) or `/app/plugins`.

**Default Chat at turn time.** Chat reads no tool preference row.
`integrations/chat_tools.py:build_integration_chat_tools` gives the default
assistant the integrations of each plugin the user runs (visible and enabled in
`db/plugin_access.py:load_user_plugin_states`), with the settings of its
persona 0 link. A custom agent uses each plugin of its links that the user can
see, whatever the user's on/off choice. `PATCH /tool/{id}/preferences` sets
the on/off of the plugins that hold the custom tool. The member routes send that choice as
`enabled` on each plugin ref, and the chat popover of the default agent shows
only the plugins that are on. On the web,
`lib/plugins/chat.ts:effectiveChatPreference` names a built-in tool of the agent,
else a saved plugin action (`tool_options.preferred` with `type: "action"`)
whose plugin is on. The web has no control that sets an action preference; it
keeps one that another client saved, and pinning a built-in tool releases it.

**Tool options of an existing chat.** The server owns them.
`lib/tools/hooks.ts:useToolConfiguration` reads them from the chat-session detail
(`tool_options`, held in the chat session store). The composer keeps built-in
tool states by tool id and plugin states by plugin id. The plugins are the
agent's (`lib/plugins/hooks.ts:useAgentPluginIds`): `GET /plugins/agents/{id}`
(`integrations/plugin_settings.py:agent_plugin_ids`) returns the plugins that
chat tool construction reads (`integrations/policy.py:agent_plugin_settings`). A failed read
leaves the list null, not empty, so the composer never sends an allow-list
that leaves out every plugin. The agent viewer passes its own agent id, and
the composer reads and saves that agent's plugins. A switch in
`ChatPluginsPopover` calls `setPluginEnabled`, which also saves the agent's
`disabled_plugin_ids` (`lib/plugins/hooks.ts:useAgentPluginPreferences`,
`PATCH /user/assistant/{id}/preferences`); a chat that does not exist yet
starts from them. When something is off, `allowed` names each built-in tool
that is on and each plugin of the agent that is on, because the server leaves
out each plugin that the list does not name.
`sections/plugins/IntegrationConnectPrompt.tsx` is the chat connect prompt.

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
   exists comes from `web/src/lib/integrations/connect.ts:connectAction`.
   An integration with one organization account has no member flow.
9. `member-directory-no-admin-endpoints` **The member directory must not call
   admin endpoints.** A scoped manager or a member cannot read them. The only
   admin route on the page is the add dialog's `POST /admin/integrations`,
   shown only with manage:actions.
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
    Allow" switch on the Configuration tab. The member "Always allow" list
    (`sections/plugins/AlwaysAllowList.tsx`) shows for an integration whose
    `users_can_save_always_allow` is on and offers the switch only for an
    action whose admin policy is Ask. It reads and writes
    `/action-policies/integration/{id}` (`server/features/integrations/api.py`),
    which checks plugin visibility but not Craft. The Craft catalog list
    (`/build/action-policies`) and task choices cover the integrations of the
    plugins the user runs (`integrations/craft.py:list_task_plugin_views`). The
    plugin UI must not show
    read or write badges to members.

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
- `mcp-auth-type-ui` **The UI for a new MCP auth type.** Add the admin sign-in
  fields in `web/src/sections/integrations/signIn.ts`, the method to
  `connectAction` in `web/src/lib/integrations/connect.ts`, and a branch in
  `web/src/sections/plugins/IntegrationConnectionRow.tsx:connect`. The Craft
  connect card (`web/src/app/craft/components/setup-requests/SetupCard.tsx`)
  signs in with the `integration_id` of `GET /build/apps`.
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
- Playwright: `web/tests/e2e/mcp/`: the default agent, connecting from a
  plugin page and from the chat prompt (API key and OAuth), and plugin access.
