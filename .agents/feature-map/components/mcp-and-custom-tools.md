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
- **A user in chat** sees each call as a tool step. A missing, expired or
  rejected credential gives an error that tells the user to connect from the
  MCP menu. When Onyx cannot resolve any credential for a server, that
  server's tools are left out of the turn with no message. A down MCP server gives "Tool execution failed" with the reason. An
  OpenAPI tool says that it could not reach its server. Only that call fails;
  the turn continues.

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
- MCP server access grants and the per-server and per-user credential rows.

Its neighbours own:
- [[tools-framework]]: the `Tool` interface and per-turn construction.
- [[plugins]]: the plugin UI, Default Chat selection and personal preferences.
- [[auth-and-identity]]: the OpenAPI per-tool `OAuthConfig` and
  `OAuthUserToken` rows, and the OAuth attempt store.
- [[craft-external-apps]]: what a Craft action policy on an MCP tool means.
- [[mcp-server]]: the opposite direction, Onyx as an MCP server. Check who
  connects to whom before you change "MCP" code.

---

## Architecture

```
Admin config                                Turn time (tools/tool_constructor.py)
MCPServer --1:N--> Tool (mcp_server_id,      resolve_mcp_credentials(server, user)
   |               mcp_input_schema)           once per server -> one MCPTool per
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
CIMD off for that server, and the SDK then uses DCR.
`server/features/mcp/oauth_flow.py:validate_client_metadata_authorization`
pre-fetches the authorization URL, so that a provider that cannot read the
document fails in the Onyx form with that advice. The redirect URI and the
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

When resolution raises `MCPCredentialsError`, `_construct_tools_impl` leaves
that server's tools out of the turn and logs a warning. The user sees no error.

**Outbound safety.** `server/features/mcp/ssrf.py:mcp_ssrf_httpx_client_factory`
checks every request the MCP SDK makes, redirects included, at the admin SSRF
Protection level. `MCP_SERVER_ALLOW_PRIVATE_NETWORK` and
`MCP_SERVER_ALLOW_LOOPBACK` only seed that level's default. OpenAPI tools use
`tools/tool_implementations/custom/custom_tool.py:custom_tool_ssrf_params`:
self-hosted allows private targets at every level and loopback only at
`DISABLED`, cloud blocks all internal targets, and `ssrf_safe_request` does not
follow redirects.

**Craft action policies.** `update_mcp_server_simple` and `_publish_mcp_setup`
call `replace_workspace_action_policies` under `MANAGE_ACTIONS` with
`allow_scope=True`, so a scoped action manager can write them.
`update_mcp_server_with_tools` only sets `Tool.enabled` for the selected tools.
Policy precedence is in [[craft-external-apps]].

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
   tools need no sync.
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
    catches every exception and reports an auth error for a 401,
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
- OpenAPI tool names can collide on one agent. See [[tools-framework]].
- A per-tool OAuth token replaces a static `Authorization` header with only a
  log warning (`tools/tool_implementations/custom/custom_tool.py:CustomTool`).
  Save rejects that pair only for `passthrough_auth`
  (`server/features/tool/api.py:_validate_auth_settings`).
- On CE, `_apply_mcp_server_access` raises `EE_REQUIRED` for a non-public
  server. The Community downgrade ([[billing]]) makes only group-restricted
  servers public, so a server restricted to named users fails every access
  edit until an admin makes it public.

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
- [[craft-external-apps]]: Craft action policies (`GatedApp`) on MCP servers.
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
