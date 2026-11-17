# MCP and Custom Tools

> Onyx as an MCP client to servers that an admin connects, and the OpenAPI
> custom tools that an admin describes with a schema: how they become `Tool`
> rows, how their credentials are stored and resolved, and how one call
> succeeds or fails.

**Verified against:** `6bac4e012f` (2026-10-29)
**Edition:** CE. Restricting an MCP server to users or groups needs EE
(`backend/onyx/db/mcp.py:make_mcp_server_private` is a CE stub).

---

## User experience

- **An admin connects an MCP server.** Onyx probes the URL without
  credentials and reports whether the server is open, asks for OAuth, asks for
  some other credential, or cannot be reached. The admin then picks none, a
  shared or per-user API token, per-user OAuth, or pass-through of the user's
  Onyx login token. The server is saved only after sign-in and tool discovery
  succeed. On failure the admin sees the error in the form and nothing is
  saved. A URL that SSRF protection blocks fails with a hint that names the
  SSRF Protection level that allows it, or says that no level does.
- **An admin adds an OpenAPI action.** The admin pastes an OpenAPI 3 schema with
  one server URL. Each operation in it becomes a tool that the model can call.
  The admin can add static headers, link a per-tool OAuth client, or forward
  each user's Onyx login token. A schema with a missing or duplicate
  `operationId`, or a server URL that SSRF protection blocks, is rejected at
  save.
- **A member connects an account.** On a per-user server, each member connects
  their own API key or OAuth account. One member's connection never serves
  another member.
- **A user in chat** sees each call as a tool step. When Onyx cannot
  authenticate a server, its tools are left out of the turn. The composer
  prompts the user to connect. Credentials that expire or are rejected during
  a call produce an error that tells the user to connect from the MCP menu.
  A down MCP server gives "Tool execution failed" with the reason. An OpenAPI
  tool says that it could not reach its server. Only that call fails; the turn
  continues.
