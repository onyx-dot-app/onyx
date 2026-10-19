# MCP and Custom Tools

> How an admin gives Onyx a capability it did not ship with: connecting an MCP
> server, or defining a custom action from an OpenAPI schema. Covers admin
> configuration, credential storage and scope, the MCP OAuth flow, and how a
> schema or server becomes one or more runtime `Tool` rows.

**Verified against:** `268e4d5a3d` (2026-10-05)
**Domain:** core-loop
**Edition:** CE, with EE additions in MCP server private-sharing (`make_mcp_server_private`)
**Owns:**
`backend/onyx/db/mcp.py`, `backend/onyx/db/oauth_config.py`,
`backend/onyx/server/features/mcp/` (`api.py`, `client.py`, `client_metadata.py`,
`credentials.py`, `models.py`, `oauth.py`, `oauth_flow.py`, `ssrf.py`),
`backend/onyx/tools/tool_implementations/mcp/mcp_tool.py`,
`backend/onyx/tools/tool_implementations/custom/` (`custom_tool.py`,
`openapi_parsing.py`, `base_tool_types.py`), `backend/onyx/oauth/`,
`web/src/app/admin/plugins/`, `web/src/app/admin/mcp-actions/`, `web/src/app/admin/openapi-actions/`,
`web/src/sections/plugins/`, `web/src/sections/actions/`, `web/src/lib/plugins/`, `web/src/lib/mcp/`

**Read first:** `[[tools-framework]]`. It owns the `Tool` interface, the
three-way discriminator on the `Tool` table, and `tool_constructor.py`'s
per-turn assembly loop. This document owns everything upstream of that loop:
how an admin creates the `Tool` row and its associated `MCPServer` /
`MCPConnectionConfig` / `OAuthConfig` rows in the first place.

---

## 1. What the user experiences

An admin who wants Onyx to call an outside system has two paths, both under
Admin > Plugins.

The Plugins directory combines permission-stamped MCP servers, OpenAPI schemas,
and full-admin-only external apps. External-app admin records are never fetched
for scoped action managers. Add opens a type dropdown. MCP opens its suggested
server catalog; OpenAPI opens creation directly; App opens its provider catalog.
Provider options load only after a full admin chooses App.
The App catalog reads installed apps through the same native SWR key. Failed
installed-app reads show retry rather than an endless loader. Custom app
editing does not request provider options. Loading and error routes retain
the modal shell and close control.
Plugin setup and editors share `PluginModalContent` for medium, top-anchored
forms. MCP and Craft App catalogs use standard top-anchored Opal `Modal.Content`
with its two-tone body. Both use `PluginCatalogCard` for suggested/provider
and custom choices. There is no separate custom-app footer.
Craft App setup editors share a combined Configuration/credentials pane, with
Permissions and Skills tabs only where supported. Their logo/name headers,
fixed-height scroll panes, and bottom save rows match plugin editor patterns.
Each row retains its native resource and a kind-qualified identity. Search matches names,
descriptions, and MCP server URLs. Independent loading and retry states keep one source's
failure from hiding the other sources. The unified list uses compact two-column
rows on wider screens and one column on narrow screens.
Admin and member directories share `PluginDirectoryToolbar`: filters, when
present, sit before the search field. Add and Manage workspace plugins use
the header action slot, matching Agents and Skills. Both use the same
heading/description layout and responsive toolbar sizing.
Admin filters use the member directory's compact pill-button layout: All,
MCP, OpenAPI, and Craft Apps. Craft Apps appears only for full admins. Search applies
within the selected type; clearing an empty result resets both filters.
Empty-state actions say "View all plugins" and reset search and filters.
When Craft is unavailable, admin lists do not fetch Craft Apps or offer their
creation, filters, or direct-link editors. MCP indicators show Chat only.
Member defaults, Craft metadata, skills links, and Craft actions require the
member's Craft entitlement. MCP setup and admin tools retain their deployment gates.
Admin row actions sit beside the detail link in normal flex flow, without
absolute positioning or a placeholder spacer.
Availability controls use workspace enable/disable wording. Disabling an OpenAPI
plugin requires confirmation that it affects everyone, including custom agents,
while preserving its settings and credentials.
OpenAPI indicators and lifecycle actions follow global `Tool.enabled`,
independently of default Chat attachments.
The sliders action says Disable when all supported surfaces are enabled and Enable when all are disabled.
Mixed or unknown MCP states say Manage workspace availability. Disabled Craft does not affect this label.
Member OAuth opens a normal new tab, without popup sizing or window features.
The correlated callback still closes the sign-in tab and refreshes the original page.
Its completion screen uses a bounded, centered card with return and close-tab
actions. OAuth callback URLs use backend WEB_DOMAIN, which must match the web origin.

Members open `/app/plugins` from the main sidebar or the Actions menu's Plugins flyout.
The member directory uses `/mcp/servers`, `/tool`, and the caller's OAuth token
status. Craft-enabled members also see external apps from `/build/apps`.
It does not use admin listing endpoints. All, Connected, and Needs sign-in
filters distinguish account state without separating services by protocol.
Workspace credentials and no-auth services count as connected.
Loading and failed account-status checks remain distinct from missing credentials.
Connected and needs-auth cards omit the extra connection text line; the dot and
its tooltip retain account status. Setup errors and unavailable states remain visible.
Craft App cards show their Craft-only scope as a passive tag beside the
description, without adding a third line or shifting the service icon.
OpenAPI cards use the matching Chat-only tag and scope tooltip.

Member details show returned tool metadata without live discovery. Provider account
emails and granted scopes are not available in these responses. The UI does not
invent them. Personal disconnect removes only the caller's credentials. OpenAPI
tools sharing an OAuth configuration also share the caller's connection.
Expired OpenAPI grants require sign-in when `can_refresh !== true`.
Authoritative refresh capability keeps the connection available despite expiry.
Main-app MCP details use the shared modal shell with Connection and Tools tabs.
The Tools tab uses a searchable read-only list. Tool names and descriptions are
searchable; compact rows match the admin list's main-ui typography, padding, and
border treatment. Descriptions expand through the shared Fold without truncation.
The server URL appears once in the modal header, not in a second metadata row.
Craft App details use that row for safe service origins from the member `service_urls` response.
Missing origins omit the URL. Member details never fetch admin app records or show URL patterns.
MCP connection status appears beside that URL: green when connected, orange when
sign-in is needed, and gray for unavailable states. The Connection tab has no
duplicate status row; personal account disconnect remains a separate action.
Expanded tool descriptions reuse the compact Opal Code block, preserving raw
text and line breaks in a height-capped scroll region with copy support.
Admin and member tools both render `web/src/sections/plugins/MCPToolRow.tsx`.
Admin enable/policy controls use its control slot and do not toggle disclosure.
Read-only users can still expand descriptions without editing tool settings.
No refresh component is modified for this view.
Both panes share
a viewport-capped height and scroll internally, keeping the header and footer
stable. Cancelling account disconnect returns to the selected tab. Craft keeps
its connection-only view because it does not fetch the main-app tool catalog.

`web/src/lib/plugins/member.ts` owns the native MCP/OpenAPI/external-app union and connection
classification. `web/src/lib/plugins/memberConnection.ts` owns authorization-tab correlation,
origin and source checks, cancellation, and timeout. A nonce-scoped BroadcastChannel
also returns completion when a provider's opener policy severs the new tab's opener link.
Closing that link is not treated as proof of cancellation. The member can cancel
from the dialog; otherwise the attempt times out. Existing backend callbacks
complete OAuth before returning to `/app/plugins/oauth/complete`. That completion
page verifies the saved connection against the originating roster before notifying
the opener or BroadcastChannel. The connection caller then verifies the saved
state again before the dialog reports success.

The composer Actions menu contains a Plugins row with a right-side flyout.
It retains plugin search, connection actions, toggles, and Browse plugins.
The Actions owner keeps connection dialogs mounted after either menu closes.
The flyout reads the active agent's MCP server roster and groups
only Chat-capable kinds. External apps remain Craft-only. `/craft/v1/plugins`
uses the same member page with MCP and external apps, excluding OpenAPI.
The composer groups
only tools attached to that agent. The directory keeps using the member attach
catalog. A custom agent's attached server can remain available even when the
member cannot attach that server elsewhere.
Switches use the existing per-chat `ToolConfigurationHandle`. They cannot grant
workspace access or attach new tools to an agent. Use in Chat carries validated
`pluginKind` and `pluginId` query parameters to the existing chat owner.
Normal attached-tool defaults remain unchanged. Reconnection never automatically
repeats a failed tool call.
At send time, default Chat suppresses forced MCP/OpenAPI choices when personal
preferences disable them or member metadata is unavailable. Stored per-chat
choices remain unchanged. Custom agents and built-in forced Search retain their
existing behavior.
Full-admin OpenAPI creation and directory Enable attach the action to default
Chat through `useDefaultAssistantConfiguration`, preserving other tool selections.
An enabled action missing that attachment still offers Enable. Scoped action
managers retain status-only controls and cannot change default Chat attachments.
Successful lifecycle writes refresh member catalogs and agent rosters. Disconnect
disables the action globally but retains its agent attachments for later re-enabling.
Return-intent readiness waits for the selected resource's roster and connection
state. Non-OAuth OpenAPI tools do not wait for unrelated OAuth status requests.

