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
`web/src/app/admin/mcp-actions/`, `web/src/app/admin/openapi-actions/`,
`web/src/sections/actions/`, `web/src/lib/mcp/`

**Read first:** `[[tools-framework]]`. It owns the `Tool` interface, the
three-way discriminator on the `Tool` table, and `tool_constructor.py`'s
per-turn assembly loop. This document owns everything upstream of that loop:
how an admin creates the `Tool` row and its associated `MCPServer` /
`MCPConnectionConfig` / `OAuthConfig` rows in the first place.

---

## 1. What the user experiences

An admin who wants Onyx to call an outside system has two paths, both under
Admin > Actions.

**MCP server.** The admin enters a server URL, picks a transport, and picks an
auth mode (none, a shared API key, or OAuth). Onyx connects, lists the
server's tools, and shows them as one row per tool. The admin can restrict the
server to specific users or groups, or leave it public. If the server needs a
per-user credential (a personal API key, or a personal OAuth login), each user
who wants to use it connects it themselves from the chat's MCP dropdown,
separately from the admin's setup.

**OpenAPI (custom) action.** The admin pastes an OpenAPI 3.x schema and,
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
| `/admin/mcp-actions` | `web/src/app/admin/mcp-actions/page.tsx` | `MCPPageContent` (`web/src/sections/actions/MCPPageContent.tsx`) |
| `/admin/openapi-actions` | `web/src/app/admin/openapi-actions/page.tsx` | `OpenApiPageContent` (`web/src/sections/actions/OpenApiPageContent.tsx`) |

### HTTP endpoints, MCP (`backend/onyx/server/features/mcp/api.py`, prefixes `/mcp` and `/admin/mcp`)

| Method | Path | Handler | Notes |
|---|---|---|---|
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
stored `STDIO` row would fail to load and break the server list. The admin picks the transport explicitly in the create
form; there is no auto-negotiation. `create_mcp_server_simple` defaults to
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
- `API_TOKEN` or `OAUTH` with `auth_performer == ADMIN`: uses
  `mcp_server.admin_connection_config`, the single shared row with
  `user_email=""`. **Every user who can attach this server shares the same
  credential.** This is a deliberate admin choice (a service-account API key
  or a shared OAuth app), made explicitly at server-configuration time, not a
  default.
- `NONE`: no credential; only header templates/substitutions (if any) apply.

So: **MCP credentials are per server by default when the admin sets
`auth_performer=ADMIN`, and per user when the admin sets `auth_performer=PER_USER`
(or the server uses `PT_OAUTH`, which is inherently per user).** The admin's
choice at server-creation time is what decides this, and it is visible on the
`MCPServer` row, not implicit.

### 4.4 The MCP OAuth flow

1. **Connect.** The frontend calls `POST /mcp/oauth/connect` (user) or
   `/admin/mcp/oauth/connect` (admin, `is_admin=True`), both routed through
   `_connect_oauth` (`mcp/api.py`). It re-resolves OAuth client credentials
   against stored values, upserts the caller's `MCPConnectionConfig` (with
   `user_email=user.email` for a per-user flow), and dispatches to
   `start_known_provider_oauth_flow` or `start_auto_discovery_oauth_flow`
   (`mcp/oauth_flow.py`) depending on `oauth_provider_mode`. Either returns an
   `authorization_url` the frontend redirects the browser to, or reports
   `already_authenticated` if `credentials_usable` (valid, unexpired,
   `user_can_authenticate`) and the caller did not force re-auth.
2. **Attempt tracking.** The pending flow's state (server id, connection
   config id, a fingerprint of the OAuth client info, the return path) is
   stored keyed by an opaque `state` value in
   `mcp_oauth_attempt_store()` (`oauth_flow.py`, backed by
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
| changes credential scope (`auth_performer` handling) | `resolve_mcp_credentials` (§4.3), `requires_user_authentication`, `user_can_authenticate`, the MCP dropdown's per-user connect UI, and whether an existing shared credential must be migrated or invalidated |
| changes name disambiguation | `_disambiguate_mcp_tool_names`, `MCPTool.use_disambiguated_name`, and any saved chat history that stored the pre- or post-disambiguation name (`[[tools-framework]]` §7's tool-rename row applies here too) |
| changes the `Tool` discriminator (adds a fourth kind, or changes column semantics) | `[[tools-framework]]`'s `BUILT_IN_TOOL_MAP`/dispatch, `get_tools` (`db/tools.py`, its `only_openapi`/`only_connected_mcp` filters), `_upsert_db_tools`, `create_tool__no_commit` |
| changes `passthrough_auth` or per-tool OAuth resolution order | `tool_constructor.py`'s priority-1-then-2 logic (§4.5 step 5-6), `_validate_auth_settings` (`tool/api.py`) |
| changes MCP OAuth token storage shape | `extract_connection_data`, `mcp_token_expired`, `ResolvedMCPCredentials.build_headers`, and the SSRF-safe httpx factory that every one of these calls flows through |
| changes tool sync (`_sync_mcp_server_tools`) | admin-visible tool list going stale, the `with_for_update()` lock's contention behavior under concurrent refresh triggers |

---

## 8. How to verify a change

### Tests

```bash
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
  server-side `mcp_oauth_attempt_store()` entry keyed by `(user_id, state)`;
  a client that tries to shortcut the flow by POSTing arbitrary
  `code`/`server_id` values without a matching stored attempt gets rejected
  at the fingerprint/connection-config-id checks (§4.4 step 3).
