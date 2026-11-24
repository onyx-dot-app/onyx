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
  `GET /admin/integrations`, with Name (and the owner of a private one, or the
  "No access" reason for a manager with no access of its own), Type, Sign-in,
  Install Setting and Status, a type filter, search and "Needs setup". "Add" opens `/admin/integrations/new`
  (`/app/customize/integrations/new` from Customize): MCP Server, OpenAPI App
  or App (only with Craft; Start From is a preset or Custom app), then posts
  to `POST /admin/integrations`. Only a global
  action manager sees "For the organization"; everyone else adds "For me".
  The install setting select (`sections/integrations/IntegrationInstallSetting.tsx`,
  in the list and on the Overview tab) is the company setting; a global action
  manager changes it through `PUT /admin/integrations/{id}/installation-policy`.
  Not available keeps the integration private: its owner and its shares use it.
  There is no admin Plugins page: a plugin holds skills only. Group Access on
  the Overview tab (`sections/integrations/IntegrationGroupAccess.tsx`, reusing
  `SkillGroupAccess`) sets a group install setting through
  `PUT /admin/integrations/{id}/group-settings`; only a global action manager
  sees it. The member list shows an integration with a group setting as No
  access to a user outside those groups, below the usable ones; a private
  integration stays hidden. The detail page
  `/admin/integrations/[id]` has Overview (name, description, owner, install
  setting, switch),
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
- **A member** opens Customize (`/app/customize`, sidebar "Customize"; `/app/plugins`,
  `/app/plugins/[id]` and `/craft/v1/plugins` redirect here with their query in
  `web/next.config.js`). It has three path tabs: Skills (first, and where
  `/app/customize` opens), Integrations and Plugins (`/app/customize/plugins`). Plugins lists each plugin of
  `lib/plugins/directory.ts:memberPluginEntries` in the groups Created by you
  (the user's own, published or not), From your organization and Shared with you
  (`lib/customize/plugins.ts:groupPlugins`), with its skill count, Turn on and a
  row menu (Turn on/off, Share). The list leaves out skill-kind entries (one
  SKILL.md at the bundle root; they are on Skills), and an admin's list
  leaves out the plugins that are not `member_visible`. The plugin page
  (`sections/plugins/MemberPluginDetailPage.tsx`) has Share, a "..." menu
  (Upload New Version through `sections/modals/plugins/UploadPluginFlow.tsx`,
  Delete Plugin) and the switch in its header. A needed integration that is
  not added links an organization-wide manager to `/admin/integrations/new`
  with the owner set to the organization and `return_to` the plugin page. A plugin holds custom skills only; there is no
  "Add integration" in its Add menu. Integrations
  (`sections/customize/CustomizeIntegrationsPage.tsx`) is a table: Integration,
  Type, Authorization and Status. Status shows the one row state of
  `access.state` (`sections/customize/IntegrationAccessControls.tsx`): On and
  Turn on are the user's switch (`PUT /integrations/{id}/enabled`, locked when
  Required), Sign in adds Connect, No access and Turned off show the reason.
  `GET /integrations` returns the integrations the user can use, then each
  one an admin made available only to groups the user is not in. Those come
  as No access rows with no configuration, connection or owner
  (`integrations/service.py:_no_access_views`), and the page lists them last
  without a link. A private integration stays hidden. A user who manages a private
  integration (`access.can_manage`) gets a "..." menu with Share
  (`sections/plugins/ShareIntegrationModal.tsx`: specific people, groups in
  EE, no permission picker, `PUT /integrations/{id}/access`) and Publish to Org
  (`POST /integrations/{id}/publish`, off without global manage:actions). A row opens
  `/app/customize/integrations/[id]` (`sections/customize/CustomizeIntegrationPage.tsx`):
  the status, Connect and the "..." menu in the header, then Overview (type,
  sign-in, owner, state, and the "Use This Integration" switch),
  Configuration (the user's connection, Disconnect)
  and Actions (each action with the admin's Allow, Ask or Blocked, and the
  user's Always allow switch when the admin allows it). The admin sets the
  policy only on `/admin/integrations/[id]`. A plugin that holds one skill
  opens that skill's page. When the admin lets users save it, each action that asks offers
  "Always allow". A member with manage:actions adds a private integration
  ("For me" only) from the Integrations Add menu.
- **In chat**, the tools popover lists the current agent's integrations
  (`sections/plugins/ChatIntegrationsPopover.tsx`) and switches each one; the
  choice is saved for the agent. An "integrations need sign-in" prompt lists
  the integrations that are on and need the user to connect. An integration with no usable
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
and `web/src/lib/integrations/types.ts` follow the integration API. The add page
(`sections/integrations/AddIntegrationPage.tsx`, at `/admin/integrations/new`
and `/app/customize/integrations/new`) probes an MCP URL
through `POST /admin/mcp/probe` to suggest the sign-in, and opens
`AddOpenAPIActionModal` for the schema. Its App type is the `preset` and
`custom` shapes: a preset fills the name and sign-in, and "Custom app" sends
`custom`. The Actions tab
(`sections/integrations/IntegrationActionsTab.tsx`) is built from
`PolicyEditor` and `PolicyToggle`, which take the API values
`allow|ask|blocked`.

**Member flow.** `web/src/sections/customize/` (the three tabs, in
`CustomizeLayout`) and `web/src/sections/plugins/MemberPluginDetailPage.tsx`
read only member endpoints: the user's skills
(`GET /skills`, as the Skills page) and `GET /integrations`.
`lib/plugins/directory.ts:memberPluginEntries` makes one plugin of each custom
skill (a custom skill's id is its plugin id). `GET /skills` also lists
uploaded plugins: each row has `kind` (`skill` or `plugin`) and
`available_count` of `needed_count` integrations. `GET /skills/{id}` adds
`plugin`: the skills, the plugin.json fields and the needs with their state
for the user ([[skills#plugin-upload]]). A plugin row shows "N of M
integrations available"; a `kind: plugin` page reads `GET /skills/{id}`
(`lib/plugins/hooks.ts:usePluginDetail`) for its Skills and Integrations tabs
and does not redirect to the skill page. A `kind: plugin` row opens this page
from the admin skills table too, and the skill page redirects a `kind: plugin`
id here. `sections/plugins/PluginNeedList.tsx`
shows each need: `lib/plugins/needs.ts:liveNeedState` reads the state of the
matched integration from `GET /integrations`, so a row follows a switch or a
sign-in at once, and `needAction` maps the state to one action (Turn on,
Connect, Add for your team with `newIntegrationHref` filling the Add page, or a
note). `lib/plugins/directory.ts:pluginSwitch` gives its switch
(`PUT /skills/{id}/enabled` through `lib/skills/hooks.ts:useSkillEnablement`,
so a skill name conflict asks to switch in `SkillSwitchModal`); when the response leaves a supported need not
on, `sections/modals/plugins/PluginTurnOnModal.tsx` lists the needs. Each integration row carries `access`; its
`installation_policy` is the user's own setting (group settings and shares
included). `sections/plugins/ShareIntegrationModal.tsx` reads and replaces the
shares through `/integrations/{id}/access`; it reuses `AddPeoplePicker` with
no permission menu.
`sections/plugins/IntegrationConnectionRow.tsx` shows the
status of one integration and its action; the API key form
(`web/src/sections/plugins/IntegrationCredentialsModal.tsx`, which the Craft
setup card also opens) renders `CredentialFieldInputs` from `credential_fields`
and calls `PUT /integrations/{id}/connection`; Disconnect is `DELETE` on the same path.
`web/src/sections/plugins/AlwaysAllowList.tsx` reads and writes `/action-policies/integration/{id}`.

**Required gate.** `sections/integrations/RequiredIntegrationGate.tsx`, mounted
in `app/app/layout.tsx`, `app/craft/v1/layout.tsx` and `app/nrf/layout.tsx` (the Chrome
extension new tab and side panel), covers the page while `lib/integrations/connect.ts:requiredSignIns` returns rows: the user's
`access.installation_policy` is REQUIRED, `access.state` is `sign_in`, and
`connectAction` is not null. An integration only an admin can fix never blocks.
Each row reuses `IntegrationConnectButton` and shows `status.reason` when it needs a reconnect. A row
stays after it connects (`status.state` is `connected`), and a count shows how many
rows are connected. A row that stops being required with no connection leaves the
gate. Continue opens when no row needs a sign-in. An admin can continue at once; the
choice is kept in `sessionStorage` for the browser tab. After a member's
connect attempt fails or is abandoned (`IntegrationConnectButton` `onConnectFailed`:
an OAuth error or cancel, or the credentials modal closed), the gate shows an
"ask your admin" line and Skip for now, which uses the same `sessionStorage` key. The gate renders nothing for
an anonymous user, until the first `GET /integrations` succeeds (a failed refresh
keeps the last list), and on an OAuth callback path
(`lib/oauth/desktopCallback.ts:isOAuthCallbackPath`), so a sign-in can finish.
`lib/oauth/launch.ts:launchOAuth` cancels an attempt when this page has focus and the
sign-in tab is closed (checked on focus and every second), so the Connect button resets.
The gate is UI only: the chat API does not check Required integrations.

**Member OAuth.** `lib/integrations/connect.ts:connectWithOAuth` calls
`POST /integrations/{id}/oauth/start` (`organization: false`, the page as
`return_path`; the admin Configuration tab passes `organization: true`) through `lib/oauth/launch.ts:launchOAuth`: a new tab on the
web, the system browser in the desktop app. When the browser blocks the tab,
it loads the provider in the same tab. Each redirect URI
(`/craft/v1/apps/oauth/callback` for presets, `/oauth-config/callback` for
manual clients, `/mcp/oauth/callback` for MCP) renders
`sections/oauth/IntegrationOAuthCallback.tsx`. It posts `{code, state}` to
`POST /integrations/oauth/callback`, reports to the waiting tab, and goes to
`return_path` (a path of this app) or `/app/customize/integrations`.

**Default Chat at turn time.** Chat reads no tool preference row.
`integrations/chat_tools.py:build_integration_chat_tools` gives the default
assistant each integration that is on for the user
(`db/integration_access.py:load_user_integration_states`), with the settings
of its persona 0 link. A custom agent uses each integration of its links that
the user has access to, whatever the user's on/off choice. The plugin of a
link gives no access; its id only names the integration
([[mcp-and-custom-tools#access-grants-default-chat-only]]).
`PATCH /tool/{id}/preferences` sets the user's on/off choice on the
integration of the custom tool. The member routes send that choice as
`access.user_enabled`, and `GET /integrations/agents/0` lists only the
integrations that are on. On the web,
`lib/tools/chat.ts:effectiveChatPreference` names a built-in tool of the agent,
else a saved integration action (`tool_options.preferred` with `type: "action"`
and `integration_id`) whose integration is on. The web has no control that sets an action preference; it
keeps one that another client saved, and pinning a built-in tool releases it.

**Tool options of an existing chat.** The server owns them.
`lib/tools/hooks.ts:useToolConfiguration` reads them from the chat-session detail
(`tool_options`, held in the chat session store). The composer keeps built-in
tool states by tool id and integration states by integration id. The
integrations are the agent's (`lib/integrations/hooks.ts:useAgentIntegrationIds`):
`GET /integrations/agents/{id}`
(`integrations/access.py:agent_integration_ids_for_user`) returns the integrations that
chat tool construction reads (`integrations/policy.py:agent_link_settings_by_integration`). A failed read
leaves the list null, not empty, so the composer never sends an allow-list
that leaves out every integration. The agent viewer passes its own agent id,
and the composer reads and saves that agent's integrations. A switch in
`ChatIntegrationsPopover` calls `setIntegrationEnabled`, which also saves the
agent's `disabled_integration_ids`
(`lib/integrations/hooks.ts:useAgentIntegrationPreferences`,
`PATCH /user/assistant/{id}/preferences`); a chat that does not exist yet
starts from them, and so does an existing chat whose `allowed` is null. When something is off, `allowed` names each built-in tool
that is on and each integration of the agent that is on (`{type: "integration",
integration_id}`), because the server leaves out each integration that the
list does not name.
`sections/plugins/IntegrationConnectPrompt.tsx` is the chat connect prompt. It
reads the integration statuses again when the user opens it. A tool sign-in
card (`web/src/app/app/message/messageComponents/CustomToolAuthCard.tsx`) also reads them again; a turn does not.

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

1. `default-chat-is-persona-tool` **Default Chat for an integration is its
   company install setting** (`integration.installation_policy`). Built-in
   tools are `Persona__Tool` rows on the default assistant. The
   `/admin/tool/custom` aliases map `default_chat_enabled` to DEFAULT
   (`server/features/tool/api.py:_set_default_chat`).
2. `default-chat-full-admin-only` **Only `FULL_ADMIN_PANEL_ACCESS` changes the
   built-in tools of Default Chat.**
   `server/features/tool/api.py:_check_default_chat_permission` and the
   `/admin/default-assistant` routes enforce it. An omitted
   `default_chat_enabled` leaves the selection unchanged. Integrations reach
   Default Chat another way: an organization-wide action manager sets an
   install setting of Installed or Required, for the company or a group
   (`PUT /admin/integrations/{id}/installation-policy` and `.../group-settings`),
   and each user's on/off choice applies.
3. `default-assistant-lock` **Built-in tool writes follow the default-assistant
   lock rule.** [[agents-personas]] owns that rule. On the web,
   `web/src/lib/agents/hooks.ts:enqueueDefaultAssistantSave` orders saves from
   every hook instance.
4. `missing-preference-means-enabled` **A missing preference row means
   enabled.** Both preference tables default to true. Preferences apply only to
   Default Chat and Craft; custom agents ignore them.
   `server/features/tool/api.py:update_tool_user_preferences` sets the
   user's choice on the integration of the custom tool
   (`user_integration_preference`).
   Craft does not read `enabled_in_craft`: the sandbox proxy and the Craft
   MCP config use the integrations that are on for the user
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
    `/admin/openapi-actions`, `/admin/craft/apps`, `/admin/plugins` and
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
    user has on (`integrations/craft.py:list_task_integration_views`). The
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
  `web/src/sections/integrations/AddIntegrationPage.tsx:config`. Add its label under
  `admin.integrations.shape` in all nine locales, and its icon to
  `INTEGRATION_SHAPE_ICONS` in `web/src/sections/integrations/integrationLabels.ts`.
- `mcp-auth-type-ui` **The UI for a new MCP auth type.** Add the admin sign-in
  fields in `web/src/sections/integrations/signIn.ts`, the method to
  `connectAction` in `web/src/lib/integrations/connect.ts`, and a branch in
  `web/src/sections/plugins/IntegrationConnectButton.tsx:connect`. The Craft
  connect card (`web/src/app/craft/components/setup-requests/SetupCard.tsx`)
  signs in with the integration id of the member list (`GET /integrations`).
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
  `backend/tests/external_dependency_unit/integrations/test_integration_access_api.py`
  and `backend/tests/integration/tests/integrations/test_integrations_api.py`.
- Playwright: `web/tests/e2e/mcp/`: the default agent, connecting from a
  plugin page and from the chat prompt (API key and OAuth), plugin access, and
  Always allow (`web/tests/e2e/mcp/mcp_tool_approval.spec.ts`).