Member MCP and tool listings expose `default_chat_enabled` from default-assistant
attachments. The API computes these summaries in batches. Credential submission
checks server access before reading credentials, validating them, or saving them.

Main Chat still executes MCP and OpenAPI calls without Craft approval enforcement.
Member UI does not display read/write policy badges or promise approval before writes.
Installed rows show a status control between the type label and the row menu.
MCP circles split diagonally: the upper-left half shows main Chat and the lower-right
half shows Craft. Each half uses the standard success green when enabled and
neutral gray when disabled, matching member directory indicators.
Admin indicators show workspace availability only; individual authentication
never changes their color or tooltip. Personal pages retain orange needs-auth
indicators. Tooltips show both workspace states when Craft is available.
OpenAPI dots follow the action's enabled flag.
The status control uses a compact borderless circle and a neutral two-column tooltip.
MCP Chat state comes from the admin
list's `default_chat_enabled` summary, not credential connection status.
Missing summaries use a neutral dot with a Chat unknown tooltip.

Add opens the type dropdown and then its native catalog or creation flow.
OpenAPI creation combines schema entry and live action review on the first step, then authorization.
The validated schema preview groups its service logo, name, server URL, and
description in one compact identity row, shared by creation and schema editing.
Back preserves schema and credential drafts.
Authorization supports OAuth, custom headers/API keys, pass-through when enabled, and explicit no authentication.
Only the final Add Action creates a record. Auth saves use refreshed permission-stamped rows.
Failed retries reuse the created tool ID and any newly created OAuth configuration ID.
Retry writes require a successful authoritative refresh, not SWR's cached
revalidation result. Schema and metadata writes preserve the fresh row's OAuth
ID without sending cached header or pass-through settings. Forms
retain only unlinked OAuth IDs and reuse them after failed linking. Saved
editors support No authentication. Hidden OAuth fields do not invalidate other
methods. New OAuth configurations reject blank or masked credentials.
Schema checks retain one result keyed to the current text. Request identity
blocks old responses from replacing current previews or errors, and blocks
Continue completion after unmount.
Format is disabled during submission. Lenient JSON normalization leaves quoted
text unchanged. Failed background refreshes retain cached editors and drafts;
the blocking error surface appears only without a usable selected record.
Schema drafts remain fixed for each open editor, even when saved definitions
refresh. Fresh capability loss removes write fields; a missing record restores
the fallback. Rejected saves remain visible through errors and toasts.
Schema editing remains on one step.
Review shows one divided list of actions, with method badges and endpoint paths beside each summary.
Creation and details render `web/src/sections/plugins/OpenAPIEndpointList.tsx`, keeping endpoint typography,
method badges, spacing, and responsive behavior identical.
Creation schema and authentication modals use the same top-anchored, single-tone
surface as MCP setup. Admin detail tabs embed those same forms without headers
or nested dialogs, and portal only the active form's save action to the footer.
Drafts survive tab switches. Successful inline saves clear dirty state; pending
saves block navigation. The inline Authentication Method has no divider.
Closing saved OpenAPI details confirms unsaved edits within the same modal frame.
Keeping edits preserves each mounted form. Authentication saves reject a changed
OAuth link before writing, so stale values cannot target a replacement config.
The inline Schema tab shows validation and a detected-tool count, not endpoints.
View tools selects the Tools tab; unsaved schemas must be saved first. Creation
retains its endpoint preview because it has no separate Tools tab.
Personal OpenAPI details reuse the MCP Connection/Tools tabs and URL/status
header. Tools use the shared endpoint list, search, count, and empty feedback.
Personal detail panes use a compact, fixed height across connection and
capability tabs. OpenAPI description and personal default Chat settings use
Opal content rows. The member switch persists through
`PATCH /api/tool/{tool_id}/preferences`, stored per user/tool in
`ToolUserPreference`. Missing rows mean enabled. Member snapshots stamp
`user_enabled_in_chat` separately from workspace `default_chat_enabled`.
The switch cannot override admin-disabled default Chat availability. Optimistic
cache updates roll back on failure and refresh composer/default-agent data.
Opted-out plugins remain in the directory; only default Chat excludes them.
Custom agents keep their own tool settings. Credentials are unchanged.
Personal Craft App details use Connection/Skills tabs with the same header
status, fixed scroll panes, and footer layout. They omit the duplicate account
table and header subtitle. `web/src/sections/plugins/MemberCraftAppSkills.tsx`
reads only the caller's skills, filters by external-app ID, and shows search,
count, enabled state, and loading/retry feedback. Review skills opens the
existing app-filtered skills page; no admin metadata or policies are fetched.
Craft must be enabled before skills or launch actions appear. Apps needing
authentication show Connect account instead of Open in Craft.
`web/src/sections/plugins/OpenAPIPluginCreateModal.stories.tsx` covers schema entry, review,
Back navigation, authorization choices and draft retention, invalid JSON, validation failure/pending, saving, creation failure/success,
and closing/reopening a discarded draft. Network fixtures remain local to each story.
Explore offers official remote endpoints for Slack, HubSpot, Asana, Linear, Notion,
Sentry, and Atlassian. Compact rows show a logo, regular-weight title, short summary,
and centered action. The setup modal shows registration requirements and provider setup guides.
Installed MCP endpoints are excluded from Explore, including URLs with a trailing slash.
Both views share grid spacing and row sizing. A stable scrollbar gutter keeps navigation fixed.
Selecting a suggestion fills the MCP setup URL and name. It does not create credentials
or probe every catalog entry on directory load. Skills and external apps remain separate.
The directory does not install portable plugin packages or claim a complete plugin SDK host.

**MCP server.** The admin enters a URL, reviews detected authentication, then
sets the name and access. OAuth uses individual accounts; API tokens can be
individual or shared. Servers can also use no authentication or OAuth
pass-through. Onyx connects, lists the
server's tools, and shows them as one row per tool. The admin can restrict the
server to specific users or groups, or leave it public. If the server needs a
per-user credential (a personal API key, or a personal OAuth login), each user
who wants to use it connects it themselves from the chat's MCP dropdown,
separately from the admin's setup.

Chat shows a **Tools need credentials** pill after Deep Research when an enabled
tool needs a user connection. The pill is blue when all pending connections need
first-time setup, and orange when any requires reauthentication. The modal lists actionable
connections for the current agent, including the default Onyx agent. It uses
`MCPConnectionPrompt` (`web/src/lib/mcp/components/MCPConnectionPrompt.tsx`).
Its tooltip explains that tools remain unavailable until the user connects an
account or adds credentials. Users can continue chatting without connecting.
Shared admin credentials and pass-through OAuth without user header fields do not produce a connection prompt.
Servers with required user header values can prompt with `NONE` or `PT_OAUTH`.

The credentials prompt reads persona-scoped SWR data and handles connections
through `useMcpAuthentication` in `web/src/lib/mcp/hooks.ts`.
The Plugins flyout uses member catalogs. Both flows use
`getMcpAuthenticationFlow` and the authoritative `connection_status` field.
The hook exposes credential requests and submit/cancel actions; each UI owns its modal props. Shared authentication types live in
`web/src/lib/mcp/types.ts`.
Credential submission, completed chat responses, and window focus refresh this data.
`connection_status` distinguishes `not_connected`, `connected`, and
`reauth_required`. The modal shows **Connect** for initial setup and **Reconnect**
for replacement credentials. Reconnect forces a fresh OAuth grant; successful
credential entry replaces the user's stored credentials.
The API always includes `connection_status`; it is null only without user context.
The backend records confirmed OAuth `invalid_grant` and HTTP 401 rejection of
user API tokens or required headers in the encrypted connection config. Rejections are marked
only if stored credentials still match the failed request. Expired OAuth grants
without refresh tokens also require reconnection. Temporary failures do not change
the connection state. Successful replacement credentials clear the rejection marker;
OAuth header edits and authorization attempts retain it until authorization succeeds.
A new user connection does not inherit the admin connection's rejection history.
For no-auth servers, missing required header values mean first-time setup, even
with stored headers. A confirmed rejection still requires reauthentication.
Pass-through OAuth rejection does not mark extra headers stale, since the failure
may concern the user's Onyx login token.
`connection_status` reports credential state, not whether a Connect button should appear.
The client checks supported authentication flows
with `getMcpAuthenticationFlow` in `web/src/lib/mcp/auth.ts`. It returns credential
entry, OAuth, or no supported flow. Chat authentication entry points read connection state
directly from `connection_status`.

