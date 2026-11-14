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
- **A user in the web chat approves an MCP call.** Each MCP tool has an action
  policy: Auto-approve, Ask or Disabled. When unset it is Auto-approve for a
  tool the server marks read-only, else Ask, as in Craft
  (`db/action_policy.py:mcp_tool_default_policy`). A Disabled tool
  is not offered to the model. For an Ask tool the response pauses on an
  approval card with the call's arguments and a deadline. The user picks
  Approve once, Approve for this chat, or Reject. Approve once runs the exact
  call. Approve for this chat also runs later calls of that tool in the chat
  session with no card. Reject, or no decision within 10 minutes
  (`chat/tool_approvals.py:TOOL_APPROVAL_TIMEOUT`), gives the model a "did not
  run" result, and the answer continues. A policy change applies from the next message.
  Web, mobile, the widget, the CLI and API callers all show requests; a
  non-streaming API call returns early with them. The Slack and Discord bots
  run Ask tools without asking for now. Usage-only incognito chats, anonymous
  users, and background or hosted agent runs cannot wait: an Ask call gives the
  model an error that names the cause ([[#chat-approval-needs-waiting-client]]). The upgrade
  migration (`backend/alembic/versions/7c00f53ab75f_chat_tool_approvals.py`)
  writes Auto-approve for tools that exist then on servers not available in
  Craft, and on every server when the tenant has no `build_session` row (it
  never used Craft); it keeps existing policies. Craft servers of a tenant that
  used Craft keep their policies, and new tools use their default. If Craft is
  enabled on such a server later, those Auto-approve policies apply in Craft
  too. Older clients (mobile builds, CLI versions and pinned widgets from
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
Admin config                                Turn time (tools/tool_constructor.py)
MCPServer --1:N--> Tool (mcp_server_id,      resolve_mcp_credentials(server, user)
   |               mcp_input_schema,           once per server -> one MCPTool per
   |               mcp_output_schema)
   +--admin_connection_config (shared)          saved Tool row, schema from the DB
   +--MCPConnectionConfig per user_email
Tool (openapi_schema) ---------------------> build_custom_tools_from_openapi_schema_
   +--oauth_config_id -> OAuthConfig           and_headers: one CustomTool per
                                               operationId, all with the same Tool.id
```

**Staged MCP setup.** `server/features/mcp/api.py:setup_mcp_server` handles both
new servers and authentication edits:
1. `_prepare_mcp_setup` resolves masked fields against stored values and takes
   a fingerprint of the saved configuration (`_mcp_setup_configuration_fingerprint`).
2. For OAuth with no reusable grant,
   `server/features/mcp/setup_oauth.py:start_setup_oauth` returns an
   authorization URL. The pending request is encrypted and stored in
   `SETUP_OAUTH_ATTEMPTS` under a state with the `mcp-setup_` prefix. Nothing
   is written to the database.
3. `process_oauth_callback` sends a `mcp-setup_` state to `_complete_mcp_setup`,
   which exchanges the code into `TransientTokenStorage` and discovers tools.
4. `_publish_mcp_setup` locks the server, the gated app and the default
   assistant, checks the fingerprint again, and then writes the server,
   credentials, tools, Craft action policies and Default Chat selection in one
   transaction.

**Member OAuth for a saved server.** `_connect_oauth` stores an owner-bound
attempt in `server/features/mcp/oauth_flow.py:MCP_OAUTH_ATTEMPTS` (ten
minutes). The callback consumes it, checks access and the client fingerprint
again, and calls `server/features/mcp/oauth.py:complete_mcp_oauth_authorization`.
`refresh_mcp_oauth_token_if_expired` refreshes under a shared lock per
connection config, because providers rotate refresh tokens.

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

**Credential scope.** `server/features/mcp/credentials.py:resolve_mcp_credentials`
turns `auth_type`, `auth_performer` and the calling user into the credential.
The admin's choice at setup decides the scope, and the `MCPServer` row shows it:
- `API_TOKEN` with `ADMIN`: one shared token in `admin_connection_config`. Every
  user with access to the server uses it.
- `API_TOKEN` or `OAUTH` with `PER_USER`: the caller's own `MCPConnectionConfig`
  row, keyed by `user_email`. A user with no row cannot authenticate.
- `PT_OAUTH`: the caller's Onyx login token (`user.live_oauth_token`).
- `NONE`: no credential. A header template with required fields asks each user
  for values (`web/src/lib/mcp/auth.ts:getMcpAuthenticationFlow`).

`_construct_tools_impl` and `MCPTool._run` both use
`ResolvedMCPCredentials.can_authenticate_with_headers`. Construction excludes
servers with missing or rejected credentials before exposing tools to the model.
Refreshable OAuth tokens remain available. Request-supplied headers can replace
missing credentials, but denylisted headers and grants that need reauthentication
cannot pass this gate. Resolution errors also exclude the server and log a warning.

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
tools/tool_constructor.py:_construct_tools_impl   resolve_user_action_policies once per turn
  (db/action_policy.py: one batched core, _resolve_policies, with resolve_action_policies)
  (defaults: mcp_tool_default_policy(ToolConfiguration.mcp_read_only))
  DENY -> tool not offered    ASK -> MCPTool.approval = ToolApprovalScope
  Tool.bind -> AgentTool.approval_required
agents/tool_execution.py:ToolBatch.decide_call   (direct calls, and program calls
  through ToolInvocation.nested_calls, a NestedCallGate)
  -> coordinator ToolApprovals = chat/run_store.py:ChatRunStore.request_approval
     -> chat/tool_approvals.py:open_tool_approval
        session grant (current_action_policy not DENY) -> run
        cannot wait (signed out, unwatched, server stopping) -> error by cause
        else ApprovalRequest row -> PendingToolInput(expires_at = created_at + timeout)
     the runtime marks the request PendingToolInput.approval
  direct call waits in the run; program call waits in its cell; both in memory
  renderer sends tool_approval_request on the call's (or execute_code's) card
POST /chat/approvals/{id}/decision (public)   db/approval_request.py:record_approval_decision__no_commit
  then wake key chat_response_approval:{id}
ChatRunStore.poll_control   one exists_many reads the Stop keys and the wake keys
ChatRunStore._deliver_tool_decisions
  requests = the owned runs' Run.pending_inputs with PendingToolInput.approval
  reads woken responses, and all every APPROVAL_FALLBACK_POLL_SECONDS
  (that read also expires overdue rows, up to that interval late)
  -> Run.submit(tool_answer) -> input_ended (answer) -> tool_approval_resolved
     (a SESSION_GRANT decision is a standing answer -> "approved_for_chat")
user Stop: chat/execution.py:ChatTurnExecution._poll_control
  -> ChatRunStore.reject_waiting_approvals   REJECTED by USER where decision IS NULL
  -> then cancels the turn
a call that stops waiting, or a run that ends
  -> ToolApprovals.withdraw_approval = ChatRunStore.withdraw_approval
     expires the row if it still waits; returns the answer of a decision saved
     first (chat/tool_approvals.py:ended_answer), e.g. the Stop's rejection
  -> input_ended (that answer, or none -> "cancelled"); a direct call that the
     answer denies keeps the denial as its result
  ChatRunStore.release expires what is left by response
session load: db/chat_response.py:read_response_replay_data (ended responses)
  -> chat/presentation.py:replay_response   request + resolved on the call's card
```

A decision row is the only channel between the API pod that takes the
decision and the pod that owns the run. The `approval_request` row holds the
session, the waiting response (`chat_message_id`), the `GatedApp`, the action
ID, the decision, and for the saved record the step's call that shows the card
(`tool_call_id`), the tool name and its display name. The arguments come from
the stream packet, not the table. Craft's proxy keeps its own `action_approval` table
([[craft-external-apps]]). The table, the decision route and the card are
general, so future sandbox-proxy network approvals can reuse them. An
"approve_session" decision is a session grant: it also approves the action's
other pending rows in the chat session, and `has_session_grant` lets later
calls run with no row unless the policy is now DENY.

---

## Contracts and traps

1. `credential-resolution-single-point` **`resolve_mcp_credentials` is the only
   place that picks a credential.** A new auth type or performer must be
   handled in `server/features/mcp/credentials.py:resolve_mcp_credentials`.
   An unhandled combination must fail, not fall back to the shared admin
   credential.
2. `oauth-always-per-user` **OAuth is always per user.**
   `server/features/mcp/models.py:MCPToolCreateRequest.validate_auth_configuration`
   rejects OAuth with any performer other than `PER_USER`. The OAuth client
   registration is shared configuration. The admin's grant is the admin's own
   connection.
3. `token-forwarding-full-manager` **Forwarding a login token is a full-manager
   decision.** `passthrough_auth` and `PT_OAUTH` send each chatting user's Onyx
   token to the admin's URL.
   `server/features/tool/api.py:_validate_auth_settings` lets only a global
   `MANAGE_ACTIONS` holder turn it on or change the destinations or headers of
   such a tool. `server/features/mcp/api.py:_validate_mcp_setup` and
   `server/features/mcp/api.py:upsert_mcp_server` do the same for `PT_OAUTH`.
   Keep both opt-in.
4. `guarded-client-factory` **Every outbound MCP request must use the guarded
   client factory**, `server/features/mcp/ssrf.py:mcp_ssrf_httpx_client_factory`.
   The SDK builds URLs from server responses. A new call that makes its own
   `httpx.AsyncClient` reopens SSRF.
5. `mcp-schema-from-db` **MCP tool schemas come from the database.**
   `tools/tool_constructor.py:_construct_tools_impl` builds each `MCPTool` from
   `Tool.mcp_input_schema`. A change on the remote server reaches the model
   only after `server/features/mcp/api.py:_sync_mcp_server_tools` runs: on
   setup, and when a manager lists tools from the live server
   (`_list_mcp_tools_by_id` with `is_admin`, which
   `admin_list_mcp_tools_by_id` and `get_mcp_server_tools_snapshots` call). The
   member route `user_list_mcp_tools_by_id` discovers but never writes. OpenAPI
   tools need no sync. The same sync saves the tool's declared `outputSchema`
   in `Tool.mcp_output_schema`, and sets it to NULL when the server declares
   none. It also saves `annotations.readOnlyHint` in `Tool.mcp_read_only` (NULL
   when absent), which sets the Craft default policy
   ([[craft-external-apps]]). `server.action_policies` holds only stored
   overrides, so `MCPServerToolsEditor` reads each tool's default from
   `ToolSnapshot.default_action_policy` on the tool snapshot route.
6. `sync-matches-by-name` **Sync matches tools by name.**
   `server/features/mcp/api.py:_sync_mcp_server_tools` treats a tool that the
   remote server renames as a new tool: it is deleted and inserted again with
   a new `Tool.id`.
   `Persona__Tool` cascades, so every agent loses it, and its enabled flag
   resets. Deleting a server removes its tools from every agent in the same
   way.
7. `mcp-tool-user-id-none` **`Tool.user_id` is `None` for MCP tools.** Ownership
   is on `MCPServer.owner`. Check rights with `db/tools.py:can_manage_tool`,
   never with `tool.user_id == user.id`.
8. `access-grants-default-chat-only` **Server access grants gate attachment and
   Default Chat only.** `_construct_tools_impl` calls
   `backend/onyx/db/mcp.py:user_can_access_mcp_server` only for the default
   assistant. A custom agent that already has the server's tools keeps them
   for every user of that agent, after a grant is removed.
9. `destination-change-deletes-credentials` **A changed URL or auth scheme
   deletes user credentials.** `server/features/mcp/api.py:_upsert_mcp_server`
   calls `_invalidate_mcp_user_credentials` when the URL, auth scheme or header
   template changes, and `_prepare_mcp_setup` drops stored secrets for a new
   URL. A new destination must never receive credentials that were given for
   the old one.
10. `setup-fingerprint` **A new server-level setting must join the setup
    fingerprint.** An OAuth return can arrive minutes after setup starts.
    `server/features/mcp/api.py:_assert_mcp_setup_current` rejects it only
    when `_mcp_setup_configuration_fingerprint` changed. A setting left out of the
    fingerprint is overwritten without a conflict.
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
12. `reauth-mark-if-current` **A rejected credential is marked only if it is
    still current.**
    `MCPTool._run` marks it only for a 401 on a connection config whose headers
    the user manages
    (`server/features/mcp/credentials.py:uses_user_managed_headers`).
    `backend/onyx/db/mcp.py:mark_connection_config_reauth_required` compares
    the stored data with the data the call used, so a call with old values
    cannot mark a newer credential. The mark makes `connection_status` report
    `reauth_required`.
13. `craft-sessions-bake-mcp-config` **Craft sessions bake MCP config.** A change
    to a server's URL, access or `available_in_craft` must call
    `server/features/mcp/api.py:_hot_reload_craft_sessions`. Take
    `backend/onyx/db/mcp.py:affected_user_ids_for_mcp_server` before an access
    change or a delete; users who lose access are not in the
    set afterwards. The reload only restamps `mcp_config_hash`; it does not push
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
    only a signed-in owner's watched run can wait.**
    `chat/run_store.py:ChatRunStore.request_approval` gives
    `chat/tool_approvals.py:open_tool_approval` an `ApprovalBlocker`:
    `SIGNED_OUT` for an anonymous user, `SERVER_STOPPING` once the API server
    starts to shut down, `UNWATCHED_RUN` when `Run.has_event_listeners` is
    false, as for background subagents and hosted runs; foreground children
    such as deep research can wait. A `USAGE_ONLY`
    incognito turn has no run store, so the runtime's own error applies. Each
    cause has its own model-facing text in `chat/tool_approvals.py`; nothing
    about approvals goes into the system prompt or tool descriptions. Turns
    the server starts (queued messages, agent-result follow-ups) can wait too.
    The non-streaming API returns early: at each `tool_approval_request`,
    `gather_stream_full` reads the response's pending rows
    (`db/approval_request.py:get_pending_approval_ids`); a row is saved before
    its packet streams, so it returns once the stream has delivered the packet
    of every waiting request, and lists them all in
    `ChatFullResponse.pending_tool_approvals`. Closing the stream leaves the
    turn running. Requests that open later reach the caller through the resume
    stream. The Slack and Discord bots do not ask for approval, so
    their turns build no approval scope (`ChatTurnSetup.ask_for_approval`,
    `construct_tools(ask_for_approval=...)`); Disabled tools stay unbuilt.
    Only server-side callers set it: the Slack handler and evals pass it to
    `run_chat_turn`, and
    `server/query_and_chat/chat_backend.py:handle_send_chat_message` sets it
    for the Discord bot's service API key. Authentication marks that key
    (`db/api_key.py:ApiKeyAuthResult.is_discord_bot`: no owner and the bot's
    name, which no key can be renamed to) on `request.state`, so the send
    route opens no extra session. The client-supplied
    `SendMessageRequest.origin` never changes it.
16. `chat-approval-owner-delivers` **Only the run's owner applies a decision.**
    `server/query_and_chat/chat_backend.py:decide_approval` saves the row, then
    sets the response's wake key. `chat/run_store.py:ChatRunStore.poll_control`
    reads the wake keys and the Stop keys in one `exists_many`, and
    `ChatRunStore._deliver_tool_decisions` calls `Run.submit`. The requests are
    those that the owned runs wait on (`Run.pending_inputs`) and that the
    runtime marks as opened by `ToolApprovals` (`PendingToolInput.approval`).
    Requests from a `before_tool_call` hook or a question tool are not rows,
    and the store does not read or withdraw them. The row owns the lifecycle
    and deadline, and the store keeps no copy. A read every `APPROVAL_FALLBACK_POLL_SECONDS` covers a
    lost key and expires overdue rows, so expiry can be up to that interval
    late. `ChatRunStore.release` expires a run's open rows by response;
    `withdraw_approval` expires one by ID. When the response has no owner, the
    route expires its requests and returns 409. When the API server starts to
    shut down, `backend/onyx/main.py:_end_approval_waits_on_exit_signal` (chained to
    uvicorn's SIGTERM and SIGINT handlers, because uvicorn waits for open
    responses before the lifespan shutdown) calls
    `chat/tool_approvals.py:end_approval_waits`; the next control poll cancels
    runs that wait, their cards close as `cancelled`, and their streams end.
    The lifespan resets the flag at startup. A user Stop (the chat's stream
    Stop key, read by `chat/execution.py:ChatTurnExecution._poll_control`)
    first calls `ChatRunStore.reject_waiting_approvals`, which saves
    `REJECTED` by `USER` under the same `decision IS NULL` condition as the
    decision route, so a decision that races the Stop keeps whichever saved
    first. The runs then end, `withdraw_approval` returns the saved decision's
    answer, the card's outcome is `rejected`, and the call's saved result is
    the rejection text that the model reads in the next turn. A cancelled turn
    still sends `tool_approval_resolved` (`ChatTurnExecution._publish`). An
    approval of a tool whose
    current policy (`db/action_policy.py:current_action_policy`, also used by
    the session grant) is DENY saves `REJECTED` with `decided_via` `POLICY` and
    returns 200; the model reads that the tool is disabled, and the card's
    outcome is `disabled`. Deleting the tool's server deletes its rows; the
    owner's next read (`db/approval_request.py:settle_approval_requests__no_commit`)
    answers a call whose row is gone as `disabled`. While the response runs, an approval of a row that
    is already approved returns 200 with the row's `decided_via`. An
    `approve_session` on a row the user approved once upgrades it to a session
    grant and approves the waiting sibling requests; every request that a grant
    decides ends with the outcome `approved_for_chat`
    (`HumanToolAnswer.standing`). `chat/tool_approvals.py:TOOL_APPROVAL_TIMEOUT`
    is 10 minutes, well below `CHAT_EXECUTION_TIMEOUT_S`, so one wait cannot
    use up the turn. Several waits in a row can still reach the turn deadline.
17. `chat-approval-records-replay` **A saved response shows the records its
    stream showed.** `db/chat_response.py:read_response_replay_data` loads the
    `approval_request` rows of an ended response and its child runs, and
    `chat/presentation.py:replay_response` sends a `tool_approval_request` and a
    `tool_approval_resolved` for each, after the start of the card of the
    row's `tool_call_id`, in the order the requests opened. The outcome comes
    from the same mapping as the stream: `chat/tool_approvals.py:ended_answer`
    then `chat/renderer.py:approval_outcome`. An `EXPIRED` row that ended
    before its deadline was withdrawn, so it replays as `cancelled`; a row
    still undecided in an ended response also replays as `cancelled`. A
    running response replays no records; its stream, through resume-stream,
    shows them, and a waiting card stays decidable. A program's call is not
    saved, so its replayed request has empty arguments and the program call's
    ID.
18. `program-call-waits-in-cell` **A program's Ask call waits inside its
    cell.** MCP tools stay program functions in code mode.
    `tools/tool_implementations/code_mode/cells.py:CodeCell._decided_result`
    asks `ToolInvocation.nested_calls` (`agents/tools.py:NestedCallGate`) and
    blocks through `NestedCallGate.wait_for_input`, giving back the cell's
    running-cell slot while it waits. When the wait ends, the program
    continues only once a slot is free, so resumed cells never exceed
    `MAX_RUNNING_CELLS` (`CodeCell._update_waiting`). `execute_code` and `wait_code` keep
    waiting instead of returning, so the model spends no steps. The request is
    not saved with the run, and the events carry `nested_call`.
19. `policy-fixed-per-turn` **The policy is read once per turn.**
    `tools/tool_constructor.py:_construct_tools_impl` resolves every MCP tool's
    policy when it builds the turn's tools. A change applies from the next
    message; within the turn, only a session grant rechecks for DENY
    (`chat/tool_approvals.py:open_tool_approval`), and the decision route
    rejects an approval of a now-disabled tool.
20. `waiting-approval-blocks-send` **A chat that waits for an approval starts
    no user turn.** `server/query_and_chat/chat_backend.py:_reject_while_approval_waits`
    rejects `send-chat-message` and the pending-message submit and interrupt
    routes with `APPROVAL_PENDING` (409) while the user's chat has a pending
    row younger than the timeout
    (`db/approval_request.py:responses_waiting_for_approval`). A row whose
    response has no owner expires instead. The send route checks before the
    stream starts, so the client gets a status, not a stream packet. Stop and
    withdraw stay open. A new route that starts a user turn in an existing
    chat must make the same check.

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

- The Slack and Discord bots run Ask tools without approval until they get
  approval buttons (TODOs in `onyxbot/slack/handlers/handle_regular_answer.py`
  and `server/query_and_chat/chat_backend.py:handle_send_chat_message`).

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
  (`server/features/tool/api.py:_validate_auth_settings`).
- On CE, `_apply_mcp_server_access` raises `EE_REQUIRED` for a non-public
  server. The Community downgrade ([[billing]]) makes only group-restricted
  servers public, so a server restricted to named users fails every access
  edit until an admin makes it public.
- A saved chat shows no approval history. The approval packets come only from
  live runtime events; replay (`chat/presentation.py:replay_response`) renders
  saved results, so a reload after the response shows the call's result or
  error with no card.

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
  `NestedCallGate` and `Run.submit`, which pause and continue an approved call.
- [[craft-sessions]]: the `mcp_config_hash` restamp that the hot reload calls.

---

## Recipes

- `mcp-auth-type` **An MCP auth type.** Copy how `API_TOKEN` is handled; list the current set
  in `db/enums.py:MCPAuthenticationType`. Add validation in
  `MCPToolCreateRequest.validate_auth_configuration`, which resets the OAuth
  fields, `oauth_cimd_enabled` included, for every type that is not `OAUTH`.
  Handle the type in `server/features/mcp/credentials.py`
  (`resolve_mcp_credentials`, `ResolvedMCPCredentials`,
  `user_connection_status`, `uses_user_managed_headers`), and in
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
- `investigate-missing-mcp-tools` **Investigate "my MCP tools are missing in chat".** In order: the API server
  log has an `MCPCredentialsError` warning when the user has no usable
  credential; on the default assistant, `user_can_access_mcp_server` must pass
  and the user's `MCPServerUserPreference` must not turn the server off
  ([[plugins]]); `Tool.enabled` must be true; and a tool that the remote
  server added or renamed exists only after a sync ([[#mcp-schema-from-db]]).
- `investigate-stuck-approval` **Investigate "I approved, but the call did not
  run".** Query `approval_request` for the response (`chat_message_id`). A
  NULL `decision` means no decision was saved. `EXPIRED` means the deadline,
  the end of the run or a lost owner came first, and the route returned 409.
  A saved decision on a call that still waits means the owner did not apply
  it: check the `chat_response_approval:<id>` wake key, search the API server
  log for "Could not read tool approval wake-ups" or "Could not read tool
  approval decisions", and check that the pod that owns the response still
  runs ([[#chat-approval-owner-delivers]]).

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
