# Craft External Apps and Egress Proxy

> The egress proxy that every outbound request from a Craft sandbox goes
> through, and the external apps it gates. A request to a connected app or MCP
> server gets an action policy check, an approval wait for Ask actions, and the
> real credential; other public traffic goes out with no policy check.

**Verified against:** `73e0ae3c31` (2026-10-28)
**Edition:** CE

---

## User experience

A Craft user connects apps such as Slack, Gmail, Linear, GitHub, a custom API
or an MCP server, through OAuth or a credential form. The agent can then act as
that user on the service: read a channel, create an issue, send a draft. The
agent can also reach the public internet to install packages or read docs.

When an action is set to Ask, the agent's call waits. An approval card appears
in the session. The user can approve once, approve that action for the rest of
the session, or reject. With no decision within the wait window (180 seconds
by default), the request expires and the agent gets an error. When an action
is Blocked, the call fails at once with a `policy_denied` error that the agent
can read. When the app is not connected, the call fails with a message that
asks the user to connect it. A proxy restart or deploy expires every open
approval card, and the agent gets an error.

The agent can also ask the user to connect an app mid-turn. The turn pauses
and a connect card appears. The card resolves the request even when the user
already has credentials. It shows Connected only after the decision succeeds,
and stays retryable after a failure. When the user declines, the agent gets a
rejection and can choose another way.