Credential entry replaces the connection list within the same dialog.
A shared backdrop stays mounted across screens to prevent transition flashes.
**Back to tools** returns to the list. Back, close, Escape, and outside clicks
ask for confirmation before discarding edited credentials. The confirmation
replaces the form in the same dialog; keeping edits restores the entered values.
Unchanged forms can leave without confirmation. Submission blocks dismissal.
Successful credential saves return to the list with the server marked connected.
Credential fields scroll within the dialog on short screens; the submit button stays visible.
The credentials prompt's OAuth controls stay busy until navigation leaves the
page, or a request fails. The Plugins flow instead waits for its new-tab callback.


Clicking an MCP row opens a detail modal at `/admin/plugins/mcp/[serverId]`. Rows show the icon,
name, description, and integration kind. They do not expand tool lists or claim
live health. Details own configuration, authentication, tool availability, and policies.
`web/src/app/admin/plugins/layout.tsx` keeps the directory behind both MCP and OpenAPI detail modals,
including hard links and OAuth returns. Closing returns to Plugins, not browser history.

`web/src/sections/actions/MCPServerDetailPage.tsx` has three filled tabs:
Server configuration, Authentication, and Tools. All forms are inline. Tab changes
retain drafts, and route navigation asks before discarding any unsaved edits.
The `tab` query parameter links directly to each section. Saving server details
stays on that tab. Authentication saves configuration, then runs the existing
connection and tool-loading flow before opening Tools. Workspace availability and
deletion stay in the directory. Saved details show the URL beneath the name and
do not offer an endpoint input; creation still accepts a URL.
Metadata-only saves preserve existing access grants, including after a plan downgrade.
Changing restricted access still requires the applicable plan and permissions.

The Tools editor uses one divided list with aligned availability switches.
Search, enabled-only filtering, bulk actions, and refresh share a toolbar.
It has no fading rows or icon-only list footer. Save Changes stays below the list.
Craft permissions use the same toolbar, search, divided rows, typography, and
right-aligned controls. Per-tool policies appear directly without an Advanced
accordion. Bulk policy changes apply to all enabled tools, including search-hidden
tools. Without Craft, the editor omits the redundant single Available tools tab.

Authentication uses one labeled method dropdown instead of nested tabs. OAuth
client setup uses two descriptive radio choices. API-key sharing uses a Credentials
dropdown. Recommended tags stay attached to detected defaults. Headers, transport,
and manual OAuth endpoints remain under Advanced settings.

New servers open a modal from Plugins, rendered by
`web/src/sections/actions/modals/MCPPluginSetupModal.tsx`. The modal has one continuous surface without a timeline. Footer buttons own navigation.
Server contains name and URL inputs. Description remains editable on the server detail page.
Connection combines authentication and access.
Both steps use the same content insets. The footer uses an explicit Back button.
Closing MCP or OpenAPI creation discards the local draft immediately, without confirmation.
Directory and catalog rows share horizontal padding. Suggested rows are keyboard-accessible cards.
An entered name is preserved; an empty name is filled from detection. A valid URL
starts `POST /admin/mcp/probe` after 700 milliseconds without another URL edit.
The NDJSON stream reports Contacting server, then Detecting authentication.
A real MCP initialization or authentication challenge completes contact. Authentication
completes after tools load anonymously or OAuth metadata resolves. Unknown authentication
fails that row. Unreachable servers fail contact and leave authentication waiting.
Closing the stream cancels its probe task. Detection rows remain visible before Continue. The modal discards
responses for an earlier URL and never advances automatically.
The credential-free check initializes MCP and lists tools through Streamable HTTP,
then tries compatible SSE. It uses the shared SSRF guard, bounded timeouts, and
public OAuth metadata. It never executes tools or registers OAuth clients.
Anonymous success recommends no authentication. OAuth metadata from a challenge
recommends individual OAuth, with automatic client setup when supported.
Recommended tags identify detected authentication and supported automatic client setup.
The tags remain on those defaults when the admin selects another option.
Unknown authentication leaves the method unselected until the admin chooses it.
Connection failures keep the first form open without creating a server. Retry
checks the URL again. Configure manually lets an admin supply headers or transport
settings when the connection check fails. Blocked destinations have no bypass.
Continue opens Connection without database writes. Connection contains authentication,
client setup, custom headers, and advanced transport settings. Continue validates
authentication and access on the Connection step. The name remains editable on the Server step.
Public server metadata supplies
the suggested name. Other servers use the URL hostname. Connect saves details and
access, then saves authentication and starts the connection flow. Failed retries
reuse the saved server ID and update its details. Back and Continue retain drafts for an
unchanged URL. A changed URL clears credentials and checks the endpoint again.
Existing edit pages do not probe or replace saved authentication settings.
Creation does not register an unsaved-draft navigation guard. Existing edit pages retain their guards.
There is one production creation flow. The removed legacy wrapper is not kept
for tests or stories. Authentication prepares and validates its payload before
resolving a new server. Its form owner retains explicit OAuth setup choices
when method-specific fields unmount.
Completion and OAuth return open the
server detail page.

Backend updates to a server URL clear shared and personal credentials, including
OAuth registration, and resets connection status. Authentication then starts from
the new saved server response and repeats discovery. Old credentials and masked
values are not carried to the new endpoint. Existing tool rows remain intact.

The Connection step and saved server form have an Access Control selector:
Public or User groups.
User groups uses the shared searchable group picker. Selected groups appear as
removable pills below the dropdown. The selected-group area scrolls when full.
Existing non-public servers open in
User groups mode, including servers without explicit grants. Existing direct user
grants remain visible as a retained-user count.
Switching to Public clears explicit grants. Restricted access requires
Business and the enterprise backend. Scoped managers must select at least one
managed group. These grants control attaching tools to agents; they do not change
access to custom agents that already use those tools. Default Chat still checks
server access before showing tools or resolving credentials.
`web/src/sections/actions/modals/MCPServerDetailsPage.tsx` owns the Access Control
selector and its group validation.

Each admin installed plugin row has a disconnect dropdown and a separate trash
button for deletion. Clicking its status circle opens the same availability
dropdown. Delete is not a dropdown item. Controls respect resource permissions,
and managed external apps cannot be deleted. MCP deletion confirmation names
the server and states that its tools are deleted for everyone in the organization.
Enable for main Chat opens authentication when the server needs sign-in or has no
discovered tools. Only an explicit Enable or creation Connect action records an enable intent.
`web/src/sections/actions/mcpChatEnableIntent.ts` binds the one-time record to the user, server, and origin.
The record expires after five minutes and is consumed before the workspace write.
Admin OAuth uses the same tab to retain that record. Query flags alone never enable tools.
Missing or expired records require another explicit Enable action. Successful
authentication and discovery then attach the tools to default Chat. Failed or
cancelled authentication does not attach tools to default Chat. New full-admin
setup selects discovered tools for default Chat and defaults Craft availability
on when the deployment supports Craft. OAuth setup carries the same enable intent
through its callback. The administrator uses the credentials saved by that setup.
Successful completion refreshes existing member and agent caches, so the new
connection appears without a manual reload. Ordinary reauthentication preserves
later admin disable choices. Individual member sign-ins never change org settings.
Member MCP details separate personal account connections from personal default
Chat/Craft preferences. Both switches use the same Opal InputSwitch row pattern
as admin settings and remain bounded by workspace availability. Switching off
keeps credentials. Account disconnect is a distinct Connection-tab action.
No preference row means both personal defaults are enabled. Default Chat opt-out
does not affect custom agents. Craft opt-out also applies to live proxy calls and
scheduled-task availability. Personal-disabled servers remain in member catalogs.
`MCPServerUserPreference` stores the two flags per user/server. The authenticated
`PATCH /mcp/server/{server_id}/preferences` updates only supplied fields, then
restamps that user's Craft sessions when needed. Member DTOs expose separate
`user_enabled_in_chat` and `user_enabled_in_craft` flags. The frontend updates
existing scoped SWR caches optimistically and rolls back failed saves.
The personal directory dot describes account state, not workspace availability:
green means connected, orange means credentials are needed, gray means unavailable.
Ordinary discovery of an existing server does not change availability.
MCP menus have independent Chat and Craft actions.
Organization-wide MCP disable actions show "All users in your organization"
in the menu and require confirmation. Chat confirmation explains that default
Chat changes for everyone, while custom agents remain unchanged. Craft
confirmation explains that Craft changes for everyone, while Chat is unchanged.
Enabling stays immediate. Cancelling makes no writes. Failed disables retain
the confirmation for retry. Delete and disable share one confirmation owner.
Main Chat uses the same
`Persona__Tool` selections as Admin > Chat Preferences. There is no separate
server flag or schema migration. The page reads
`GET /admin/default-assistant/configuration` and saves through
`PATCH /admin/default-assistant` with `tool_ids`. These endpoints require
`FULL_ADMIN_PANEL_ACCESS`. Other action managers cannot change the main Chat setting.
Enabling selects this server's tools; disabling removes them. Both operations
preserve selections from other servers and built-in tools. A selected subset
shows the server as available. Changes in either surface appear in the other.
The frontend sequences complete replacement writes across hook instances
sharing one SWR cache. Rejection rolls back before the next write. Different
browser clients still require backend concurrency control.
Refreshing an existing server does not select new tools automatically. Custom
agent attachments remain unchanged.