- **A user in the web chat approves an MCP or OpenAPI call.** Chat reads the
  integration tables. Each action of an integration has a policy:
  Allow, Ask or Blocked, from `integrations/policy.py:resolve_action_policies`
  (see "Policy order" under Chat approvals). When no row sets it, a read-only
  MCP tool and an OpenAPI GET are Allow, and each other action is Ask. A
  Blocked action is not offered to the model. For an Ask tool the chat shows an approval
  card with the call's arguments, and when nothing but such
  requests remains, the response stops: its stream ends with the stop reason
  `awaiting_user`, and the response waits, saved, with no server holding
  it and no time limit. The user picks Approve once, Approve for this chat, or
  Reject. Approve once runs the exact call. Approve for this chat also runs
  later calls of that tool in the chat session with no card. Reject gives the
  model a "did not run" result. Once no request of the response waits, the
  response continues in a new stream, on any server, and the answer continues.
  A policy change applies from the next message.
  Web, mobile, the widget, the CLI and API callers all show requests; a
  non-streaming API call returns them when the response stops. A Slack bot run
  and a run of the Discord bot's service key have no approver, so an action
  that is still Ask is not offered. Evals run Ask actions with no question.
  Usage-only incognito
  chats and anonymous users cannot wait: an Ask call gives the model an error
  that names the cause. Agent runs, foreground or background, ask and park as
  the root does
  ([[#chat-approval-needs-waiting-client]]). The upgrade
  migration (`backend/alembic/versions/7c00f53ab75f_chat_tool_approvals.py`)
  writes Auto-approve for tools that exist then on servers not available in
  Craft, and on every server when the tenant has no `build_session` row (it
  never used Craft); it keeps existing policies. Craft servers of a tenant that
  used Craft keep their policies, and new tools use their default. Older clients (mobile builds, CLI versions and pinned widgets from
  before the feature) cannot answer requests; the docs tell admins to upgrade
  them.

The plugin screens, Default Chat selection and personal preferences are in
[[plugins]].

---

## Scope

This component owns:
- the MCP client: the admin and member API, staged setup, OAuth, the setup
  probe, the SSRF guard, credential resolution, tool sync, and the `MCPTool`
  that runs a call;
- OpenAPI custom tools: the admin API, schema parsing, and the `CustomTool`
  that runs a call;
- MCP server access grants and the per-server and per-user credential rows;
- chat tool approvals: the policy materialized at tool construction, the
  approval requests and their decisions.
- integration credentials on the new tables (`integration_connection`,
  `integration_oauth_client`): resolve, sign-in, refresh, status and lifecycle.

Its neighbours own:
- [[tools-framework]]: the `Tool` interface and per-turn construction.
- [[plugins]]: the plugin UI, Default Chat selection and personal preferences.
- [[auth-and-identity]]: the OpenAPI per-tool `OAuthConfig` and
  `OAuthUserToken` rows, and the OAuth attempt store.
- [[craft-external-apps]]: action policy storage and precedence, and the Craft
  proxy gate.
- [[chat-frontend]]: the approval card.
- [[mcp-server]]: the opposite direction, Onyx as an MCP server. Check who
  connects to whom before you change "MCP" code.

---

## Architecture

```
Admin config                                Turn time (integrations/chat_tools.py)
Plugin --plugin__integration--> Integration   resolve_call_credentials(integration, user)
   |                               |            once per integration; a problem
persona__plugin (action_settings)  +--integration_action (schemas, defaults)
                                   +--integration_connection / oauth_client
                                   +--kind row: mcp_server | OpenAPI tool
MCP server kind  -> one MCPTool per offered action (mcp__<integration id>__...)
OpenAPI kind     -> one CustomTool per offered operation (custom__<integration id>__...)
```

**MCP setup.** An admin adds an MCP server through
`POST /admin/integrations` (see "Integrations API (U6)" below). The old staged
setup and member OAuth routes are gone. The add form still uses
`POST /admin/mcp/probe` and `POST /admin/mcp/oauth/discover`
(`server/features/mcp/api.py`). Sign-in uses the one flow in
`integrations/oauth.py`.

**OAuth client registration.** With `KNOWN_PROVIDER` mode, the admin supplies
the client ID and endpoints. With `AUTO_DISCOVERY`, the client registers in
one of three ways: supplied credentials, a Client ID Metadata Document (CIMD),
or Dynamic Client Registration (DCR).
`server/features/mcp/oauth.py:make_oauth_provider_with_storage` offers CIMD
first when `MCPServer.oauth_cimd_enabled` is on and `WEB_DOMAIN` gives a valid
HTTPS metadata URL. The client ID is then the URL of
`server/features/mcp/client_metadata.py:get_mcp_oauth_client_metadata`, which
the provider must fetch. A deployment that the provider cannot reach must turn
CIMD off for that server, and the SDK then uses DCR. The setup probe checks this
first: `server/features/mcp/oauth_discovery.py:_client_metadata_accepted` sends a
status-only authorization request with the CIMD client ID and reports
`supports_client_metadata`. A network error, a timeout or HTTP 429 gives `null`
(unknown). The setup page sets the CIMD switch from that result, unless the admin
already changed the switch.
`server/features/mcp/oauth_flow.py:validate_client_metadata_authorization`
repeats the check at connect time and fails with `client_metadata_rejected`. The
setup page then turns CIMD off and retries with DCR. The redirect URI and the
metadata URL both come from the backend `WEB_DOMAIN`. If `WEB_DOMAIN` does not
match the origin that users open, the provider rejects the callback.

**Integration connections.** `backend/onyx/integrations/connections.py` makes,
stores, refreshes and applies the credentials of every integration (MCP server,
OpenAPI tool, external app). Queries are in `db/integration_connection.py`.
- `resolve_connection(integration, acting_user)` reads `auth_mode`: `none` needs
  no credential, `shared` reads the organization row (`user_id IS NULL`, else
  Not set up), `individual` reads the acting user's row (else Not connected).
  It never falls back from one mode to the other, with one exception: an old
  custom app in `individual` mode uses the organization values until the user
  saves their own (see Old secret formats). One query reads the user's row and
  the organization row together. `onyx_login` stores no row: it
  sends the user's Onyx login token and refreshes it with no web request
  (`auth/oauth_refresher.py:refresh_oauth_account_sync`).
- `render_headers(header_template, secret)` fills `{placeholder}` from the token
  values and `secret.fields`; `{{` and `}}` are literal braces. The template is
  `secret.headers` (headers the connection itself sends) with `header_template`
  on top. A placeholder with no value raises, so a call never goes out with a
  header missing.
- `ensure_fresh_connection` is the one refresh. It holds one cache lock per
  connection (`integrations/connection_models.py:connection_refresh_lock_name`), which the
  MCP SDK storage also uses. `invalid_grant`, or a 400 or 401 without an OAuth
  error, sets `needs_reconnect` with a reason and keeps the row. Other errors,
  including `invalid_client`, keep the token. The refresh writes in a session
  that it opens and then re-reads the row of the caller, so it never commits or
  rolls back the session of the caller. The `onyx_login` refresh does the same.
- `integration_status` gives Connected, Not connected, Needs reconnect or Not set
  up. It maps `resolve_connection(..., refresh=False)`, so it never calls the
  service.
- `mark_sign_in_settings_changed` sets every connection to Needs reconnect.
  Compare `sign_in_settings_for` before and after an edit: a change of only the
  client secret or a label keeps the connections. Deactivation
  (`db/user_preferences.py:deactivate_user`, the SCIM DAL) deletes the user's
  rows. A user delete removes them by FK cascade.

The one sign-in flow is `integrations/oauth.py`, served by
`POST /integrations/{integration_id}/oauth/start` and
`POST /integrations/oauth/callback`. The attempt store namespace is
`integration`. Each kind keeps the redirect URI admins registered before:
`/mcp/oauth/callback`, `/craft/v1/apps/oauth/callback` (presets) and
`/oauth-config/callback` (manual clients). A preset reads its host values, such
as the Zendesk subdomain, from the OAuth client only
(`integrations/connections.py:preset_host_values`): `additional_params`, or the tagged
registration of an old client. MCP servers use the SDK with
`server/features/mcp/oauth.py:IntegrationTokenStorage`, which keeps the grant in
`integration_connection` and the DCR or CIMD client and discovered metadata in
`integration_oauth_client.registration`.

**Old secret formats.** The integration tables migration copies each old secret as its
encrypted bytes and names the old shape in `legacy_format` on
`integration_connection` and `integration_oauth_client` (`db/enums.py:IntegrationLegacyFormat`:
`mcp_config`, `external_app_org`, `external_app_user`, `oauth_user_token`,
`tool_headers`). `integrations/connection_models.py:read_connection`,
`read_oauth_client` and `legacy_organization_defaults` are the only readers.
The first two give the same `ConnectionSecret`, expiry, scopes and status for
both formats (`reauth_required` reads as Needs reconnect). `resolve_connection`
also applies what an old organization row gave each user: the header template
of an MCP admin config, or the field values of a custom app that the user's
values override (`legacy_organization_defaults`). A custom app user with no row
calls with the organization values when they fill the template; an MCP server with no sign-in
whose template needs values that the user did not save is Not connected. Every secret write
(`upsert_connection__no_commit`, `update_connection_secret__no_commit`,
`set_oauth_client_credentials__no_commit`) saves the new format and clears the
tag; a status-only change keeps it. There is no import job.

Chat reads only the integration tables. The old MCP, OAuth config, user OAuth
token, Craft external app and tool status routes are removed. The sandbox proxy
and Craft read and write the old tables (`mcp_connection_config`,
`external_app_user_credential`) with the old refresh functions.

**Chat on integrations.** `db/tools.py:capture_persona_tool_configuration`
copies the agent's built-in tools and its `persona__plugin` links (plugin id
and `action_settings`). `integrations/chat_tools.py:build_integration_chat_tools`
then picks the integrations:
- A non-default agent: each link whose plugin the user can see
  (`db/plugin_access.py:load_user_plugin_states`). The user's on/off choice,
  `can_run` and the skill limits do not apply.
- The default agent (id 0): each plugin the user runs (visible and enabled),
  with the settings of its persona 0 link when one exists (the bot freeze).
- An anonymous user (a Slack channel): only Organization library plugins, and
  only integrations with no sign-in or shared sign-in.
- Only integrations with `enabled = true`. An API integration with no OpenAPI
  tool (a preset or custom app) gives no chat tool, so it is skipped before its
  credential resolves. When several links hold one integration, the strictest
  link setting of each action wins.

For each integration, `integrations/call_credentials.py:resolve_call_credentials`
calls `resolve_connection` and renders the `header_template`. An OAuth2 or Onyx
login token goes in `Authorization: Bearer` unless the template fills
Authorization from a placeholder; a literal Authorization value (the static
header of a migrated OpenAPI tool) loses to the token. A problem means
no action of the integration is offered. The migration writes the actions of
each MCP server, OpenAPI tool, preset and custom app, so chat reads the stored
actions and never discovers them.
`MCPTool._run` sends the credential that construction resolved and opens no
database session for it. Only an OAuth2 or Onyx login token that expires within
`REFRESH_SKEW` resolves again (`integrations/call_credentials.py:resolve_fresh_call_credentials`).
For OAuth2 on a non-SSE transport, construction reads the server settings
(`mcp_oauth_server`), and each call passes `make_integration_oauth_provider` with
`IntegrationTokenStorage`, so the MCP SDK can refresh during the call. A 401 on
an API key connection sets it to Needs reconnect (`mark_api_key_rejected`).
Request MCP headers do not stand in for a missing connection. The kind handler (`build_chat_tools`) builds the tools:
`MCPTool` for an MCP server, one `CustomTool` per operation for an OpenAPI spec,
and none for a preset or custom app. Tool names use the integration id
(`mcp__<id>__<name>__<tool>`, `custom__<id>__<operationId>`), and each tool has
`id = None`.

**Integrations API (U6).** One API serves every integration; the contract
is plans/workstream-u-api-contract.md (local only). Routes:
`server/features/integrations/admin_api.py` (`/admin/integrations`: list,
presets, create, read, PATCH, DELETE, actions GET/PUT, `actions/refresh`,
`organization-connection` PUT/DELETE) and `server/features/integrations/api.py`
(`/integrations`: list, detail, `connection` PUT/DELETE, `agent-catalog`; and
`/action-policies/integration/{id}` GET/PUT for the user's Always allow). The
OAuth start and callback stay in
`backend/onyx/server/features/integrations/connections_api.py`. The logic is in
`integrations/service.py`; the queries are in `db/integration.py` and
`db/integration_policy.py`.
- Create (`create_integration__no_commit`) writes, in one transaction, the
  `integration` row, its kind row (`mcp_server`, the OpenAPI `tool` row, or
  `external_app` with the preset or URL patterns), the OAuth client, one plugin
  that holds it (`db/plugin.py:create_integration_plugin__no_commit`: version 1
  with no files, Organization library or the creator's "My uploads") and the
  actions. A public MCP server is asked for its tools at create; a failure
  leaves no actions until a refresh.
- A preset keeps its client id, secret and host settings (Zendesk
  `subdomain`) on `integration_oauth_client`; the host settings are in
  `additional_params`, which
  `backend/onyx/integrations/connections.py:preset_host_values` reads.
  `external_app.organization_credentials` is not written.
- Who manages: `backend/onyx/integrations/service.py:manages_integration`. Organization-wide
  manage:actions manages each integration. A scoped holder manages one only
  when each plugin that holds it is in its own "My uploads". Only
  organization-wide manage:actions adds for the organization or sets
  `onyx_login`. `db/plugin.py:publish_or_request_review__no_commit` refuses to
  publish a plugin that holds an integration unless the actor (or the approver
  of a review request) has organization-wide manage:actions. Manage-plugins
  scope gives no right on an integration.
- PATCH compares `sign_in_settings_for` before and after and calls
  `mark_sign_in_settings_changed`; `client_secret: null` keeps the secret.
- MCP actions:
  `backend/onyx/integrations/kinds/mcp_server.py:fetch_mcp_actions` asks the server with
  the acting user's credential; the refresh writes the result as
  `integration_action` rows. `discover_actions` returns the stored rows, so the
  sync never reads MCP `tool` rows.
- Agents: `PersonaUpsertRequest.plugins` replaces the `persona__plugin` links
  (null keeps them). An old custom or MCP id in `tool_ids` adds the plugin of
  its integration (`db/integration_policy.py:legacy_tool_plugin_links`; MCP
  links get `default: blocked` and each listed tool `inherit`). Built-in ids
  stay on `persona__tool`. Agent detail returns `plugins`.
- The eight public `/tool` and `/admin/tool` routes
  (`server/features/tool/api.py`) are aliases on `api` integrations with an
  OpenAPI schema and return the `tool` row id. Plain headers become a shared
  API key connection; `passthrough_auth` is `onyx_login`; `oauth_config_id` is
  refused; `default_chat_enabled` is the plugin install setting (DEFAULT).
- Changes call `backend/onyx/integrations/service.py:reload_craft_sessions` after the commit so running
  Craft sandboxes pick them up.

**Outbound safety.** `server/features/mcp/ssrf.py:mcp_ssrf_httpx_client_factory`
checks every request the MCP SDK makes, redirects included, at the admin SSRF
Protection level. `MCP_SERVER_ALLOW_PRIVATE_NETWORK` and
`MCP_SERVER_ALLOW_LOOPBACK` only seed that level's default. OpenAPI tools use
`tools/tool_implementations/custom/custom_tool.py:custom_tool_ssrf_params`:
self-hosted allows private targets at every level and loopback only at
`DISABLED`, cloud blocks all internal targets, and `ssrf_safe_request` does not
follow redirects.

**Action policies.** `update_mcp_server_simple` and `_publish_mcp_setup`
call `replace_workspace_action_policies` under `MANAGE_ACTIONS` with
`allow_scope=True`, so a scoped action manager can write them.
`update_mcp_server_with_tools` only sets `Tool.enabled` for the selected tools.
Policy precedence is in [[craft-external-apps]]. The Craft proxy and the chat
gate below read the same policies.

**Chat approvals.**

```
integrations/chat_tools.py:build_integration_chat_tools   once per model response
  (integrations/policy.py:resolve_action_policies for each integration and link)
  Blocked -> tool not offered    Ask -> tool.approval = ToolApprovalScope(integration_id, action_id)
  Tool.bind -> AgentTool.approval_required
agents/tool_execution.py:ToolBatch.decide_call   (direct calls, and program calls
  through ToolInvocation.nested_calls, a NestedCallGate)
  -> coordinator ToolApprovals = chat/run_store.py:ChatRunStore.request_approval
     -> chat/tool_approvals.py:open_tool_approval
        session grant (action_now_blocked is false) -> run
        signed out -> error result
        else ApprovalRequest row (display name, the call's arguments)
          -> PendingToolInput(display_name)
     the runtime marks the request PendingToolInput.approval
  a direct call waits in the run; a program call parks its cell's program
  renderer sends tool_approval_request on the call's (or execute_code's) card
the run suspends when only such waits remain
ChatRunStore.poll_control   one park pass over every owned run, once a second
  ChatRunStore.may_park: suspended, idle, every wait is an approval request,
    a question (a `RESULT` request that no `ToolApprovals` opened), or a
    waited-for run that is
    parked or ended
  -> ChatRunStore.handoff   persist_checkpoint_files (dumps under unique IDs)
     -> db/chat_checkpoint.py:publish_checkpoint__no_commit   SUSPENDED, with
        child_run_ids and dump_file_ids; dumps of a replaced checkpoint go
     a failed save deletes its dumps; RunNotTransferable and transient storage
     errors (FileStore.is_transient_error) keep the run, and a later poll
     tries again; a deleted chat parks nothing
  root -> on_root_parked -> chat/execution.py:ChatTurnExecution._root_parked
     -> stop(awaiting_user); the stream keeps naming the response
every turn and agent host, at its end: hands its admission to the resume of a
  parked root that can continue (chat/execution.py:root_response_resumes),
  else releases
POST /chat/approvals/{id}/decision (public)   db/approval_request.py:record_approval_decision__no_commit
POST /chat/question-requests/{id}/answers (public)
  db/question_request.py:resolve_question_requests__no_commit (card: the row;
  a typed message: every open question of the response, whatever the named
  row's state, 409 while an approval of its parked tree waits; the query
  hook processes typed text and card notes first; a repeat of the saved
  answer is 200, and a request that ends no question is otherwise 409)
  -> chat/process_message.py:dispatch_pending_chat_messages(mcp_headers,
     decided_response_id)   the decided response's resume starts first, inline
  -> response continuation {stream_id, response_ids} when a resume turn
     writes the decision's response after the dispatch
dispatch: ChatInbox.resumable_runs (db/chat_checkpoint.py:resumable_parked_runs)
  root response, any branch -> resume turn (new stream ID) -> ChatRunStore.resume
  agent run -> the store of its branch (_dispatch_messages) -> ChatRunStore.resume
  ChatRunStore.resume: claim, answers from the rows
     (chat/run_store.py:_saved_answers, also for a Stop: tool_answer,
     chat/tool_questions.py:question_answer)
     -> Agent.resume(answers) -> input_ended (answer) -> tool_approval_resolved
        or tool_question_resolved
     (a SESSION_GRANT decision is a standing answer -> "approved_for_chat")
  resume turn and agent host: the parked run's own model, tools and filters
     (db/chat_checkpoint.py:parked_response_settings)
  a resume turn that fails before its run exists -> fail_suspended_response,
     except a transient error (RETRYABLE_START_ERRORS): dispatch retries it
     after RESUME_RETRY_DELAYS_S
  an agent host that cannot start -> fail_suspended_response for the agents
     it would resume, except a transient error, a conflict or a rate limit,
     which keep them parked for a later dispatch
user Stop: chat/execution.py:ChatTurnExecution._poll_control
  -> ChatRunStore.reject_waiting_inputs   REJECTED by USER where decision IS
     NULL, for the root and its foreground descendants, and the root's
     questions CANCELLED where outcome IS NULL; each run takes its answers
     through Run.submit and cancels, under its execution lock
a program call that stops waiting while its run goes on
  -> ToolApprovals.withdraw_approval = ChatRunStore.withdraw_approval
     -> EXPIRED if it still waits
  -> input_ended (the answer the run recorded, or none -> "cancelled")
a run that ends: input_ended for each wait, with its recorded answer; a direct
  call whose answer denies it or supplies its result keeps that result
  ChatRunStore.release closes what is left by response (EXPIRED; a root's
  questions CANCELLED)
session load: db/chat_response.py:read_response_replay_data (ended and
  suspended responses; agents' requests at the call that started the agent)
  -> chat/presentation.py:replay_response   request + resolved on the call's
     card; a root's questions the same way
```

A decision row is the only channel between the API pod that takes the
decision and the pod that owns the run. The `approval_request` row holds the
session, the waiting response (`chat_message_id`), the `integration_id`, the
action key, the decision, and for the saved record the step's call that shows the card
(`tool_call_id`), the tool name, its display name and the call's arguments as
the card shows them, so a live card and a replayed card are the same. Craft's proxy keeps its own `action_approval` table
([[craft-external-apps]]). The table, the decision route and the card are
general, so future sandbox-proxy network approvals can reuse them. An
"approve_session" decision is a session grant: it also approves the action's
other pending rows of that integration and action in the chat session, and
`chat/tool_approvals.py:open_tool_approval` lets later calls run with no row
unless the policy is now Blocked. A new row leaves the old `gated_app_id`
column NULL. Deleting an
integration sets `integration_id` to NULL; an approval of that row saves a
rejection by the policy.

**Policy order** (`integrations/policy.py`):
(1) the admin value: the admin row of the action, else the admin default row
(action `''`), else `integration_action.default_policy`, else Allow for a
read-only action and Ask otherwise; Auto counts as Ask. (2) The admin value is
locked when it is Blocked or `users_can_save_always_allow` is false. (3) The
link setting of the agent or task: Blocked blocks; Ask asks unless the admin
blocks; Allow allows unless locked; Inherit keeps the admin value. (4) The
user's Always allow turns Ask into Allow unless locked. (5) A chat grant turns
Ask into Allow. (6) `ApprovalMode.NO_APPROVER` turns Ask into Blocked;
`RUN_WITHOUT_ASKING` turns Ask into Allow. No link that holds the integration
blocks each action. `integrations/policy.py:decide_action_policy` applies the
order to loaded values; `resolve_action_policies` loads the rows for the actions
that its caller passes. The approval re-check
(`chat/tool_approvals.py:action_now_blocked`, also in the decision route) uses
no chat grant. It reads the agent links that construction reads
(`integrations/policy.py:agent_link_settings_by_integration`), so a plugin the
user cannot see, or a default agent plugin the user turned off, does not change
it.

---

## Contracts and traps

1. `credential-resolution-single-point` **`resolve_connection` is the only
   place that picks a credential.** Chat construction and MCP execution reach
   it through `integrations/call_credentials.py:resolve_call_credentials`; the
   sandbox proxy uses `server/features/mcp/credentials.py:resolve_mcp_credentials`.
   A mode never falls back to the other one.
2. `oauth-always-per-user` **OAuth is always per user.**
   `server/features/mcp/models.py:MCPToolCreateRequest.validate_auth_configuration`
   rejects OAuth with any performer other than `PER_USER`. The OAuth client
   registration is shared configuration. The admin's grant is the admin's own
   connection.
3. `token-forwarding-full-manager` **Forwarding a login token is a full-manager
   decision.** `passthrough_auth` and `PT_OAUTH` send each chatting user's Onyx
   token to the admin's URL.
   `backend/onyx/integrations/service.py:create_integration__no_commit` and
   `update_integration__no_commit` let only a global `MANAGE_ACTIONS` holder
   set the `onyx_login` method, also through the `/admin/tool/custom` aliases.
   Keep it opt-in.
4. `guarded-client-factory` **Every outbound MCP request must use the guarded
   client factory**, `server/features/mcp/ssrf.py:mcp_ssrf_httpx_client_factory`.
   The SDK builds URLs from server responses. A new call that makes its own
   `httpx.AsyncClient` reopens SSRF.
5. `mcp-schema-from-db` **MCP tool schemas come from the database.**
   `tools/tool_constructor.py:_construct_tools_impl` builds each `MCPTool` from
   the stored `integration_action` rows. A change on the remote server
   reaches the model only after a refresh
   (`POST /admin/integrations/{id}/actions/refresh`, which calls
   `backend/onyx/integrations/kinds/mcp_server.py:fetch_mcp_actions`) or a
   create of a public server. OpenAPI tools need no refresh. The refresh saves
   the declared `outputSchema` and `annotations.readOnlyHint`, which sets the
   default policy of the action.
6. `sync-matches-by-name` **Sync matches actions by key.**
   `db/integration.py:replace_integration_actions__no_commit` treats a tool
   that the remote server renames as a new action, and the policy rows and
   agent settings of the old key no longer apply to it.
7. `mcp-tool-user-id-none` **`Tool.user_id` is `None` for MCP tools.** Ownership
   is on `MCPServer.owner`. Check rights with `db/tools.py:can_manage_tool`,
   never with `tool.user_id == user.id`.
8. `access-grants-default-chat-only` **Plugin visibility gates chat, not server
   grants.** Chat offers an integration's actions to each user who can use the
   agent and can see a plugin of the agent that holds the integration
   (`integrations/chat_tools.py`). Old server grants gate nothing in chat.
9. `destination-change-deletes-credentials` **A changed URL or sign-in
   setting resets connections.** `integrations/connections.py:sign_in_settings_for`
   includes the host, and an admin PATCH that changes it sets every connection
   to Needs reconnect. A new destination must never receive credentials that
   were given for the old one.
10. `setup-fingerprint` **A new sign-in setting must join the sign-in
    fingerprint.** An OAuth return can arrive minutes after the start.
    `integrations/oauth.py:_configuration_fingerprint` rejects it only when the
    settings changed. A setting left out is overwritten without a conflict.
11. `expected-failure-tool-response` **An expected failure returns an error
    `ToolResult`.** `tools/tool_implementations/mcp/mcp_tool.py:MCPTool._run`
    preserves `CallToolResult.isError` as a failed result without marking
    credentials for reauthentication. Text content takes precedence; a result
    with only `structuredContent` is JSON-encoded, then parsed for the model.
    `server/features/mcp/client.py:process_mcp_result` uses image/audio omission
    notices only when neither readable content nor structured content exists.
    Transport exceptions report an auth error for a 401,
    `MCPReauthenticationRequired`, or auth words in the message.
    `tools/tool_implementations/custom/custom_tool.py:CustomTool._run` returns a
    failed result for a blocked destination, a timeout, a connection error
    or a redirect, and flags only 401 and 403. Both put a
    `CustomToolCallSummary` in `details`, which the chat renderer draws:
    `CustomTool` fills its `error`, and `MCPTool` puts an `{"error": ...}`
    object in `tool_result`. Other `CustomTool` exceptions reach `Tool.run`,
    which gives the model "Tool failed with error: <exception text>" and the
    user no error detail ([[tools-framework#run-errors-become-results]]).
12. `reauth-mark-if-current` **Only a rejected API key is marked.**
    For a 401, `MCPTool._run` calls
    `integrations/call_credentials.py:mark_api_key_rejected`, which locks the
    API key connection that the call used and sets it to Needs reconnect only
    when it still holds the key the call sent (`CallCredentials.secret_fingerprint`).
    A key saved during the call stays connected. An OAuth2 connection is left
    to the refresh.
13. `craft-sessions-bake-mcp-config` **Craft sessions bake MCP config.** A change
    to an integration must call
    `backend/onyx/integrations/service.py:reload_craft_sessions`. Take
    `craft_users_of_integration` before a delete; users who lose access are not
    in the set afterwards. The reload only restamps `mcp_config_hash`; it does not push
    skill files.

14. `cancel-in-flight-request` **Chat cancellation stops an active MCP request.**
    `tools/tool_implementations/mcp/mcp_tool.py:MCPTool._run` passes its
    invocation signal to `server/features/mcp/client.py:call_mcp_tool`.
    The synchronous client cancels and drains the request coroutine before
    raising `AgentCancelled`. This bypasses ordinary tool error recovery and
    records `cancelled`, not `error`, in MCP call metrics.
    `utils/threadpool_concurrency.py:run_until_cancelled` owns coroutine cancellation
    and cleanup. The MCP client supplies signal callbacks and `AgentCancelled`.
    A result that already completed wins a concurrent cancellation. Discovery
    calls that have no signal keep the existing synchronous behavior. Stopping
    the local request cannot undo work already performed by the remote server.
15. `chat-approval-needs-waiting-client` **Every client handles approvals;
    any run of a signed-in owner's chat can wait.**
    `chat/run_store.py:ChatRunStore.request_approval` opens the request for
    the root run and for agent runs alike; for an anonymous user,
    `chat/tool_approvals.py:open_tool_approval` (`signed_out`) returns the
    call's error result instead. A `USAGE_ONLY` incognito turn has no run
    store, so the runtime's own error applies. Nothing about approvals goes
    into the system prompt or tool descriptions. The root agent's question
    tool ([[tools-framework]]) asks the user where an approval can wait: a
    signed-in user's single-model turn that keeps content, asks for approval
    and is not deep research (`chat/process_message.py:prepare_chat_turn`,
    `ChatTurnSetup.question_tool`). A question parks and resumes through the
    same flow, and its rows are `question_request`
    (`chat/tool_questions.py`). Turns the server starts (queued messages,
    agent-result follow-ups) can wait too. The non-streaming API reads the
    whole stream: `chat/process_message.py:gather_stream_full` returns the
    requests that the stream asked and did not resolve when its last stop is
    `awaiting_user`, in `ChatFullResponse.pending_tool_approvals`, and the
    questions in `pending_tool_questions`. The
    run's `ApprovalMode` (`ChatTurnSetup.approval_mode`,
    `construct_tools(approval_mode=...)`) decides what Ask does: the Slack
    handler passes `NO_APPROVER` (Ask is Blocked and not built), evals pass
    `RUN_WITHOUT_ASKING` (Ask runs), and
    `server/query_and_chat/chat_backend.py:handle_send_chat_message` passes
    `NO_APPROVER` for the Discord bot's service API key. Authentication marks that key
    (`db/api_key.py:ApiKeyAuthResult.is_discord_bot`: no owner and the bot's
    name, which no key can be renamed to) on `request.state`, so the send
    route opens no extra session. The client-supplied
    `SendMessageRequest.origin` never changes it.
16. `chat-approval-durable-wait` **A waiting response is saved, not held.**
    A run parks when it is suspended and idle and all of its waits are on
    people (`chat/run_store.py:ChatRunStore.may_park`): its approval requests
    in `Run.pending_inputs`, its questions there (a `RESULT` request that no
    `ToolApprovals` opened; only the root question tool makes one), its
    unfinished foreground children and, for a
    subagent, its unfinished delegated runs, each of them parked. A wait on a
    run that still runs keeps the waiter resident. One park pass in
    `ChatRunStore.poll_control`, at the inbox poll interval, hands off every
    owned run that may park, the root included. The root reports its park
    through the store's `on_root_parked` callback
    (`chat/execution.py:ChatTurnExecution._root_parked`), and its stream ends
    with `OverallStop(awaiting_user)` (`chat/presentation.py:overall_stop`);
    an agent run's release dispatches. A parked root stays in its stream's
    `response_ids`, so `model_index` still indexes them. A park that raises
    `RunNotTransferable` (the run changed), a transient cache, database or
    file store error keeps the run, and a later poll tries again; the
    configured file store classifies its own errors
    (`file_store/file_store.py:FileStore.is_transient_error`, for S3, Azure
    and GCS; a denied access or a missing bucket does not retry). Another
    error cancels the run. A deleted chat parks nothing
    (`publish_checkpoint__no_commit` locks the root chat row), and a soft
    delete ends the parked responses that it reads after its commit. `ChatRunStore.handoff` saves the
    checkpoint with the foreground child runs it waits for and the dumps of its
    parked programs (`db/chat_checkpoint.py:publish_checkpoint__no_commit`,
    columns `child_run_ids` and `dump_file_ids`), sets `SUSPENDED` and releases
    the lease. A save that fails deletes the dumps that it saved. An agent
    run's checkpoint binds to its agent's saved runs before it
    (`ChatRunStore._child_context`), which `ChatRunStore.resume` rebuilds on
    any pod. `ChatRunStore.release` keeps the rows of a handed-off run.
    Requests have no deadline. `server/query_and_chat/chat_backend.py:decide_approval` saves
    the decision (`db/approval_request.py:record_approval_decision__no_commit`,
    conditional on `decision IS NULL`) and calls
    `chat/process_message.py:dispatch_pending_chat_messages` with the body's
    `mcp_headers`, which are not saved. The headers reach every turn or agent
    host that this dispatch starts, and the dispatch that those start when
    they end; a resume that a status read starts has none. The route returns
    `continuation` (`ApprovalDecisionResponse`: the stream ID and its
    response IDs) only when, after the dispatch, a resume turn writes the
    request's response (`ProcessingStream.resumed`). That can be the stream
    that already ran: a resume turn whose answer asks again, decided during
    its resident wait, or with one of two requests decided. A decision while
    the first turn of the response, or a multi-model sibling, still runs gets
    null, and the resume follows when that turn ends. Dispatch reads `db/chat_inputs.py:read_chat_inbox`, whose
    `resumable_runs` come from one query,
    `db/chat_checkpoint.py:resumable_parked_runs`, over every branch of the
    chat: a response is parked only while it is `SUSPENDED` with a
    checkpoint row, and it continues once none of its rows, approval or
    question, waits, none
    of the child runs that its checkpoint names is unfinished and, for a
    subagent, none of its delegated runs is unfinished. A leaf resumes first
    and its parent after it ends. A resumable root response, on any branch,
    continues before any queued turn. For the decision route, the decided
    response goes first and its turn starts synchronously, so the new stream
    ID (`db/chat.py:reserve_stream_id`) is published before the route returns;
    other callers start it on a thread. The decision route skips the
    processing check and lets the admission claim decide. Admission runs one
    turn at a time, so the parked responses of a multi-model turn continue one
    after another, each turn's end dispatching the next. Every turn and agent
    host hands its admission over at its end when a parked root can continue
    (`ChatTurnAdmission.release(hand_off=...)`, with the check
    `chat/execution.py:root_response_resumes` under the admission lock; a
    chat with no checkpoint row answers it with one EXISTS read). Examples
    are the turn that parked the root, a resume that ends while a sibling's
    decision waits, and an agent host that held the chat during a root
    decision. So after any release the chat shows processing until the
    resume publishes its stream. A resume turn runs on the model, tools and
    search filters that the response ran with: its checkpoint saves the model
    configuration and the request's tool options
    (`ResponseCheckpoint.model_configuration_id`, `.tool_options`; the
    integration tables migration removes `tool_selection` from older
    checkpoints, so they resume with the tools of their agent), and
    `prepare_chat_turn` uses them
    instead of the chat's current model and saved options. It checks
    document-set access again. An agent host uses those of the first parked
    agent that it resumes. A restored run whose saved preferred tool matches
    no tool of the turn runs without the preference
    (`chat/agent.py:_offered_preference`).
    Resumable agent runs resume in the store of their branch, selected or not
    (`ChatRunStore._dispatch_messages`), with no stream; dispatch starts an
    agent host (`chat/execution.py:host_agent_work`) for the selected branch,
    or for a parked run's branch, when no running child keeps a store
    scanning. Each resumed run is rebuilt at its depth
    (`chat/restoration.py:restore_chat_agent`); a resumed root has the agent
    tools when its saved step declared them. A session grant decides the
    action's sibling rows, so one decision can resume the response. `_dispatch_after_release` and the status
    route's background dispatch catch a decision saved before the handoff
    finished. The continuation is a `ChatTurnExecution` whose setup has
    `resumed_response_id`: it replays the saved response
    (`chat/presentation.py:ResponsePresenter.replay`, which keeps the waiting
    calls' renderers open), then `ChatRunStore.resume` claims the checkpoint
    once (`db/chat_checkpoint.py:claim_checkpoint__no_commit`; a second claim
    gets None) and answers each waiting request from its row
    (`chat/tool_approvals.py:tool_answer`; a deleted row is "no longer
    available"). A saved call whose tool is gone or whose parameters changed
    gets `agents/tool_execution.py:UNAVAILABLE_CALL_MESSAGE`. Any failure of a
    resume turn before its run exists, such as a gone model or saved state,
    ends the response through `chat/run_store.py:fail_suspended_response`:
    failed, its rows ended, its checkpoint and its parked programs' dumps
    deleted, so no retry repeats it. A transient error
    (`RETRYABLE_START_ERRORS`) keeps the response suspended; the turn does not
    hand off, and its release asks dispatch for `retry_resume`, which
    dispatches again after the next of
    `chat/process_message.py:RESUME_RETRY_DELAYS_S` (on the shared
    `call_later` timer). A dispatch that cannot prepare the turn ends the
    response the same way, except for a transient storage error, which
    retries the same way, and a conflict or a rate limit, which a later
    dispatch retries: the turn that holds the chat hands it over when it
    ends. After the last retry, a status read's dispatch tries again. An
    agent host that cannot start saves its child work as failed runs. A rate
    limit keeps the decided agents parked with their decisions, and a later
    dispatch, such as a release's or a status read's, resumes them. Any other
    error except a transient one or a conflict ends them with
    `fail_suspended_response`, so the status stops reporting active agents. A user Stop of a live
    turn (the chat's stream Stop key, read by
    `chat/execution.py:ChatTurnExecution._poll_control`) first calls
    `ChatRunStore.reject_waiting_inputs`, which saves `REJECTED` by `USER`
    for the root run and its foreground descendants, the runs that the Stop
    cancels, under the same `decision IS NULL` condition, and `CANCELLED` for
    the root's open questions, so an answer that races the Stop keeps
    whichever saved first. Each of those runs then takes
    the saved answers through `Run.submit` and is cancelled, under its
    execution lock, so it applies them only once it sees the Stop; the run's
    requests end with those answers, a question call keeps its result for
    the next turn's history, and a cancelled turn still sends
    `tool_approval_resolved` and `tool_question_resolved`
    (`ChatTurnExecution._publish`). Background agents keep running and keep
    their requests. A suspended response runs nothing, so a Stop finds no
    turn: the stop route only pauses the queue, and the requests still wait.
    "Stop subagents"
    (`server/query_and_chat/chat_backend.py:stop_chat_subagents`) sets each
    active agent's Stop key, saves the user's rejection of their rows, then
    cancels the live ones and ends the parked ones
    (`chat/run_store.py:stop_response`). A store that finds a parked run
    resumable after those rejections reads its Stop key and ends it instead
    of resuming it (`ChatRunStore.resume`). Soft
    deleting a chat ends its parked responses the same way
    (`server/query_and_chat/chat_backend.py:_end_parked_responses`); a hard
    delete removes them with the chat. The checkpoint row owns its dumps,
    which are saved under unique IDs: ending a checkpoint
    (`db/chat_response.py:finish_checkpoint__no_commit`, also through
    `db/chat_checkpoint.py:interrupt_response__no_commit`) or replacing it
    returns its dumps, and the caller deletes them after commit
    (`file_store/staging.py:delete_files_best_effort`). Ownerless repair
    (`chat/run_store.py:interrupt_ownerless_responses`) keeps a parked
    response, which has no owner by design, and ends a `RUNNING` response or a
    `SUSPENDED` one without a checkpoint, with its rows; the inbox lists such
    a selected response for repair. Only a parked selected response blocks sends
    (`server/query_and_chat/chat_backend.py:_reject_while_user_input_waits`); a waiting agent does
    not. A send that the route let through before the response parked fails
    in `prepare_chat_turn` once it holds admission, since its parent is the
    parked response. The checkpoint owns only its programs' dumps: a parked
    program's staged files are its documents' connector files, saved by
    reference, not copied. An approval of a tool whose current
    policy (`chat/tool_approvals.py:action_now_blocked`, also used by the
    session grant) is Blocked saves `REJECTED` with `decided_via` `POLICY` and
    returns 200; the model reads that the tool is disabled, and the card's
    outcome is `disabled`. A decision that repeats the saved one returns 200
    with the row's `decided_via`, also after the response ends or the policy
    changes. An `approve_session` on a row the user approved once upgrades it
    to a session grant; every request that a grant decides ends with the
    outcome `approved_for_chat` (`HumanToolAnswer.standing`).
17. `chat-approval-records-replay` **A saved response shows the records its
    stream showed.** `db/chat_response.py:read_response_replay_data` loads the
    `approval_request` rows of an ended or suspended response and the child
    runs it shows, and the rows of the background agents that its
    `spawn_agent` and `send_message` calls started, directly or through
    their agents, at any status; those show in that call's card, with the
    agent's name (`ToolApprovalRequest.agent_name`). Every request shows the
    arguments saved on its row, so a replayed card equals the live one. An
    agent's request never shows in a live stream: the client sees
    `approvals_version` change in the session status
    (`db/approval_request.py:approvals_version`, also on the session load) and
    reloads.
    `chat/presentation.py:replay_response` sends a
    `tool_approval_request` for each, after the start of the card of the row's
    `tool_call_id`, in the order the requests opened, and a
    `tool_approval_resolved` for each decided row. The outcome comes from the
    same mapping as the stream: `chat/tool_approvals.py:ended_answer` then
    `chat/renderer.py:approval_outcome`; an `EXPIRED` row was withdrawn, so it
    replays as `cancelled`. A suspended response's waiting calls stay open and
    it ends with `awaiting_user`, as its stream did, so a reload shows
    decidable cards. A running response replays no records; its stream,
    through resume-stream, shows them. A program's request has the program
    call's ID. A stream that continues a suspended response replays its
    records, the resolutions of its waiting requests and its background
    agents' requests included, then `replay_end`; the run's live events send
    a waiting request's resolution again (`ResponsePresenter.replay`). A
    root's `question_request` rows replay the same way:
    `tool_question_request`, then `tool_question_resolved` for an ended row,
    with the card's answers or the typed `message`, at the asking call
    (`chat/renderer.py:question_resolved`).
18. `program-call-waits-in-cell` **A program's Ask call parks its
    program.** MCP tools stay program functions in code mode. A gated call
    opens its request through `ToolInvocation.nested_calls`
    (`agents/tools.py:NestedCallGate`), and its card shows at once on the
    observing `execute_code` or `wait_code` card, also for a cell that runs in
    the background. The program parks once it waits only for such calls
    ([[code-execution]]), the observation ends with `NestedInputWait`, and the
    run hands off as for a direct call: the parked cell is saved in
    `ChatFeatureState.code_cells`, and its dump goes to the file store with the
    checkpoint (`chat/restoration.py:persist_checkpoint_files`), under a
    unique ID that the checkpoint owns. The continuation loads the dump on any
    server and runs the approved call. A
    program too large to park fails the waiting call with
    `tools/tool_implementations/code_mode/cells.py:PARK_REFUSED_MESSAGE` and
    continues; the request ends `cancelled`. The events carry `nested_call`.
19. `policy-fixed-per-turn` **The policy is read once per turn.**
    `integrations/chat_tools.py:build_integration_chat_tools` resolves every
    action's policy when it builds the response's tools. A change applies from
    the next response; within it, only a session grant rechecks for Blocked
    (`chat/tool_approvals.py:open_tool_approval`), and the decision route
    rejects an approval of a now-blocked action.
20. `waiting-approval-blocks-send` **A chat that waits for the user starts
    no user turn.** `server/query_and_chat/chat_backend.py:_reject_while_user_input_waits`
    rejects `send-chat-message` and the pending-message submit and interrupt
    routes with `APPROVAL_PENDING` (409) while the chat's selected response is
    `SUSPENDED`. A live turn with an open card, a background agent's request
    and a parked response on another branch do not block. The send route
    checks before the
    stream starts, so the client gets a status, not a stream packet. Stop and
    withdraw stay open. A new route that starts a user turn in an existing
    chat must make the same check. A message typed while a question waits
    goes to the question answers route instead.

`Tool.enabled` gates MCP tools everywhere and OpenAPI tools only in Default
Chat: see [[plugins#openapi-enabled-default-chat-only]].

---

## Decisions

- **One row per MCP tool, one row per OpenAPI schema.** MCP tools come from a
  live server, so each is stored with its schema and is enabled, attached and
  given Craft policies on its own. An OpenAPI schema is the admin's own
  document: its operations attach as a group, and an edit takes effect on the
  next turn with no sync.
- **Validate before publish.** The staged flow keeps the saved server untouched
  until authentication and discovery succeed. A failed edit leaves the working
  configuration in place, and an abandoned OAuth attempt expires with no
  partial server. The direct routes `POST /admin/mcp/servers/create` and
  `POST /admin/mcp/server` save without discovery. The web UI sets up and
  authenticates only through `/admin/mcp/setup`.

---

## Known issues

- The Slack and Discord bots have no approval buttons, so they get no Ask
  action. An admin sets an action to Allow, or the agent sets it to Allow, to
  let a bot run it.
- An MCP server or OpenAPI tool made through the admin MCP or tool routes has
  no integration, so chat offers none of its actions.

- Schema placeholders are a plain string replace.
  `build_custom_tools_from_openapi_schema_and_headers` replaces
  `CHAT_SESSION_ID`, `MESSAGE_ID`, `USER_ID` and `USER_EMAIL` anywhere in the
  JSON, descriptions included. Headers are not templated. An anonymous user's
  email is substituted as `anonymous` (`tools/tool_constructor.py`).
- OpenAPI response files have no chat-session stamp. `CustomTool` saves a file
  response as `FileOrigin.CHAT_UPLOAD` with no session. Only the
  `ChatMessage.files` branch of the chat-file access check can serve it
  ([[access-control]]).
- `server/features/tool/api.py:delete_custom_tool` maps any unexpected
  exception to a 400, on the assumption that an agent still uses the tool.
  `Persona__Tool.tool_id` cascades on delete, so that case cannot occur. The
  handler hides real errors.
- `MCPTransport.STDIO` is accepted by `MCPToolCreateRequest`, but the client
  has no STDIO path and uses `sse_client` for it. Do not remove the enum value:
  the column is a non-native enum, and a stored `STDIO` row would fail to load.
- A per-tool OAuth token replaces a static `Authorization` header with only a
  log warning (`tools/tool_implementations/custom/custom_tool.py:CustomTool`).
  Save rejects that pair only for `passthrough_auth`
  (`server/features/tool/api.py:_auth_settings`).
- On CE, `_apply_mcp_server_access` raises `EE_REQUIRED` for a non-public
  server. The Community downgrade ([[billing]]) makes only group-restricted
  servers public, so a server restricted to named users fails every access
  edit until an admin makes it public.
- A running response's approval cards come only from its stream, live or
  through resume-stream ([[#chat-approval-records-replay]]). A request that
  opens after the stream buffer stops (`chat/stream_buffer.py`: over
  `CHAT_STREAM_BUFFER_MAX_BYTES` compressed, or a cache write fails) is not
  buffered, so resume-stream ends at the gap or returns 404. A client that
  reconnects then shows the request only after the response parks and a
  reload replays it.
- During the first rollout of parked background agents, a status poll that
  an older server answers can end a parked agent as failed: older servers
  list a SUSPENDED agent as running and repair it as ownerless. Its requests
  stay undecided and its card cannot resume. Accepted for that rollout.

---

## Dependencies

- [[tools-framework]]: the `Tool` interface, per-turn construction and the
  error handling of `Tool.run`.
- [[auth-and-identity]]: `user.live_oauth_token`, the OpenAPI per-tool OAuth
  rows, and the attempt store.
- [[authorization]]: `require_permission`, and `assert_within_scope` (GATE 2) for
  scoped managers who set grants.
- [[editions-and-gating]]: the EE `make_mcp_server_private`, and the
  encryption used for setup attempts.
- [[agents-personas]]: `Persona__Tool` attaches these tools to agents.
- [[craft-external-apps]]: action policies (`GatedApp`) on MCP servers and
  their resolution, which the chat gate calls.
- [[agent-runtime]]: `AgentTool.approval_required`, `ToolApprovals`,
  `NestedCallGate`, `Agent.resume(answers=...)`, which continues a parked
  run with its saved decisions, and `Run.submit`, which gives a live run a
  Stop's rejection.
- [[craft-sessions]]: the `mcp_config_hash` restamp that the hot reload calls.

---

## Recipes

- `mcp-auth-type` **An MCP auth type.** Copy how `API_TOKEN` is handled; list the current set
  in `db/enums.py:MCPAuthenticationType`. Add validation in
  `MCPToolCreateRequest.validate_auth_configuration`, which resets the OAuth
  fields, `oauth_cimd_enabled` included, for every type that is not `OAUTH`.
  Handle the type in `server/features/mcp/credentials.py`
  (`resolve_mcp_credentials`, `ResolvedMCPCredentials`,
  `user_connection_status`), and in
  `_mcp_setup_headers` and the fingerprint in `server/features/mcp/api.py`.
  Add a test that a user without a credential gets the auth error, not a
  shared credential.
- `mcp-transport` **A transport.** Copy `STREAMABLE_HTTP`; list the set in
  `db/enums.py:MCPTransport`, and branch in
  `server/features/mcp/client.py:_create_mcp_client_function_runner`. Decide
  how OAuth refreshes: `auth` goes only to Streamable HTTP, because httpx auth
  reads the whole response body, which never ends on SSE. `MCPTool._run`
  refreshes before an SSE call instead. Add the transport to the probe in
  `server/features/mcp/setup_probe.py`.
- `mcp-server-setting` **A server-level setting.** Copy `oauth_cimd_enabled`. Store it through
  `_upsert_mcp_server`, add it to `_mcp_setup_configuration_fingerprint`
  ([[#setup-fingerprint]]), and reload Craft sessions if a session uses it
  ([[#craft-sessions-bake-mcp-config]]).
- `local-mcp-server` **Run a local MCP server to test against.** Start one of the FastMCP scripts
  in `backend/tests/integration/mock_services/mcp_test_server/` (list them with
  `ls`). Copy
  `backend/tests/integration/mock_services/mcp_test_server/run_mcp_server_no_auth.py`
  for a new one: it takes a port argument and serves `/mcp`. A loopback URL
  passes the SSRF guard only when the admin SSRF Protection level is
  `DISABLED` (or `MCP_SERVER_ALLOW_LOOPBACK` seeds it). Use `127.0.0.1`, not
  `localhost`: `localhost` is in `utils/url.py:BLOCKED_HOSTNAMES` and fails at
  every level.
- `investigate-missing-mcp-tools` **Investigate "my MCP tools are missing in chat".** In order: the server
  must have an integration (`integration.mcp_server_id`) with `enabled` true;
  a plugin that holds it must be linked to the agent (`persona__plugin`), or on
  the default assistant be visible and turned on for the user ([[plugins]]);
  `integration_status` must be connected for the user (a debug log "Skipping
  integration" names the problem); the policy must not be Blocked by the admin
  or the agent; a bot run also drops Ask actions; and a tool that the remote
  server added or renamed exists only after a sync ([[#mcp-schema-from-db]]).
- `investigate-stuck-approval` **Investigate "I approved, but the call did not
  run".** Query `approval_request` for the response (`chat_message_id`). A
  NULL `decision` means no decision was saved, and the response waits for it.
  `EXPIRED` means the call stopped waiting first: its program or run ended, or
  ownerless repair ended the response. When every row is decided and the
  response (`chat_message.response_status`) is still `SUSPENDED`, nothing
  resumed it: a session status read dispatches it again; search the API server
  log for "Could not start queued chat work" or "Could not dispatch queued
  chat input". An `ERROR` response with "could not continue after the
  approval" could not rebuild its run ([[#chat-approval-durable-wait]]).

---

## Verification

- Backend: `backend/tests/unit/onyx/server/features/mcp/`,
  `backend/tests/external_dependency_unit/server/features/mcp/`, the MCP and
  custom tests in `backend/tests/unit/onyx/tools/`, and
  `backend/tests/integration/tests/mcp/`, which runs the mock servers in
  `backend/tests/integration/mock_services/mcp_test_server/`.
- Playwright: `web/tests/e2e/mcp/` covers OAuth, per-user keys, group access
  and the default assistant.
- By hand, connect a per-user server as two users. The second user must get
  the connect error until they connect their own account.