A command that a chat runs in its VM gets the same wait while the chat's
`exec_command` call waits on it: the card shows on that call, with approve
once, approve for this command, or reject. A background process gets an
error instead ([[#chat-command-approvals]]).

The user can set personal Allow, Ask or Blocked choices per action when
the admin allows it. Scheduled tasks run in chat, not in Craft
([[craft-scheduled-tasks]]).

The agent never sees the real token or the Craft PAT. It holds a placeholder,
and the proxy writes the real value into the outbound request.

In this document "workspace" means the tenant-wide scope (workspace policy,
workspace DENY), never a session directory.

---

## Scope

This component owns:
- the `sandbox-proxy` process: TLS termination with its own CA, sandbox
  identity (source IP, or a relay-signed token for Firecracker VMs),
  destination checks, request recognition, the policy
  verdict, approval waits and credential injection;
- external-app models, provider catalogs, URL matching and OAuth token
  refresh;
- action policy resolution and storage, and the personal policy routes,
  which need Craft for external apps but not for MCP servers;
- the user app routes, OAuth connect and connect-app decisions;
- approval rows and the approval decision routes.

Neighbours:
- [[craft-admin]]: the admin routes and pages that write app configuration and
  workspace policies.
- [[craft-sandboxes]]: the in-sandbox lockdown that forces all traffic to this
  proxy, the CA trust install, the Craft PAT, and the rule that general
  internet egress is intentional.
- [[mcp-and-custom-tools]]: MCP server records, access lists and credential
  storage. This component only matches and injects for Craft-enabled servers.
  Chat applies the same MCP tool policies through its own gate and approval
  rows ([[mcp-and-custom-tools]]). Chat applies the same integration action
  policies to MCP and OpenAPI actions ([[plugins]]).
- [[craft-streaming]]: how an approval or connect card reaches the live
  stream.
- [[craft-scheduled-tasks]]: task enablement and task choices, which this
  component reads.

---

## Architecture

```
sandbox process  --HTTP(S)_PROXY-->  sandbox-proxy (GateAddon, addons/gate.py)
 1 http_connect     caches the session tag on CONNECT: Proxy-Authorization
                    basic auth (pod), or X-Onyx-Session-Hint (Firecracker)
 2 destinations     resolve_destination: public, or the exact ONYX_SERVER_URL
                    host:port, or a Craft MCP origin the user can reach with
                    tenant SSRF settings that allow it; server_connect pins
                    the validated IPs (no second DNS lookup); a
                    /microvm/ path on the API host -> 403 (host-agent routes)
 3 identity         signed `Proxy-Authorization: Bearer` on the connection's
                    first request -> SignedIdentityVerifier, bound to the
                    client connection; else IdentityResolver.resolve_sandbox
                    (source IP) -> sandbox, user, tenant; failure -> 403
 4 body cap         raw_content None or > PARSER_MAX_BODY_BYTES -> 403
 5 recognition      IntegrationRequestEvaluator: cached match targets pick
                    candidates by host or URL pattern, then match_request of
                    each candidate the user runs; API before MCP
                    None -> no gate; host-claiming resolvers may still inject
 6 session          verified session tag required for any matched request
 7 policy           resolve_craft_action_policies (a chat: its agent's
                    policies); strictest action governs
                    DENY -> 403   ASK -> session grant or approval wait
                    (a chat: command grant or approval wait while a call
                    waits on the command, else 403)
 8 recheck          after an approval: same actions, live policy, same run
 9 injection        CredentialInjectionDispatcher: OnyxPat, Integration
                    resolvers, first claim wins
10 forward          session-tag headers stripped first
```

**Recognition.** `sandbox_proxy/request_evaluator.py:IntegrationRequestEvaluator`
loads the integrations the sandbox owner can use (`_usable_ids`). For a Craft
session these are the integrations that are on for the user
([[mcp-and-custom-tools]] has the access rule).
`sandbox_proxy/usable_integrations.py:UsableIntegrations`
caches the integration ids of each user for 30 seconds, and the evaluator and
the resolver share it. A request whose session tag is a chat of the owner
reads, on each request and with no cache, the integrations of that chat
(`integrations/policy.py:chat_session_integrations`): the agent links, or,
in the chat of a scheduled run, the task's current links, also after the run
ends, narrowed by the chat's saved tool options (`apply_tool_options`),
Required ones kept. These can include a linked integration that the user
turned off. A chat on a custom agent that the user can no longer access
(`onyx/db/persona.py:user_can_access_persona`) reads no integrations, and the
default agent's integrations do not take their place. `UsableIntegrations` also caches, for 30 seconds per tenant, one
`IntegrationMatchTarget` (`sandbox_proxy/resolvers/mcp_matching.py`) for each
enabled integration: the MCP server URL, the OpenAPI base URL or the app URL
patterns. `load_match_targets` reads them with one query for each kind table.
`may_match` keeps the targets on the request host or URL, so a request to an
unrelated host runs no query. The evaluator calls `match_request` of each kind
(`integrations/kinds/`) only for these candidates that the user runs, and
reads the enabled integrations of the candidates for each request. A target
whose stored settings do not parse has a `load_error`, which blocks each
request of a user who runs it. An API integration wins
over an MCP server on a shared host, and the lowest id wins between API
integrations. For an external app, `external_apps/matching/engine.py:url_matches_patterns`
full-matches the URL against the app's patterns and `recognize_actions` maps
the request to catalog actions. A request that matches no catalog action gets
one synthetic `unspecified` action. A GraphQL request that also invokes a root
field no matched action covers gets `unspecified` next to the matched actions,
so an unknown mutation cannot ride on a known read's Allow. A custom GraphQL
app matches the same way under its endpoint URL
(`integrations/kinds/api.py:ApiKindHandler._match_graphql`): each root field
in the body maps to `query.<field>` or `mutation.<field>`, and a body with no
root field, or with one that is no action, adds `unspecified`. An MCP server attributes by host and path
prefix (`sandbox_proxy/resolvers/mcp_matching.py:match_request`) and returns
the prefix length in `RequestMatch`; the evaluator picks the longest prefix
across servers, and a tie matches nothing. The kind then parses the JSON-RPC
body (`sandbox_proxy/mcp_jsonrpc.py:classify_mcp_request`). Protocol messages
need a session and task access but no approval. `tools/call` gives one action
per tool. Its default is the default of the `integration_action` row. Grants,
policies and approvals key off `GatedTarget.integration_id`, never a display
name.

**Policy precedence.** `integrations/craft.py:resolve_craft_action_policies`
calls the one policy function (`integrations/policy.py:resolve_action_policies`)
with the interactive approval mode and the stored actions, so Ask keeps the
approval wait. An interactive session and the task catalog pass empty link
settings, which inherit each action; no link (`None`) would block each
action. The policy function itself makes each `always_asks` action
(`unspecified`) Ask unless it is Blocked. The gate maps Allow, Ask and Blocked
to the `ActionPolicy` values that approval rows store
(`sandbox_proxy/addons/gate.py:resolve_gate_policies`). A request from a chat
VM takes the policies of the agent of that chat
(`integrations/policy.py:resolve_chat_action_policies`), and the evaluator
matches it against that agent's integrations, linked ones that the user
turned off included. The chat's saved tool options narrow both as they narrow
the chat tools (`integrations/policy.py:apply_tool_options`). The evaluator
does not match an integration that the chat turned off, unless it is
Required: the proxy injects no credential and applies no policy, so a
request to a public API still goes out without the app's credentials. An
action that the chat turned off on an integration that still matches is
Blocked. A chat Ask gets `approval_needs_tool`. Its detail names
the chat tools to call instead, and the connect tool for a user with no
sign-in, or says that the app has no tool for the request, as for a custom app (`sandbox_proxy/addons/gate.py:_app_tool_hint`). `AllMatchedActions` sorts actions
strictest first, and `governing_action` decides the verdict.

**Approvals.** For an Ask verdict, `GateAddon._apply_session_grant` first looks
for an "approve for session" grant. Otherwise `_persist_approval_row` commits a
pending `ActionApproval`, announces it in Redis
(`sandbox_proxy/approval_cache.py:announce_approval`), and `_await_decision`
blocks on a wake key for `SANDBOX_APPROVAL_WAIT_TIMEOUT_SECONDS`. The decision
route writes through `backend/onyx/db/action_approval.py:try_record_decision` and pushes
the wake key. On timeout the gate claims `EXPIRED`, or reads the decision that
won the race (`_claim_expired_or_read_winner`). "Approve for session" in
`backend/onyx/server/features/build/approvals/api.py:submit_decision` also approves the session's other pending
rows that the grant covers, and caches the grant
(`approval_cache.hydrate_session_grants`). The approval routes treat rows older
than the wait timeout as orphaned. After approval, `_recheck_approval`
evaluates the request again and checks live policy and run context before it
forwards. On SIGTERM, `sandbox_proxy/server.py:_install_signal_handlers` marks
the proxy not ready and runs `GateAddon.drain_inflight`, which claims
`EXPIRED` (or reads the winner) for each parked approval and wakes it.

**Connect-app requests.** The agent's `connect_app` tool is a no-op whose
opencode permission ask pauses the turn. The turn consumer announces the
request and stashes the context to answer it in the cache
(`server/features/build/connect_app.py`).
`backend/onyx/server/features/build/external_apps/api.py:resolve_connect_app_request` answers the
permission on the sandbox: allow for connected, reject for declined.

**Craft catalog.** Craft uses the integrations that are on for the user
(`integrations/craft.py:list_runnable_integrations`).
`server/features/build/sandbox/util/mcp_config.py:resolve_craft_mcp_servers`
writes the MCP integrations whose `integration_status` is connected (or that
have no sign-in) into the opencode config, with each Blocked action as a
disabled tool. The web reads
the Craft apps and MCP servers from the member list (`GET /integrations`,
`web/src/lib/integrations/craft.ts`), and
`integrations/craft.py:list_connectable_apps` lists the external apps the user
can still connect. No code reads `mcp_server.available_in_craft`. An
integration change reloads running Craft sessions through
`backend/onyx/integrations/service.py:reload_craft_sessions`. It restamps
`mcp_config_hash` and pushes the skill files of the affected users.

**Credentials.** The sandbox holds only the placeholder
`server/features/build/configs.py:SANDBOX_PROXY_INJECTED_PLACEHOLDER`. The
resolvers claim a request by host or by the gate's attribution, never by the
placeholder value. `sandbox_proxy/server.py:build_resolvers` registers the
resolvers. `backend/onyx/sandbox_proxy/resolvers/onyx_pat.py:OnyxPatResolver` claims the Onyx API host
and injects the Craft PAT. `backend/onyx/sandbox_proxy/resolvers/integration.py:IntegrationResolver`
injects the credential of the matched integration through
`integrations/call_credentials.py:resolve_call_credentials`: `resolve_connection`
(which refreshes a token that expires soon) and `render_headers`; an OAuth
integration sends its access token as a bearer token. It sets
`CURRENT_TENANT_ID_CONTEXTVAR` to the sandbox tenant around this, because a
refresh reads the tenant from the context. It checks again that
the integration is enabled and that the request still matches the endpoint in
its kind row, because the gate matched against cached targets. Otherwise, or on
a connection problem, it refuses with `CredentialUnavailableError`. An internal MCP host is reachable only
when the user has access to the integration of the server
(`IntegrationResolver.allows_destination`).

**OAuth connect.** `backend/onyx/integrations/oauth.py` binds each
attempt to the user, app and a fingerprint of the resolved OAuth
configuration: client, redirect and endpoints. The callback consumes the
attempt once, rejects it when the configuration changed after the start,
stores the credential, and pushes the user's skills. Providers with
per-account hosts (Zendesk) resolve OAuth endpoints from organization
credentials through `OAuthExternalAppProvider.resolve_oauth_flow`.

---

## Contracts and traps

1. `addon-error-fails-closed` **No addon error may let a request through.**
   mitmproxy forwards the original request when an addon raises.
   `sandbox_proxy/addons/gate.py:GateAddon.request` wraps the approval path and returns `internal_error`.
   If an approval row exists, `_terminalize_after_unhandled_error` ends it.
   Recognition and policy errors in `_resolve_and_match` also return 403. Keep
   every new branch inside these guards.
2. `deny-before-injection` **DENY returns before injection and forwarding.**
   No approval row is written. The upstream TLS connection can already be
   open, because mitmproxy connects before `request()` runs. Do not treat "a
   connection opened" as "the request was sent".
3. `source-ip-is-identity` **The source IP or the relay-signed token is the
   identity boundary; the session tag is not.** The signed path exists only with
   `SANDBOX_RUNTIME=firecracker`; with the default `pod` the proxy ignores
   `Bearer` headers. Firecracker VMs share the host relay's IP, so the relay
   stamps an EdDSA token per connection (`sandbox_proxy/sandbox_identity/signed.py`).
   The proxy holds node public keys only and checks the cache placement record
   (`microvm/registry.py`; no schema change).
   A bad token is a 403, never an IP fallback; a signed plain-HTTP connection
   allows one request. The relays reach the proxy over mTLS on a separate port
   (`sandbox_proxy/relay_tls.py`, Helm `craft.hostAgent.relayTls`); it pipes
   to the plain listener on loopback, so relay flows log a loopback source IP
   and the token check stays the identity check.
   `sandbox_proxy/sandbox_identity/resolution.py:IdentityResolver.resolve_session_by_id` accepts a tag
   only for a session of the IP-resolved user. A forged tag can only move an
   approval to another session of the same user. The comment in
   `GateAddon._extract_session_tag` explains why signing the MCP session header
   adds nothing. Keep the user check. A tag with a command ID is a chat's,
   and a tag without one is a build session's: each chat VM command sends
   `<chat session>.<command ID>` as the proxy URL user (`server/features/build/sandbox/firecracker/harness_sandbox.py:command_proxy_user`,
   parsed by `sandbox_proxy/addons/gate.py:parse_session_tag`), and `IdentityResolver.resolve_chat_session`
   accepts a chat of the owner that is not deleted. Such a request takes the
   agent policies of that chat (`integrations/policy.py:resolve_chat_action_policies`)
   with no chat grant and no run mode. Allow goes out, and Blocked is denied.
   Ask is held only while a call of the chat waits on the command
   ([[#chat-command-approvals]]); otherwise, as for a background process, it is
   refused with `approval_needs_tool`, which names the chat tool
   (`sandbox_proxy/addons/gate.py:_app_tool_hint`: `custom__<id>__<action key>` for a REST or GraphQL app,
   `app__<id>__<action>` for a preset), or says that the app has no tool for
   the request, as for a request that matches only `unspecified`. The command ID is a same-user hint like
   the session tag: a process of the VM can send another command's ID. The initial IP listing fails loudly when
   two sandboxes share an IP
   (`backend/onyx/sandbox_proxy/sandbox_identity/kubernetes.py:K8sInformerLookup._initial_list`,
   `backend/onyx/sandbox_proxy/sandbox_identity/docker.py:DockerEventsLookup._initial_sync`).
   A frozen cache rejects every sandbox created after it froze. The Kubernetes
   watch has a read deadline, and `K8sInformerLookup.is_synced` turns false
   when the last relist is stale, so `/healthz` fails and the liveness probe
   restarts the proxy.
4. `url-patterns-credential-boundary` **An app's URL patterns are its
   credential boundary.** A wide pattern lets a prompt-injected agent spend the
   tenant's token on another account of the same vendor.
   `external_apps/url_glob.py:UrlGlob` forbids host wildcards for custom apps.
   Built-ins use regexes, and a malformed regex is skipped with a warning, not
   rejected. When patterns overlap, the lowest app id wins. Each app row holds
   its own copy of the patterns ([[#url-patterns-on-app-row]]).
5. `mcp-fails-closed` **API integrations match before MCP, and MCP fails closed
   twice.** On a host that is both, the API attribution governs. An unparsable
   body on a matched MCP host becomes a DENY action. Independently,
   `IntegrationResolver` claims each host of an enabled MCP integration: with
   no gate verdict it refuses a non-protocol request, and it blocks a request
   outside every server URL that the user can use. The resolver injects for the
   integration the gate evaluated, never a re-match.
6. `body-cap-all-requests` **The body cap applies to every request, matched or
   not.** The check runs before recognition.
   `sandbox_proxy/addons/gate.py:PARSER_MAX_BODY_BYTES` is 32 MiB,
   the Anthropic Messages API limit; a larger body gets a 403, not the
   upstream's 413. A streamed body (`raw_content is None`) counts as oversize,
   so a future stream opt-in cannot skip the cap. Turning on request streaming
   anywhere in the chain blocks requests with `body_too_large`.
7. `unspecified-never-auto` **`unspecified` is never Allow and never
   session-granted on an external app.** Personal or task choices cannot make
   an off-catalog request run unattended.
   `sandbox_proxy/addons/gate.py:GateAddon._session_grant` returns false for
   it, and `backend/onyx/server/features/build/approvals/api.py:ApprovalView.can_approve_for_session` refuses
   "approve for session" by the same `always_asks` check. The rule covers
   only API apps: an MCP tool named `unspecified` follows the normal
   approval rules.
   The admin Actions tab (`web/src/sections/integrations/IntegrationActionsTab.tsx`)
   reads `always_asks` on each action and does not offer Allow for it.
8. `approval-single-writer` **Approval decisions have one writer.** Only
   `backend/onyx/db/action_approval.py:try_record_decision` writes the decision of a
   pending row. It arbitrates between the user, a session grant and proxy
   expiry. The one other path, `GateAddon._apply_session_grant`, inserts a row
   that is already approved when an existing session grant covers the request.
   A new kind of held request must register in `GateAddon._parked` and
   `_inflight_tasks`, or a shutdown leaves its row pending until the orphan
   window.
9. `pinned-upstream-addresses` **Pinned addresses only.**
   `GateAddon.server_connect` calls `backend/onyx/sandbox_proxy/destination_policy.py:resolve_destination`
   and pins the TCP connection to those addresses through
   `UpstreamEventLoop`. The hostname stays for SNI and certificate checks.
   Keep the real TLS tests when you upgrade mitmproxy.
10. `ca-key-stays-in-proxy` **The CA key stays in the proxy.** Kubernetes
    stores it in a Secret in the proxy namespace and projects only the
    certificate to sandboxes
    (`backend/onyx/sandbox_proxy/certificate_authority/kubernetes.py:K8sSecretCAStore`). Never mount the
    key or the Secret into the sandbox namespace. A CA rotation breaks TLS in
    every running sandbox, because sandboxes install the CA only at boot.
11. `url-patterns-on-app-row` **URL patterns live on the app row, not the
    provider.** `backend/onyx/db/integration.py:create_external_app_row__no_commit`
    stores the patterns of the create request; a preset gets the patterns of
    its provider.
    `sandbox_proxy/usable_integrations.py:load_match_targets` reads the
    patterns from the row. A pattern change in provider code reaches new apps only. Existing
    apps get no credential and no policy gate on the new host until a data
    migration updates their rows. A plain append works only for literal
    patterns. A provider that overrides `resolve_upstream_url_patterns`
    (Zendesk fills `{subdomain}` from organization credentials) needs per-row
    resolution. `backend/onyx/integrations/service.py:update_integration__no_commit`
    resolves the patterns again on each save of the preset settings.
12. `connect-app-idempotent` **A connect-app decision is idempotent and
    retryable.** An expired or answered request is a no-op. When the sandbox is
    unreachable the route returns 502 and keeps the pending record, so the
    user can retry. The record expires with the opencode permission wait
    (`backend/onyx/server/features/build/connect_app.py:_PENDING_TTL_S`). "Connected" only allows the permission;
    it does not check that a credential exists. The proxy still gates the
    later calls.
13. `chat-command-approvals` **A chat command's Ask waits only on a call that
    shows its card.** The `exec_command` or `write_stdin` call that waits on a
    command marks it in the foreground
    (`sandbox_proxy/approval_cache.py:mark_command_foreground`, renewed each
    second, 60 s TTL) through
    `tools/tool_implementations/sandbox/command_approvals.py:CommandApprovals`,
    which the harness calls before the start or the write
    (`server/features/build/sandbox/harness_base.py:CommandHold`). The gate holds the request only while the
    mark names the tagged chat, writes an `action_approval` row with
    `chat_session_id` and `command_id` (method, path and body as its payload;
    `body_bytes` in place of a body that is not JSON or is over 64 KB),
    announces it under the command ID, and sends no notification. It checks
    the mark again after the write and expires its own row when the call
    ended, so no row waits that no card shows. The call's watcher shows the row
    as a `ToolApprovalRequest` progress card and its end as the resolution;
    `HarnessSandbox._collect` does not yield while a row of the command waits.
    The user decides through `POST /chat/approvals/{id}/decision`
    (`server/query_and_chat/command_approvals.py:decide_command_approval`):
    approve once (also `approve_session`, from clients with no command
    scope), `approve_command` (`decided_via` COMMAND_GRANT, one cache key
    per command, chat and `integration:action` that the gate checks before it
    holds, which also approves the command's other waiting rows that the
    command's grants together cover), or reject. An approval of a request that
    the current policies block (`chat/tool_approvals.py:action_now_blocked`)
    saves a rejection by the policy (`decided_via` POLICY) and grants nothing.
    The decision records its row, saves the grant before the commit (a cache
    error records `decided_via` USER: approved once), commits, wakes the
    proxy, then scans the waiting rows: a request that misses the grant
    committed its row before that check, and two decisions never lock each
    other's rows. A grant covers the command until it exits, also after the
    call stops waiting on it (the gate checks it before the foreground mark),
    and never covers an action that always asks. The harness drops the
    command's grants when a call sees the command end
    (`server/features/build/sandbox/firecracker/harness_sandbox.py:_end_exec_session`,
    `sandbox_proxy/approval_cache.py:drop_command_grants`), so a process that the command left
    running gets none; the 4 h TTL (the VM command deadline) covers an end
    that no call reads. The
    recheck before forwarding checks a COMMAND_GRANT row against the current
    policy, as a SESSION_GRANT row. Only a call whose `ToolContext.
    shows_command_approvals` is set holds: a root agent of a streamed turn
    (`chat/agent.py:build_chat_agent`); a background agent or a
    `run_chat_turn` caller gets `approval_needs_tool`. When the last call of
    this process that waits on the command ends, `CommandApprovals.end`
    refuses the command's waiting rows: REJECTED by the user on a Stop,
    EXPIRED otherwise. Each card ends with its row's outcome; a stopped call
    reports no progress, so `chat/renderer.py:ToolRenderer.complete` closes
    its open cards as `cancelled`. These rows are not in
    `approval_request`, so the chat run state, replay and Stop routes never
    read them.

---

## Decisions

- **MITM instead of an SDK hook.** The proxy sees every request regardless of
  the tool or language the agent uses, and secrets never enter the sandbox.
  The cost: the proxy sees all sandbox HTTPS in plaintext. The log fields in
  `sandbox_proxy/logging_utils.py` hold tenant, sandbox, host, method, app,
  action and policy. Keep bodies and header values out of the logs.
- **Lazy token refresh at injection.** A scheduled refresh job is not needed,
  and a revoked grant shows as "disconnected" on the next request instead of
  forwarding a dead token.

---

## Known issues

- The proxy does not scrub responses. An upstream API that echoes request
  headers in its response body returns the injected credential to the agent.
- The MCP tool default comes from the server's unverified `readOnlyHint`
  (`integrations/kinds/mcp_server.py:mcp_action_default_policy`). The proxy and
  chat tool construction read it from the `integration_action` row.
- The evaluator loads the kind rows of each integration the user can use on
  each request. A change to the access or the on/off choice of a user reaches the proxy after up
  to 30 seconds.
- An external app or MCP server that the old admin routes create has no
  integration row until the integration routes replace them, so the proxy does
  not match it.
- The tech debt register holds
  [URL-pattern custom apps](../TECH-DEBT.md#url-pattern-custom-apps) and the
  [Linear and Notion presets hidden from the catalog](../TECH-DEBT.md#linear-and-notion-presets-hidden-from-the-catalog).

---

## Dependencies

- [[craft-sandboxes]]: the lockdown and CA trust that make this proxy the only
  way out, and the Craft PAT that `OnyxPatResolver` injects.
- [[craft-admin]]: writes app configuration and workspace policies.
- [[mcp-and-custom-tools]]: MCP server data, access lists and credentials
  (`resolve_mcp_credentials`).
- [[craft-sessions]]: `BuildSession`, the unit an approval belongs to.
- [[craft-streaming]]: surfaces approval and connect cards on the live stream.
  Only `connect_app` permission asks reach the user
  ([[craft-streaming#only-connect-app-asks-reach-user]]), so a new consent
  flow must go through this gate.
- [[craft-scheduled-tasks]]: task enablement and task choices.
- [[skills]]: skill files pushed after connect, disconnect and admin changes.
- [[notifications]]: the approval-requested notification
  (`GateAddon._notify_approval_requested`). The dedup key and severity rules
  of the shared `Notification` table apply to it.

---

## Recipes

- `built-in-app` **A built-in app.** Copy the `linear` provider; list the providers with
  `git ls-files backend/onyx/external_apps/providers/`. Add an
  `ExternalAppType` value, the provider class, and an entry in
  `external_apps/providers/registry.py:_PROVIDER_CLASSES`. Give it a catalog
  with `default_policy` per action and host-pinned regex patterns. Use OAuth
  through `OAuthExternalAppProvider`. Subclass `OnyxManagedExtApp` only when
  Onyx can own the OAuth client. Add a built-in skill in
  `skills/built_in.py:EXTERNAL_APP_BUILT_IN_SKILL_IDS`.
- `new-host-for-built-in-app` **A new host for an existing built-in app.** Copy the migration
  `backend/alembic/versions/3350a25df58e_add_sheets_and_slides_hosts_to_google_.py`.
  Add the pattern to the provider. Add catalog `EndpointSpec` entries for the
  new host (`external_apps/providers/actions.py`); without them every call is
  `unspecified` and goes to Ask ([[#unspecified-never-auto]]). Add any new
  OAuth scope. Write a data migration that appends the pattern to existing app
  rows ([[#url-patterns-on-app-row]]). Update the app's built-in skill files
  in `backend/onyx/skills/builtin/`; the agent learns the host and helpers
  only from them, and [[skills]] owns how they reach running sandboxes. Escape
  every dot in the host: an unescaped dot matches any character, and
  `backend/onyx/integrations/craft.py:craft_service_urls` leaves that pattern
  out of the app's service URLs, with no error.
- `credential-resolver` **A credential resolver.** Copy `OnyxPatResolver`; list the resolvers with
  `git ls-files backend/onyx/sandbox_proxy/resolvers/`. Register it in
  `build_resolvers`. Claim requests by a disjoint host set. Raise
  `CredentialUnavailableError` when a credential is required but missing;
  return empty headers only when the request may go out without one.
- `approval-end-state` **A new end state for an approval.** Write it through `try_record_decision`
  and wake the waiter ([[#approval-single-writer]]).
- `approval-point` **A new approval point.** Write the `integration_id` of its target on the
  approval row, so the session grant in `submit_decision` can cover it.
- `investigate-app-call-failed` **Investigate "the agent's call to an app failed".** Read the
  response the agent got first: a proxy 403 carries the error code from
  `backend/onyx/sandbox_proxy/errors.py`. A Blocked action returns
  `policy_denied` and writes no log line (`sandbox_proxy/addons/gate.py:GateAddon._resolve_and_match`).
  Then find the request in the `sandbox-proxy` log. An `egress_block` line
  carries the `reason`, and an `egress_allow` line carries the credential
  outcome. No response from the proxy and no log line means the request did not
  reach the proxy; check the lockdown in [[craft-sandboxes]].
- `setup-policy-test` **Set up a policy test.** Set one action to Blocked and one to Ask. The
  first returns 403 `policy_denied` with no proxy log line. The second shows an
  approval card, and after approval the proxy logs the decision as `APPROVED`.

---

## Verification

- Proxy: `backend/tests/unit/sandbox_proxy/` and
  `backend/tests/external_dependency_unit/sandbox_proxy/` (includes the
  approval claim race).
- Matching and policies: `backend/tests/unit/external_apps/` and
  `backend/tests/external_dependency_unit/integrations/`.
- Approval routes: `backend/tests/external_dependency_unit/craft/`.
- Chat command approvals: `backend/tests/unit/sandbox_proxy/test_gate.py`,
  `backend/tests/unit/sandbox_proxy/test_command_grants.py` and
  `backend/tests/external_dependency_unit/sandbox_proxy/test_chat_command_approvals.py`.
  Only a Firecracker VM proves the proxy URL user through the host relay.
- End to end with a real sandbox and proxy:
  `backend/tests/integration/tests/craft/docker_e2e/`.