The active MCP editor's Save Changes button appears on the right of the sticky modal footer.
Detail modals contain editing controls only, with no Delete or Disconnect buttons.
OpenAPI row menus enable or disconnect the action. Delete opens a confirmation
over the Plugins directory, not over another modal.

When deployment settings enable Craft, the row menu includes a Craft action.
New servers default to enabled. Existing servers retain their saved setting.
Availability menu actions save immediately.
This uses `available_in_craft` and does not change access grants.
The simple create API accepts this flag atomically; omitted values still default
to false for other API callers.

The inline `web/src/sections/actions/MCPServerToolsEditor.tsx` has Available tools
and, when Craft is available, Craft permissions tabs. Enablement and approval policies are drafts until Save changes. Refresh is
disabled while drafts exist. Each completed save batch becomes the new baseline,
so retrying a partial failure does not repeat successful writes. Tool toggles
retain per-tool permission checks. Craft policies use raw tool names and retain
overrides for disabled tools. The shared `web/src/sections/actions/PolicyEditor.tsx`
also serves Craft's policy tab, with per-action controls always visible.
Both MCP tool views reserve equal toolbar slots and one fixed-height scrollable
list viewport. Switching tabs does not resize the dialog or shift the list.

The authentication form uses tabs for OAuth, API Key, and No authentication,
plus pass-through as the first tab when enabled. Each tab starts with the same introduction layout.
OAuth setup and API-key scope use the same filled tabs as the authentication methods.
The form separates shared authentication configuration from personal test credentials.
Plain help text between the personal API key label and input explains testing and account ownership;
there is no separate test-connection heading or icon.
Save changes on the authentication page verifies access and loads tools. OAuth uses the administrator's sign-in;
personal API tokens use the administrator's supplied credentials. Both save a personal
connection for the administrator, not a separate test-only credential. Other users
connect their own accounts. Shared API keys instead connect everyone with server access.
OAuth discovery appears only in the automatic-setup tab, with visible retry and
recovery buttons. The own-client tab contains fields without repeating discovery notices.
The modal body animates content-height changes and respects reduced-motion preferences.
OAuth first offers automatic setup or a supplied OAuth client in tabs. A read-only capability check runs when setup opens. It reads public resource
and authorization metadata without credentials, client registration, or database
writes. HTTP discovery is asynchronous. The server lookup and permission check
run in a worker thread; their database session closes before HTTP discovery.
Outbound SSRF settings and DNS checks also run outside the event loop.
The request and response schemas live in `server/features/mcp/models.py`. Confirmed lack of registration support initially selects the supplied-client path.
Users can still select automatic setup and try connecting; that tab shows discovery guidance. Missing metadata offers retry and manual
endpoints; network failures remain unknown rather than implying no support. Automatic setup
tries client registration when supported and then asks the user to sign in.
Choosing a supplied client reveals the required client ID, optional secret, and
callback URL. Endpoint discovery stays automatic by default; manual endpoint
settings are a separate choice below those fields. Switching to automatic setup
clears supplied credentials and manual endpoints when saved. Existing client
credentials open in supplied-client mode and remain unchanged unless edited;
the backend does not expose how a saved client was registered.
`backend/onyx/server/features/mcp/oauth_discovery.py` owns capability checks and
safe OAuth error classification. Blocked discovery requests return the same safe
unreachable state as connection failures. Upstream response bodies never become OAuth
setup errors. The API supplies an `oauth_error` reason for registration,
discovery, connection, or general OAuth failures; the form shows localized
messages and setup recovery actions.
Advanced settings hold transport and custom headers. The header editor appears directly
when advanced settings expand, without a second disclosure or repeated introduction. Required credential values
remain visible outside the header editor. Modal headers retain their icons and
the body uses the standard two-tone background. Connection failures remain
inside the form so the admin can correct settings and retry. Saving configuration,
signing in, and loading tools are separate stages.

The form reads fresh settings on each opening and keeps edits separate from
cache refreshes. Authentication saves use that loaded server snapshot, so stale
card metadata cannot overwrite a newer name, URL, or description.
Discovery recommendations wait for the current check and preserve explicit setup choices. `web/src/sections/actions/modals/mcpAuthForm.ts` owns initial values, header placeholders, and
request construction. `MCPOAuthFields.tsx`, `MCPApiTokenFields.tsx`, and
`MCPAdvancedFields.tsx` own their respective form sections. Shared API-key headers must
retain the `{api_key}` placeholder before saving. Changing authentication settings
clears errors from the previous attempt. Credential change flags compare against the last successful
save, including retries after failed sign-in. Unchanged masked credentials remain
unchanged in storage. An existing OAuth grant proceeds directly to tool discovery
without another browser redirect.

**OpenAPI (custom) action.** Each schema has a detail modal at
`/admin/plugins/openapi/[toolId]`. It reads the permission-stamped OpenAPI list,
not the single-tool or mutation response. Metadata saves preserve `oauth_config_id`.
Plugin details, OpenAPI schema, Authentication, and Tools use one tab row with
directly editable fields. Schema and authentication reuse the existing forms
in inline mode. A `configure=authentication` return selects authentication once,
after the authorized record loads. Lifecycle controls stay on the directory.
The admin pastes an OpenAPI 3.x schema and,
optionally, static headers. Every operation in the schema (identified by its
`operationId`) becomes its own callable action. The admin can turn on
"passthrough auth" so the tool forwards the calling user's own Onyx login
token to the third-party endpoint, instead of a static header.

Once created, either kind of tool is attached to a persona (agent) the same
way a built-in tool is, and shows up in chat as a tool call block. If the
server is down or a credential is missing, the user sees a tool-call error
inline, not a broken turn.

---

## 2. Surfaces

### Admin frontend routes

| Route | Page | Content component |
|---|---|---|
| `/admin/plugins` | `web/src/app/admin/plugins/page.tsx` | `PluginsPage` (`web/src/sections/plugins/PluginsPage.tsx`) |
| `/admin/plugins?add=mcp` | Plugins directory | `MCPPluginSetupModal` (`web/src/sections/actions/modals/MCPPluginSetupModal.tsx`) |
| `/admin/plugins/mcp/[serverId]` | `web/src/app/admin/plugins/mcp/[serverId]/page.tsx` | `MCPServerDetailPage` (`web/src/sections/actions/MCPServerDetailPage.tsx`) |
| `/admin/plugins/openapi/[toolId]` | `web/src/app/admin/plugins/openapi/[toolId]/page.tsx` | `OpenAPIPluginDetailPage` (`web/src/sections/plugins/OpenAPIPluginDetailPage.tsx`) |
| `/admin/mcp-actions`, `/admin/mcp-actions/new`, `/admin/mcp-actions/[serverId]`, `/admin/openapi-actions` | Existing route files | Query-preserving redirects through `web/src/lib/plugins/routes.ts` |

### HTTP endpoints, MCP (`backend/onyx/server/features/mcp/api.py`, prefixes `/mcp` and `/admin/mcp`)

| Method | Path | Handler | Notes |
|---|---|---|---|
| POST | `/admin/mcp/probe` | `stream_admin_mcp_probe` | Credential-free MCP setup check for `MANAGE_ACTIONS`, including scoped managers. Streams NDJSON progress, then one result: public, OAuth, unknown authentication, or unreachable. No database writes. |
| POST | `/admin/mcp/oauth/discover` | `discover_admin_oauth` | Read-only public metadata probe for a manageable server. Returns metadata status, automatic registration support, and discovered endpoints. |
| POST | `/admin/mcp/servers/create` | `upsert_mcp_server` (calls `_upsert_mcp_server`) | Create, or edit when the body has `existing_server_id`. An edit can rotate admin credentials, OAuth client, transport, and access list. A new server defaults `is_public=True`. |
| POST | `/admin/mcp/servers/update` | `update_mcp_server_with_tools` | Changes only name, description, and the selected tool set (`_sync_tools_for_server`). It does not touch credentials, transport, or access. |
| POST | `/admin/mcp/server` | `create_mcp_server_simple` | Legacy/simple create path. |
| PATCH | `/admin/mcp/server/{server_id}` | `update_mcp_server_simple` | Partial update. |
| PATCH | `/admin/mcp/server/{server_id}/status` | `update_mcp_server_status` | Sets `MCPServer.status` directly. |
| DELETE | `/admin/mcp/server/{server_id}` | `delete_mcp_server_admin` (`onyx/db/mcp.py:delete_mcp_server`) | Cascades to every `Tool` row with that `mcp_server_id`. |
| GET | `/admin/mcp/servers` | `get_mcp_servers_for_admin` | |
| GET | `/admin/mcp/servers/{server_id}` | `get_mcp_server_detail` | |
| GET | `/admin/mcp/server/{server_id}/tools` | `admin_list_mcp_tools_by_id` | |
| GET | `/admin/mcp/server/{server_id}/tools/snapshots` | `get_mcp_server_tools_snapshots` | |
| GET | `/admin/mcp/server/{server_id}/db-tools` | `get_mcp_server_db_tools` | |
| GET | `/admin/mcp/tools` | `get_all_mcp_tools` | |
| POST | `/admin/mcp/oauth/connect` | `connect_admin_oauth` | Admin-side leg of `_connect_oauth`, `is_admin=True`. |
| GET | `/mcp/servers` | `get_mcp_servers_for_user` | Servers the current user may attach (`get_mcp_servers_accessible_to_user`). |
| GET | `/mcp/servers/craft` | `get_craft_mcp_servers_for_user` | Craft-enabled subset (`available_in_craft`). |
| GET | `/mcp/servers/persona/{assistant_id}` | `get_mcp_servers_for_assistant` | |
| GET | `/mcp/server/{server_id}/tools` | `user_list_mcp_tools_by_id` | |
| POST | `/mcp/oauth/connect` | `connect_user_oauth` | Per-user leg of `_connect_oauth`, `is_admin=False`. |
| POST | `/mcp/oauth/callback` | `process_oauth_callback` | Completes an in-flight OAuth attempt and persists tokens. |
| POST | `/mcp/user-credentials` | `save_user_credentials` | Per-user API-key or header-template values. |
| DELETE | `/mcp/user-credentials/{server_id}` | `delete_user_credentials` | |

### HTTP endpoints, custom/OpenAPI tools (`backend/onyx/server/features/tool/api.py`, prefixes `/tool` and `/admin/tool`)

| Method | Path | Handler | Notes |
|---|---|---|---|
| POST | `/admin/tool/custom` | `create_custom_tool` | One `Tool` row per schema; expansion into per-operation `CustomTool`s happens at turn time (§4.2), not at creation. |
| PUT | `/admin/tool/custom/{tool_id}` | `update_custom_tool` | Re-saving the schema does not retroactively fix personas holding a stale in-memory tool list; see §5. |
| DELETE | `/admin/tool/custom/{tool_id}` | `delete_custom_tool` | Fails (400) if a persona still references the tool. |
| PATCH | `/admin/tool/status` | `update_tools_status` | Bulk enable/disable, gated by `can_manage_tool` per tool id. |
| POST | `/admin/tool/custom/validate` | `validate_tool` | Runs `validate_openapi_schema` + `openapi_to_method_specs` without saving. |
| GET | `/tool` | `list_tools` | Filtered by `_may_view_tool`. |
| GET | `/tool/{tool_id}` | `get_custom_tool` | |
| GET | `/tool/openapi` | `list_openapi_tools` | |

All `/admin/*` MCP and tool routes are gated by
`require_permission(Permission.MANAGE_ACTIONS, allow_scope=True)`
(`tool/api.py`, `mcp/api.py`). See §5 and §6 for the admin/user split.

### Environment configuration

`MCP_TOOL_CALL_TIMEOUT_SECONDS` (`onyx/configs/app_configs.py`, read in
`server/features/mcp/client.py`) bounds one MCP `ClientSession` call.
`onyx/server/features/mcp/ssrf.py:mcp_ssrf_httpx_client_factory` is used for
every outbound MCP HTTP call (discovery, tool calls, OAuth), so a server URL
that resolves to an internal address is blocked before any credential is sent.
The block follows the configured SSRF protection level
(`ssrf.py:validate_mcp_outbound_url`). At `DISABLED`, private and loopback
targets are allowed.

---

## 3. Data model

### `Tool` (`backend/onyx/db/models.py:Tool`)

Owned in full by `[[tools-framework]]`; only the columns this component
populates are repeated here. The three-way discriminator
(`in_code_tool_id` / `openapi_schema` / `mcp_server_id`) is the same one
documented there. This component only ever writes the latter two shapes.

| Column | MCP tool | Custom (OpenAPI) tool |
|---|---|---|
| `mcp_server_id` | set, FK to `MCPServer`, `ondelete="CASCADE"` | null |
| `openapi_schema` | null | the full OpenAPI document |
| `mcp_input_schema` | the MCP tool's JSON input schema (`Tool.mcp_input_schema`) | null |
| `custom_headers` | null | static `list[HeaderItemDict]` merged into every request |
| `passthrough_auth` | not used | `bool`, forwards the caller's login token |
| `oauth_config_id` | null (MCP OAuth lives on `MCPServer`, not `Tool`) | optional FK to `OAuthConfig` |
| `user_id` | null (ownership lives on the server, see §5) | the creating admin's id |
| `enabled` | per-tool row, toggled via `/admin/tool/status` or `/admin/mcp` server status | same |

### `MCPServer` (`db/models.py:MCPServer`)

| Column | Meaning |
|---|---|
| `server_url`, `transport` (`MCPTransport`) | Connection target; `transport` is `SSE` or `STREAMABLE_HTTP` in practice. `STDIO` is also a member of `db/enums.py:MCPTransport`: planned, not supported yet, and not offered in the UI, but the create/update API accepts it, so a stored row can hold it. |
| `auth_type` (`MCPAuthenticationType`) | `NONE`, `API_TOKEN`, `OAUTH`, or `PT_OAUTH` (pass-through OAuth using the caller's own Onyx-login OAuth token). |
| `auth_performer` (`MCPAuthenticationPerformer`) | `ADMIN` or `PER_USER`. **The field that decides credential scope; see §5.** |
| `admin_connection_config_id` | FK to the server's shared `MCPConnectionConfig` (holds the OAuth client registration and/or a shared API token). |
| `oauth_provider_mode`, `oauth_authorization_endpoint`, `oauth_token_endpoint`, `oauth_scopes_override`, `oauth_additional_auth_params` | `AUTO_DISCOVERY` (RFC 8414 metadata) vs `KNOWN_PROVIDER` (endpoints supplied by the admin), plus scope/param overrides. |
| `status` (`MCPServerStatus`) | `CREATED` -> `AWAITING_AUTH` -> `FETCHING_TOOLS` -> `CONNECTED`, or `DISCONNECTED`. |
| `is_public`, `owner` | Public servers are attachable by any user; private ones are gated by `MCPServer__User` / `MCPServer__UserGroup` plus the owner (`db/mcp.py:_add_mcp_server_access_filter`). |
| `available_in_craft` | Separate admin toggle for Craft's agent surface; unrelated to persona attachment. |

### `MCPConnectionConfig` (`db/models.py:MCPConnectionConfig`)

One row is a credential set for one `(mcp_server_id, user_email)` pair.
`user_email=""` marks an admin/shared row; a real email marks a per-user row.
`config` is an `EncryptedJson` blob (`SensitiveValue[dict]`) holding, depending
on auth mode: `headers`, `header_template` + `header_substitutions`,
`api_token`, or the OAuth `access_token`/`refresh_token`/`client_id`/
`client_secret`/registration metadata (documented inline in the model). A
unique-ish access pattern is enforced by
`Index("ix_mcp_connection_config_server_user", "mcp_server_id", "user_email")`.

### `OAuthConfig` / `OAuthUserToken` (per-tool OAuth, not MCP OAuth)

`OAuthConfig` (`db/models.py:OAuthConfig`) holds a shared OAuth client
(`client_id`/`client_secret`, both `EncryptedString`) that one or more custom
`Tool` rows point at via `Tool.oauth_config_id`. `OAuthUserToken` stores the
per-user access/refresh token issued through that client, looked up by
`(oauth_config_id, user_id)` and refreshed by
`onyx/auth/oauth_token_manager.py:OAuthTokenManager.get_valid_access_token`.
This is a separate mechanism from MCP's OAuth (§4.3); it exists so a single
OpenAPI action can require its own OAuth login independent of `passthrough_auth`.

The action authentication form exposes `supports_pkce` as **Use PKCE**, disabled by default.
Enable it only for providers that support S256 PKCE.
The form checks provider metadata for S256 support after both HTTPS endpoints are entered.
The result appears directly below Token URL, before the credential fields.
The result is supported, unsupported, or unknown; missing metadata does not prove lack of support.
The manual setting remains available when detection cannot establish support.

**Test connection** authorizes the current form values in a popup without saving the form.
Saving and testing use the same field conversion in `web/src/lib/oauth/`.
Endpoint whitespace is removed. Masked credentials are reused only when editing an existing configuration.
Existing masked credentials are resolved on the server after checking configuration ownership.
The test exchanges the authorization code and discards the returned tokens.
It does not create or update an `OAuthConfig` or `OAuthUserToken` row.
The popup reports results through a same-origin channel bound to the attempt state, with an opener-message fallback.
A disconnected popup can still report a result until the test expires or the admin changes settings or retries.
A test can create a grant at the provider. Success confirms the exchange, not PKCE enforcement.

Authorization uses the shared tenant-aware attempt store and protocol helpers described in [[auth-and-identity]] §4.
The action route owns configuration validation and per-user token storage; MCP keeps its separate credential model.

### Diagram

```
Admin config time                      Turn time
------------------                     ---------
MCPServer ----owns----> MCPConnectionConfig (admin, user_email="")
   |  \                        ^
   |   \--admin_connection_config_id
   |
   +--current_actions--> Tool (mcp_server_id set) --tool_constructor.py-->
   |                         ^                        resolve_mcp_credentials
   |                         |                         + MCPTool per row
   |               MCPConnectionConfig (per user, user_email=<email>)
   |
Tool (openapi_schema set) --tool_constructor.py--> build_custom_tools_from_...
   |                          (one CustomTool per operationId)
   +--oauth_config_id--> OAuthConfig --OAuthUserToken (per user)--
```

---

## 4. How it works

### 4.1 MCP server lifecycle: admin configuration to a discovered tool set

1. Admin submits the create/update form on `/admin/mcp-actions`. The frontend
   posts to `/admin/mcp/servers/create` (`mcp/api.py:upsert_mcp_server`, which
   calls `_upsert_mcp_server`). An edit sends `existing_server_id` to the same
   endpoint. `/admin/mcp/servers/update` only renames the server and syncs its
   selected tools.
2. `_upsert_mcp_server` validates the URL
   (`_validate_mcp_server_url`), resolves credential fields against any
   existing values so a re-submit of a masked field does not blank it out
   (`_resolve_oauth_credentials`, `_resolve_admin_credentials`,
   `_resolve_shared_api_token`), and calls `create_mcp_server__no_commit` or
   `update_mcp_server__no_commit` (`db/mcp.py`).
3. If the auth mode needs a shared credential (`API_TOKEN` with
   `auth_performer=ADMIN`, or the OAuth client registration itself), it is
   persisted to an `MCPConnectionConfig` row with `user_email=""` and linked
   via `MCPServer.admin_connection_config_id`
   (`_persist_admin_connection_config`, `mcp/api.py`).
4. Tool discovery: `discover_mcp_tools` (`mcp/client.py`) opens an MCP
   `ClientSession` over the chosen transport and calls `list_tools`. The
   result is reconciled against existing `Tool` rows for the server by
   `_sync_mcp_server_tools` (`mcp/api.py:_sync_mcp_server_tools`): tools
   present in both are updated in place, new ones are inserted via
   `create_tool__no_commit(..., mcp_server_id=..., openapi_schema=None)`,
   and DB rows no longer returned by the server are deleted
   (`delete_tool__no_commit`). The server row is locked
   (`with_for_update()`) for the duration so concurrent refreshes serialize.
5. The admin (or a user with access) attaches the server's tools to a
   persona. Attachment is a `Persona__Tool` row per `Tool`, exactly as for
   any other tool kind (`[[tools-framework]]`, `[[agents-personas]]`).
6. At turn time, `tool_constructor.py:_construct_tools_impl` resolves
   credentials via `resolve_mcp_credentials` and builds one `MCPTool` per
   saved `Tool` row (`[[tools-framework]]` §4.4 step 5). This is the handoff
   point; construction and execution are that component's, not this one's.

### 4.2 Transport selection

`MCPTransport` has three values (`db/enums.py`): `SSE` (legacy, still
supported), `STREAMABLE_HTTP` (current default), and `STDIO` (planned, not
supported yet). Do not remove `STDIO`: the column is a non-native enum, so a
stored `STDIO` row would fail to load and break the server list. The authentication
form preserves the saved transport and exposes an advanced override. When no
transport is configured, the URL supplies a default: an SSE endpoint selects SSE;
other URLs select Streamable HTTP. This is a URL heuristic, not protocol
negotiation. `create_mcp_server_simple` leaves transport unset until authentication
setup. The alternate upsert-create path defaults to
`MCPTransport.STREAMABLE_HTTP` when the request omits it
(`mcp/api.py:_upsert_mcp_server`, the `else` branch). The chosen transport
matters at two points: `MCPTool.run` picks the `sse_client` or
`streamablehttp_client` function in `client.py:_create_mcp_client_function_runner`,
and OAuth token refresh takes a different path for SSE because
`httpx.Auth`-based lazy refresh cannot run over an open SSE stream
(`MCPTool.run`, `mcp_tool.py`: the `if self.mcp_server.transport == MCPTransport.SSE`
branch proactively calls `refresh_mcp_oauth_token_if_expired` instead of
passing an `OAuthClientProvider`).

### 4.3 Auth modes and credential scope (the security-relevant question)

`MCPAuthenticationType` has four values: `NONE`, `API_TOKEN`, `OAUTH`, and
`PT_OAUTH`. Independently, `MCPAuthenticationPerformer` is `ADMIN` or
`PER_USER`. `resolve_mcp_credentials` (`mcp/credentials.py`) is the single
place that turns `(auth_type, auth_performer)` plus the calling `user` into an
effective credential:

- `PT_OAUTH`: always uses `user.live_oauth_token`, the calling user's own
  Onyx-login OAuth token. Never shared.
- `API_TOKEN` or `OAUTH` with `auth_performer == PER_USER`: uses that user's
  own `MCPConnectionConfig` row (`user_email=<their email>`), fetched by
  `get_user_connection_config`. **One user's connection cannot be used by
  another user in this mode**; each user must connect separately, and an
  unconnected user gets the auth-error path in §4.5.
- `API_TOKEN` with `auth_performer == ADMIN`: uses
  `mcp_server.admin_connection_config`, the single shared row with
  `user_email=""`. **Every user who can attach this server shares the same
  credential.** This is a deliberate admin choice (a service-account API key),
  made explicitly at server-configuration time, not a
  default.
- New or edited OAuth configurations require `PER_USER`
  (`models.py:MCPToolCreateRequest.validate_auth_configuration`). The credential
  resolver can read legacy admin-scoped OAuth records, but setup cannot create
  shared OAuth connections. An admin's OAuth client registration is shared
  configuration; their OAuth grant is personal.
- `NONE`: no credential; only header templates/substitutions (if any) apply.

So: **MCP credentials are per server by default when the admin sets
`auth_performer=ADMIN`, and per user when the admin sets `auth_performer=PER_USER`
(or the server uses `PT_OAUTH`, which is inherently per user).** The admin's
choice at server-creation time is what decides this, and it is visible on the
`MCPServer` row, not implicit.

### 4.4 The MCP OAuth flow

Automatic discovery finds OAuth settings after the admin selects OAuth. It
does not detect the authentication method. Client setup can use supplied
credentials, a Client ID Metadata Document (CIMD), or Dynamic Client
Registration (DCR), as supported by the provider. CIMD needs the provider to
fetch the deployment's metadata document, so `MCPServer.oauth_cimd_enabled`
lets an admin turn it off per server. Automatic discovery then registers
through DCR, which a private deployment needs. Tool discovery follows
authentication; it is separate from OAuth discovery.

1. **Connect.** The frontend calls `POST /mcp/oauth/connect` (user) or
   `/admin/mcp/oauth/connect` (admin, `is_admin=True`), both routed through
   `_connect_oauth` (`mcp/api.py`). It re-resolves OAuth client credentials
   against stored values, upserts the caller's `MCPConnectionConfig` (with
   `user_email=user.email` for a per-user flow), and dispatches to
   `start_known_provider_oauth_flow` or `start_auto_discovery_oauth_flow`
   (`mcp/oauth_flow.py`) depending on `oauth_provider_mode`. Either returns an
   `authorization_url` the frontend redirects the browser to, or reports
   `already_authenticated` if `credentials_usable` (valid, unexpired,
   `user_connection_status == CONNECTED`) and the caller did not force re-auth.
2. **Attempt tracking.** The pending flow's state (server id, connection
   config id, a fingerprint of the OAuth client info, the return path) is
   stored keyed by an opaque `state` value in
   `MCP_OAUTH_ATTEMPTS` (`oauth_flow.py`, backed by
   `onyx/oauth/authorization_attempt.py`), scoped to the initiating user id.
3. **Callback.** `POST /mcp/oauth/callback` (`process_oauth_callback`,
   `mcp/api.py`) consumes the attempt by `(user_id, state)`, re-checks the
   user still has server access, re-validates the connection config and
   client-info fingerprint haven't changed mid-flow
   (`secrets.compare_digest` on `mcp_oauth_client_information_fingerprint`),
   then calls `complete_mcp_oauth_authorization` (`mcp/oauth.py`) to exchange
   the code and persist tokens into the user's `MCPConnectionConfig`.
4. **Refresh.** `refresh_mcp_oauth_token_if_expired`
   (`mcp/oauth.py:refresh_mcp_oauth_token_if_expired`) is single-flighted per
   `connection_config_id` via a shared cache lock
   (`cache_shared_lock`, lease `_REFRESH_LOCK_LEASE_S`). A losing concurrent
   caller waits for the winner and reads back the persisted header
   (`_persisted_auth_header`) rather than refreshing again; if the lock
   cannot be acquired at all, it falls back to whatever is currently stored.
   For non-SSE transports the MCP SDK's `OAuthClientProvider`
   (`make_oauth_provider`, `mcp/oauth.py`) refreshes lazily inside the tool
   call itself; for SSE, `MCPTool.run` calls this function proactively before
   opening the stream (§4.2).

### 4.5 Custom OpenAPI tools: one schema, many tools

1. Admin submits the schema via `POST /admin/tool/custom`
   (`tool/api.py:create_custom_tool`). `_validate_tool_definition` runs
   `validate_openapi_schema` (`openapi_parsing.py`), which requires `info`,
   `openapi` (3.x), `paths`, exactly one `servers[].url`, and (via
   `openapi_to_method_specs`) a non-empty, unique `operationId` and a
   `summary`/`description` per operation. **One `Tool` row is created for the
   whole schema**; it is not expanded into per-operation rows in the
   database.
2. At turn time, `tool_constructor.py` calls
   `build_custom_tools_from_openapi_schema_and_headers`
   (`custom_tool.py`), which calls `openapi_to_method_specs` again and
   returns one `CustomTool` instance per `MethodSpec`, i.e. per
   `operationId`. This is where "one schema becomes several tools" actually
   happens, every turn, from the single stored schema.
3. **Placeholder substitution.** Before parsing, if `dynamic_schema_info` is
   given, the JSON-serialized schema has the literal strings
   `CHAT_SESSION_ID`, `MESSAGE_ID`, `USER_ID`, `USER_EMAIL`
   (`onyx/tools/models.py`: `CHAT_SESSION_ID_PLACEHOLDER` etc.) replaced with
   the current turn's real values before the schema is parsed into
   `MethodSpec`s. A placeholder whose value is `None` (anonymous user's
   identity) is left untouched rather than substituted with an empty string
   (`custom_tool.py:build_custom_tools_from_openapi_schema_and_headers`).
   Substitution only touches the schema; `custom_headers` are not templated.
4. **`custom_headers`** (`Tool.custom_headers`) are static
   `list[HeaderItemDict]` merged onto every request via
   `header_list_to_header_dict` (`CustomTool.__init__`).
5. **`passthrough_auth`.** When set, `tool_constructor.py` resolves
   `oauth_token_for_tool = user_oauth_token` (the current user's own Onyx
   login OAuth token, from `user.live_oauth_token`) and passes it into
   `build_custom_tools_from_openapi_schema_and_headers`, which sets it as
   `Authorization: Bearer <token>` on every request the tool makes
   (`CustomTool.__init__`). **This means the third-party endpoint the custom
   tool calls receives the user's own Onyx-issued OAuth token as their bearer
   credential.** It is only meaningful when the third party accepts and
   validates that token (for example, an internal service that trusts Onyx's
   OAuth issuer); pointed at an arbitrary external API, it either fails auth
   or, if that API happens to accept the same token shape, leaks it. This
   requires the admin to explicitly enable it per tool
   (`_validate_auth_settings`, `tool/api.py`); it is never on by default.
6. Per-tool OAuth (`Tool.oauth_config_id`, priority 1, checked before
   `passthrough_auth`, priority 2) is a separate, narrower alternative: the
   tool authenticates with its own registered OAuth client
   (`OAuthConfig`) and its own per-user token (`OAuthUserToken`), not the
   user's Onyx login token.

### 4.6 Name disambiguation across MCP servers

`tool_constructor.py:_disambiguate_mcp_tool_names` runs once, after every
tool for the turn has been constructed. It counts tool names with
`Counter(tool.name for tool in tools)`; any `MCPTool` whose name collides
with another tool's name (built-in, custom, or from a different MCP server)
has `use_disambiguated_name()` called on it, switching its `name` from the
server's raw tool name to `self._llm_name`, precomputed in `MCPTool.__init__`
as `sanitize_tool_name(f"mcp_{mcp_server.name}_{tool_name}")`. This fires only
when a collision exists for that specific turn's tool set; a persona with
only one MCP server attached never sees the renamed form. The LLM only ever
sees whichever name is current at the moment `tool_definition()` is called
(after `_disambiguate_mcp_tool_names` runs), so it cannot observe the
un-disambiguated name once a collision exists.

### 4.7 Failure modes

`MCPTool.run` (`mcp_tool.py`) distinguishes two failure shapes, both
returned as a `ToolResponse` (never a raised exception, per
`[[tools-framework]]`'s contract 7):

- **Missing/expired credentials before the call is even attempted.** If
  `credentials.can_authenticate()` is false and either the OAuth grant is
  dead (`needs_reauth()`) or there are no request-supplied headers to fall
  back on, the tool returns an error telling the user to connect via the MCP
  dropdown, without ever contacting the server
  (`MCPToolCallStatus.AUTH_ERROR`).
- **Errors from the call itself.** Any exception from `call_mcp_tool` is
  classified by scanning the lowercased exception string for
  `_AUTH_ERROR_INDICATORS` (`"401"`, `"unauthorized"`, `"forbidden"`, etc.) or
  by type (`MCPReauthenticationRequired`). An auth-shaped error tells the user
  to reconnect via the MCP dropdown; anything else (server down, network
  error, malformed response) returns a generic
  `f"Tool execution failed: {str(e)}"`. Either way the turn continues; only
  that one tool call fails.

`CustomTool.run` (`custom_tool.py`) only classifies HTTP `401`/`403` as an
auth error (`CustomToolErrorInfo(is_auth_error=True, ...)`); any other status
code or exception surfaces as the raw response body or propagates up to
`_safe_run_single_tool`'s generic exception handling
(`[[tools-framework]]` §4.5 step 6).

---

Known-provider OAuth uses `onyx/oauth/protocol.py` for authorization URLs.
Both endpoint queries and configured extras reject flow-owned parameters,
including `resource`. The pending-attempt store resolves the tenant cache on
each operation and consumes state before exchanging the authorization code.

## 5. Contracts and invariants

1. **A tool name must be unique within one turn's tool set**, or the LLM
   cannot address a specific tool by name. `_disambiguate_mcp_tool_names`
   (§4.6) is what enforces this for MCP tools across servers; a change to it
   that stops renaming, or renames the wrong instance, breaks tool dispatch
   silently (the LLM calls one name, the wrong tool runs).
2. **MCP credential scope is exactly what `auth_performer` says, and nothing
   else.** `resolve_mcp_credentials` (§4.3) is the only place that decides
   whether a call uses a shared admin credential or a per-user one. Any new
   auth type or performer value must be added there explicitly; the default
   behavior of an unhandled combination must not silently fall back to a
   shared credential.
3. **`passthrough_auth` is a deliberate trust decision, not a convenience
   default.** It forwards the calling user's own Onyx OAuth token to
   whatever URL the OpenAPI schema's `servers[0].url` points at. It must stay
   opt-in per tool (`_validate_auth_settings`) and must never be implied by
   the absence of other auth configuration.
4. **A server being unreachable or unauthenticated must fail the tool call,
   not the turn.** Both `MCPTool.run` and `CustomTool.run` convert every
   failure into a `ToolResponse`; see `[[tools-framework]]` contract 7 for the
   mechanism that guarantees this holds even if these two implementations
   changed.
5. **An OpenAPI schema change must re-introspect, not silently keep stale
   tools.** There is no caching of `MethodSpec`s across turns; every turn's
   `build_custom_tools_from_openapi_schema_and_headers` call re-parses
   `Tool.openapi_schema` fresh (§4.5 step 2). Saving a new schema via
   `PUT /admin/tool/custom/{tool_id}` takes effect on the very next turn with
   no separate re-sync step, unlike MCP tools (which do need `_sync_mcp_server_tools`
   to run again, see §9).
6. **Deleting an `MCPServer` cascades to every `Tool` row it owns**
   (`ondelete="CASCADE"` on `Tool.mcp_server_id`), which in turn removes the
   tool from any persona's `Persona__Tool` rows. A persona that only had this
   server's tools attached silently loses that capability; there is no
   separate confirmation step beyond the delete-server admin action.
7. **`Tool.oauth_config_id` and `Tool.mcp_server_id` are mutually exclusive
   in practice** (an MCP tool never has a per-tool `OAuthConfig`; MCP OAuth
   lives entirely on `MCPServer`), even though the schema does not enforce it
   at the DB level.

---

## 6. Relationships

**Depends on**
- `[[auth-and-identity]]`: `user.live_oauth_token` is what `PT_OAUTH` MCP
  servers and `passthrough_auth` custom tools forward; `require_permission`
  gates every admin route.
- `[[access-control]]`: `MCPServer.is_public` / `MCPServer__User` /
  `MCPServer__UserGroup`, and `can_manage_mcp_server` / `can_manage_own_tool` /
  `can_manage_tool` (`db/tools.py`), decide who can view, attach, or edit a
  server or tool.
- `[[editions-and-gating]]`: `make_mcp_server_private` (`db/mcp.py`) is a
  CE no-op stub that raises if restriction is requested; the EE override
  implements the actual user/group reconciliation.
- `[[agents-personas]]`: a persona's `Persona__Tool` rows are what attach an
  MCP or custom tool to a chat agent.

**Depended on by**
- `[[tools-framework]]`: `tool_constructor.py` consumes every `Tool` row this
  component creates, dispatching on `mcp_server_id` / `openapi_schema` (§4.1
  step 6, §4.5 step 2), and `run_tool_calls` executes the resulting `MCPTool`
  / `CustomTool` instances.
- `[[core-chat-loop]]`: indirectly, through `[[tools-framework]]`; a turn's
  tool set can include MCP and custom tools alongside built-ins.
- `[[mcp-server]]` is the opposite direction: Onyx acting as an MCP *server*
  for external clients. This component is Onyx acting as an MCP *client*,
  connecting out to servers an admin configured. The two share vocabulary
  (`ClientSession`, `list_tools`) but no code.

---

## 7. Blast radius

| If your change… | Also check |
|---|---|
| adds a transport | `MCPTransport` enum, `client.py:_create_mcp_client_function_runner`'s branch on transport, `MCPTool.run`'s SSE-specific proactive-refresh branch (§4.2), the create-server frontend form |
| changes credential scope (`auth_performer` handling) | `resolve_mcp_credentials` (§4.3), `requires_user_authentication`, `user_connection_status`, the MCP dropdown's per-user connect UI, and whether an existing shared credential must be migrated or invalidated |
| changes name disambiguation | `_disambiguate_mcp_tool_names`, `MCPTool.use_disambiguated_name`, and any saved chat history that stored the pre- or post-disambiguation name (`[[tools-framework]]` §7's tool-rename row applies here too) |
| changes the `Tool` discriminator (adds a fourth kind, or changes column semantics) | `[[tools-framework]]`'s `BUILT_IN_TOOL_MAP`/dispatch, `get_tools` (`db/tools.py`, its `only_openapi`/`only_connected_mcp` filters), `_upsert_db_tools`, `create_tool__no_commit` |
| changes `passthrough_auth` or per-tool OAuth resolution order | `tool_constructor.py`'s priority-1-then-2 logic (§4.5 step 5-6), `_validate_auth_settings` (`tool/api.py`) |
| changes custom-action OAuth setup | the PKCE metadata check, draft test endpoints, masked credential handling, popup callback routing, and saved per-user authorization in [[auth-and-identity]] |
| changes MCP OAuth token storage shape | `extract_connection_data`, `mcp_token_expired`, `ResolvedMCPCredentials.build_headers`, and the SSRF-safe httpx factory that every one of these calls flows through |
| changes tool sync (`_sync_mcp_server_tools`) | admin-visible tool list going stale, the `with_for_update()` lock's contention behavior under concurrent refresh triggers |

---

## 8. How to verify a change

### Tests

Storybook covers setup, saved settings, access control, discovery, validation,
and failure states. See `web/src/sections/actions/modals/MCPModalStories.md`
for the state inventory and preview links. Fixtures intercept requests locally.

```bash
# Frontend setup, retry, credential scope, and OAuth service regressions
cd web && bun run test --runInBand src/sections/actions/modals/MCPPluginSetupModal.test.tsx src/sections/actions/modals/MCPAuthenticationPage.test.tsx src/sections/actions/modals/MCPServerDetailsPage.test.tsx src/sections/plugins/PluginsPage.test.tsx src/lib/mcp/svc.test.ts --testTimeout=30000

# Playwright e2e: MCP server creation, OAuth connect, per-user API key, group access
cd web && bun run playwright tests/e2e/mcp/mcp_oauth_flow.spec.ts
cd web && bun run playwright tests/e2e/mcp/mcp_per_user_key.spec.ts
cd web && bun run playwright tests/e2e/mcp/mcp_group_access.spec.ts
cd web && bun run playwright tests/e2e/mcp/default-agent-mcp.spec.ts

# Backend integration tests for tool construction, including MCP/custom dispatch
cd backend && uv run pytest tests/integration -k "tool or mcp"
```
See `backend/AGENTS.md` for authoritative env/secrets setup. Test helpers:
`web/tests/e2e/utils/mcpServer.ts`, `web/tests/e2e/mcp/mcpToolInvocation.ts`,
`web/tests/e2e/mcp/McpOAuthFlow.ts`, `web/tests/e2e/pages/AdminMcpServersPage.ts`.

### Adding a local MCP server and confirming the LLM can call it

1. Stand up any MCP-compliant server reachable from the backend (a
   streamable-HTTP echo/test server is simplest).
2. In `/admin/mcp-actions`, create a server with that URL, transport
   `STREAMABLE_HTTP`, auth `NONE`. Confirm status reaches `CONNECTED` and its
   tools list is populated (`GET /admin/mcp/server/{id}/tools`).
3. Attach the server to a persona used in a chat session.
4. Send a message that should trigger the tool; confirm a `CustomToolStart`/
   `CustomToolDelta` packet renders in the transcript and the tool result
   appears in the reply.
5. For an OAuth or per-user-key server, repeat as a second user and confirm
   the second user must connect independently (proves per-user scope, §4.3).

### Checking OAuth settings without saving

1. Open an action's OAuth settings and enter the authorization and token endpoints.
2. Check the detected S256 status. Change the endpoints and confirm the old status disappears.
3. Run **Test connection** and complete provider consent in the popup.
4. Confirm the result identifies whether the test used PKCE.
5. Confirm the test did not change saved configuration or the user's saved token.
6. Change a form value and confirm the previous test result no longer applies.
7. Repeat with denied consent and a closed popup. Neither case must report success.

### Adding an OpenAPI action and confirming the LLM can call them

1. In `/admin/openapi-actions`, submit a schema with two or more operations,
   each with a distinct `operationId`.
2. `POST /admin/tool/custom/validate` (or the form's own validate step) should
   report every method spec; a duplicate or colliding sanitized name should
   be rejected (`openapi_to_method_specs`'s duplicate-name check).
3. Attach the resulting `Tool` to a persona, start a chat, and confirm the
   LLM sees one callable function per operation (`tool_definition()` for
   each), not one function for the whole schema.
4. If testing `passthrough_auth`, point the schema at an endpoint that echoes
   its `Authorization` header and confirm it receives the calling user's live
   Onyx OAuth token, not a static header.

### What "working" looks like

- A newly connected MCP server's tools appear in the persona editor only
  after `_sync_mcp_server_tools` has run at least once; the admin UI's
  "refresh" action is what triggers a re-sync.
- A user without their own per-user credential on a `PER_USER` server gets a
  clear "connect via the MCP dropdown" error, not a raw exception or a silent
  tool omission.
- Deleting an MCP server removes its tools from every persona that had them
  attached, with no orphaned `Tool` rows left behind.

---

## 9. Footguns

- **`Tool.user_id` is `None` for MCP tools.** Ownership for an MCP tool lives
  on `Tool.mcp_server.owner`, not on the tool row itself. `can_manage_tool`
  (`db/tools.py`) routes through `can_manage_mcp_server` for exactly this
  reason; any new code path that checks `tool.user_id == user.id` directly,
  bypassing `can_manage_tool`, will incorrectly deny the server's owner.
- **Re-saving an OpenAPI schema does not re-sync MCP tools, and vice versa.**
  Custom tools re-parse their schema every turn (§5 contract 5); MCP tools do
  not re-discover the server's tool list until an explicit sync action runs
  `_sync_mcp_server_tools`. Assuming the two behave the same way is a common
  mistake when reasoning about "does my change take effect immediately".
- **A `Tool.enabled = False` MCP or custom tool stays attached to its
  personas**, exactly as documented for built-in tools in
  `[[tools-framework]]` contract 9; `Persona__Tool` is availability, not
  usability.
- **The disambiguated MCP tool name is only assigned once, at the top of
  `_construct_tools_impl`'s post-loop pass, and is never un-set.** If the
  same `MCPTool` Python object were somehow reused across a name-colliding
  and a non-colliding context in one process (it currently is not, since
  tools are rebuilt per turn), the disambiguated name would leak forward via
  `MCPTool.use_disambiguated_name`'s mutation of `self._name`.
- **`passthrough_auth` and a static `Authorization` custom header can both be
  set at once.** `CustomTool.__init__` logs a warning and lets the OAuth
  token silently win (`self.headers["Authorization"] = f"Bearer {token}"`
  runs after the static headers are loaded), which can surprise an admin who
  set a header expecting it to be authoritative.
- **SSRF protection is transport-agnostic but call-site-specific.**
  `mcp_ssrf_httpx_client_factory` (`ssrf.py`) is threaded through discovery,
  tool calls, and OAuth token exchange in `client.py` and `oauth.py`; a new
  MCP-related outbound HTTP call added elsewhere (for example, a new admin
  "test connection" button) that builds its own `httpx.Client` instead of
  reusing this factory would silently reopen the SSRF hole.
- **The MCP OAuth callback trusts the state store, not the query string
  alone.** `process_oauth_callback` re-derives everything it needs from the
  server-side `MCP_OAUTH_ATTEMPTS` entry keyed by `(user_id, state)`;
  a client that tries to shortcut the flow by POSTing arbitrary
  `code`/`server_id` values without a matching stored attempt gets rejected
  at the fingerprint/connection-config-id checks (§4.4 step 3).
