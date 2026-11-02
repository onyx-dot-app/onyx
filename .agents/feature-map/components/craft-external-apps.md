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
is Disabled, the call fails at once with a `policy_denied` error that the agent
can read. When the app is not connected, the call fails with a message that
asks the user to connect it. A proxy restart or deploy expires every open
approval card, and the agent gets an error.

The agent can also ask the user to connect an app mid-turn. The turn pauses
and a connect card appears. The card resolves the request even when the user
already has credentials. It shows Connected only after the decision succeeds,
and stays retryable after a failure. When the user declines, the agent gets a
rejection and can choose another way.

The user can set personal Auto-approve, Ask or Disabled choices per action when
the admin allows it. A scheduled task has its own choices
([[craft-scheduled-tasks]]).

The agent never sees the real token or the Craft PAT. It holds a placeholder,
and the proxy writes the real value into the outbound request.

In this document "workspace" means the tenant-wide scope (workspace policy,
workspace DENY), never a session directory.

---

## Scope

This component owns:
- the `sandbox-proxy` process: TLS termination with its own CA, sandbox
  identity by source IP, destination checks, request recognition, the policy
  verdict, approval waits and credential injection;
- external-app models, provider catalogs, URL matching and OAuth token
  refresh;
- action policy resolution and storage, and the personal policy routes;
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
  Chat outside Craft runs MCP and OpenAPI calls with no policy check or approval
  ([[plugins]]).
- [[craft-streaming]]: how an approval or connect card reaches the live
  stream.
- [[craft-scheduled-tasks]]: task enablement and task choices, which this
  component reads.

---

## Architecture

```
sandbox process  --HTTP(S)_PROXY-->  sandbox-proxy (GateAddon, addons/gate.py)
 1 http_connect     caches the session tag from Proxy-Authorization on CONNECT
 2 destinations     resolve_destination: public, or the exact ONYX_SERVER_URL
                    host:port, or a Craft MCP origin the user can reach with
                    tenant SSRF settings that allow it; server_connect pins
                    the validated IPs (no second DNS lookup)
 3 identity         IdentityResolver.resolve_sandbox(source IP) -> sandbox,
                    user, tenant; unknown IP -> 403
 4 body cap         raw_content None or > PARSER_MAX_BODY_BYTES -> 403
 5 recognition      CompositeRequestEvaluator: external apps first, then MCP
                    None -> no gate; host-claiming resolvers may still inject
 6 session          verified session tag required for any matched request
 7 policy           resolve_action_policies; strictest action governs
                    DENY -> 403   ASK -> session grant or approval wait
 8 recheck          after an approval: same actions, live policy, same run
 9 injection        CredentialInjectionDispatcher: OnyxPat, MCPServer,
                    ExternalApp resolvers, first claim wins
10 forward          session-tag headers stripped first
```

**Recognition.** `sandbox_proxy/request_evaluator.py:ExternalAppRequestEvaluator`
loads enabled apps and calls `resolve_app_for_url`, which full-matches the URL
against each app's patterns in id order.
`external_apps/matching/engine.py:recognize_actions` maps the request to
catalog actions. A request that matches no catalog action gets one synthetic
`unspecified` action. `McpRequestEvaluator` attributes by host and longest path
prefix among the user's Craft-enabled servers
(`sandbox_proxy/resolvers/mcp_matching.py:match_request`), then parses the
JSON-RPC body (`sandbox_proxy/mcp_jsonrpc.py:classify_mcp_request`). Protocol
messages need a session and task access but no approval. `tools/call` gives one
action per tool, default Ask. Grants, policies and approvals key off
`GatedTarget.key`, never a display name ([[craft-admin#gated-app-identity-by-id]]).

**Policy precedence.** `db/action_policy.py:resolve_action_policies` and
`effective_action_policy` own it. For each action:

1. In a scheduled run, an app that is not enabled for the task is DENY.
2. Workspace DENY wins.
3. If the app does not allow user management
   (`GatedApp.users_can_manage_policies` false), the workspace policy applies.
4. Otherwise the stored choice applies: the task's choice in a scheduled run,
   or the user's personal choice in an interactive or Slack session. A stored
   choice can be looser than the workspace policy.
5. With no stored choice, a scheduled run uses Ask and an interactive session
   uses the workspace policy.

The workspace policy is the stored override or the catalog default. The gate
then forces `unspecified` to Ask unless it resolved to DENY
(`GateAddon._resolve_request_policies`). `AllMatchedActions` sorts actions
strictest first, and `governing_action` decides the verdict.

**Session and run context.** `db/action_policy.py:get_active_scheduled_task_context`
returns the run for a session only while the run is `RUNNING`. A scheduled
session with no running run raises, and the gate returns `no_active_session`.
Only interactive and Slack sessions fall back to personal choices.

**Approvals.** For an Ask verdict, `GateAddon._apply_session_grant` first looks
for an "approve for session" grant. Otherwise `_persist_approval_row` commits a
pending `ActionApproval`, announces it in Redis
(`sandbox_proxy/approval_cache.py:announce_approval`), and `_await_decision`
blocks on a wake key for `SANDBOX_APPROVAL_WAIT_TIMEOUT_SECONDS`. The decision
route writes through `backend/onyx/server/features/build/db/action_approval.py:try_record_decision` and pushes
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

**Personal Craft opt-out.** `MCPServerUserPreference.enabled_in_craft` is
enforced twice: `MCPServerResolver` refuses to inject credentials, and
`backend/onyx/db/mcp.py:get_craft_enabled_mcp_servers` leaves the server out of the Craft
list. A missing row means enabled. A preference change reloads running Craft
sessions through `server/features/mcp/api.py:_hot_reload_craft_sessions`, which
only restamps `mcp_config_hash` and does not push skill files.

**Credentials.** The sandbox holds only the placeholder
`server/features/build/configs.py:SANDBOX_PROXY_INJECTED_PLACEHOLDER`. The
resolvers claim a request by host or by the gate's attribution, never by the
placeholder value. `sandbox_proxy/server.py:build_resolvers` registers the
resolvers. `backend/onyx/sandbox_proxy/resolvers/onyx_pat.py:OnyxPatResolver` claims the Onyx API host
and injects the Craft PAT. `backend/onyx/sandbox_proxy/resolvers/mcp_server.py:MCPServerResolver`
injects MCP credentials. `backend/onyx/sandbox_proxy/resolvers/external_app.py:ExternalAppResolver` first
calls `ensure_fresh_credentials` (`external_apps/token_refresh.py`), which
refreshes an expiring OAuth token under a fleet-wide Redis lock and clears the
credential when the grant is dead. It then renders the app's `auth_template`
from organization and user credentials. It refuses with
`CredentialUnavailableError` when the app is missing or disabled, or when the
app has an `auth_template` but no headers render. Recognition loads only
enabled apps, so this check covers an app disabled during a request. Disabling
an app does not delete stored user credentials
(`backend/onyx/db/external_app.py:update_external_app`), so enabling it again
restores injection with the old secrets.

**OAuth connect.** `server/features/build/external_apps/oauth.py` binds each
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
3. `source-ip-is-identity` **The source IP is the identity boundary; the
   session tag is not.**
   `sandbox_proxy/sandbox_identity/resolution.py:IdentityResolver.resolve_session_by_id` accepts a tag
   only for a session of the IP-resolved user. A forged tag can only move an
   approval to another session of the same user. The comment in
   `GateAddon._extract_session_tag` explains why signing the MCP session header
   adds nothing. Keep the user check. The initial IP listing fails loudly when
   two sandboxes share an IP
   (`backend/onyx/sandbox_proxy/sandbox_identity/kubernetes.py:K8sInformerLookup._initial_list`,
   `backend/onyx/sandbox_proxy/sandbox_identity/docker.py:DockerEventsLookup._initial_sync`).
4. `url-patterns-credential-boundary` **An app's URL patterns are its
   credential boundary.** A wide pattern lets a prompt-injected agent spend the
   tenant's token on another account of the same vendor.
   `external_apps/url_glob.py:UrlGlob` forbids host wildcards for custom apps.
   Built-ins use regexes, and a malformed regex is skipped with a warning, not
   rejected. When patterns overlap, the lowest app id wins. Each app row holds
   its own copy of the patterns ([[#url-patterns-on-app-row]]).
5. `mcp-fails-closed` **External apps match before MCP, and MCP fails closed
   twice.** On a host that is both, the external-app attribution governs, and
   `MCPServerResolver.claims` defers. An unparsable body on a matched MCP host
   becomes a DENY action. Independently, `MCPServerResolver.resolve` refuses to
   inject onto a non-protocol request that has no gate verdict, and blocks a
   path outside every configured server URL on an MCP host. Evaluator and
   resolver both use `backend/onyx/sandbox_proxy/resolvers/mcp_matching.py` so they agree on attribution.
6. `body-cap-all-requests` **The body cap applies to every request, matched or
   not.** The check runs before recognition.
   `sandbox_proxy/addons/gate.py:PARSER_MAX_BODY_BYTES` is 32 MiB,
   the Anthropic Messages API limit; a larger body gets a 403, not the
   upstream's 413. A streamed body (`raw_content is None`) counts as oversize,
   so a future stream opt-in cannot skip the cap. Turning on request streaming
   anywhere in the chain blocks requests with `body_too_large`.
7. `unspecified-never-auto` **`unspecified` is never Auto-approve and never
   session-granted on an external app.** Personal or task choices cannot make
   an off-catalog request run unattended.
   `sandbox_proxy/addons/gate.py:GateAddon._session_grant` returns false for
   it, and `backend/onyx/server/features/build/approvals/api.py:ApprovalView.can_approve_for_session` refuses
   "approve for session" for any whole-domain action on an external app.
8. `approval-single-writer` **Approval decisions have one writer.** Only
   `backend/onyx/server/features/build/db/action_approval.py:try_record_decision` writes the decision of a
   pending row. It arbitrates between the user, a session grant and proxy
   expiry. The one other path, `GateAddon._apply_session_grant`, inserts a row
   that is already approved when an existing session grant covers the request.
   A new kind of held request must register in `GateAddon._parked` and
   `_inflight_tasks`, or a shutdown leaves its row pending until the orphan
   window.
9. `task-authority-ends-with-run` **A task's authority ends with its run.**
   Policy and recheck read the run on each request. A follow-up message in a
   finished scheduled session cannot use the task's choices or personal
   choices.
10. `pinned-upstream-addresses` **Pinned addresses only.**
    `GateAddon.server_connect` calls `backend/onyx/sandbox_proxy/destination_policy.py:resolve_destination`
    and pins the TCP connection to those addresses through
    `UpstreamEventLoop`. The hostname stays for SNI and certificate checks.
    Keep the real TLS tests when you upgrade mitmproxy.
11. `ca-key-stays-in-proxy` **The CA key stays in the proxy.** Kubernetes
    stores it in a Secret in the proxy namespace and projects only the
    certificate to sandboxes
    (`backend/onyx/sandbox_proxy/certificate_authority/kubernetes.py:K8sSecretCAStore`). Never mount the
    key or the Secret into the sandbox namespace. A CA rotation breaks TLS in
    every running sandbox, because sandboxes install the CA only at boot.
12. `url-patterns-on-app-row` **URL patterns live on the app row, not the
    provider.** `db/external_app.py:create_external_app` stores the patterns
    that the create request submits; the admin form sends the provider's
    descriptor patterns.
    `sandbox_proxy/request_evaluator.py:resolve_app_for_url` matches against
    the row. A pattern change in provider code reaches new apps only. Existing
    apps get no credential and no policy gate on the new host until a data
    migration updates their rows. A plain append works only for literal
    patterns. A provider that overrides `resolve_upstream_url_patterns`
    (Zendesk fills `{subdomain}` from organization credentials) needs per-row
    resolution. `db/external_app.py:update_external_app` resolves the patterns
    again on each save of credentials or patterns.
13. `connect-app-idempotent` **A connect-app decision is idempotent and
    retryable.** An expired or answered request is a no-op. When the sandbox is
    unreachable the route returns 502 and keeps the pending record, so the
    user can retry. The record expires with the opencode permission wait
    (`backend/onyx/server/features/build/connect_app.py:_PENDING_TTL_S`). "Connected" only allows the permission;
    it does not check that a credential exists. The proxy still gates the
    later calls.

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
- The MCP tool default (Ask) is written twice and the copies must agree:
  `sandbox_proxy/request_evaluator.py:MCP_TOOL_DEFAULT_POLICY` for the proxy and
  `db/action_policy.py:_catalog_defaults` for storage, which drops an override
  equal to the default. The constant of the same name in
  `server/features/mcp/api.py` has no readers; it is a false lead.

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
  every dot in the host: an unescaped dot matches any character, and the member
  app view
  (`backend/onyx/server/features/build/external_apps/api.py:_to_user_response`)
  leaves that pattern out of the app's service URLs, with no error.
- `credential-resolver` **A credential resolver.** Copy `OnyxPatResolver`; list the resolvers with
  `git ls-files backend/onyx/sandbox_proxy/resolvers/`. Register it in
  `build_resolvers`. Claim requests by a disjoint host set. Raise
  `CredentialUnavailableError` when a credential is required but missing;
  return empty headers only when the request may go out without one.
- `approval-end-state` **A new end state for an approval.** Write it through `try_record_decision`
  and wake the waiter ([[#approval-single-writer]]).
- `approval-point` **A new approval point.** Map its target to a `GatedApp`, so the session
  grant in `submit_decision` can cover it.
- `investigate-app-call-failed` **Investigate "the agent's call to an app failed".** Read the
  response the agent got first: a proxy 403 carries the error code from
  `backend/onyx/sandbox_proxy/errors.py`. A Disabled action returns
  `policy_denied` and writes no log line (`sandbox_proxy/addons/gate.py:GateAddon._resolve_and_match`).
  Then find the request in the `sandbox-proxy` log. An `egress_block` line
  carries the `reason`, and an `egress_allow` line carries the credential
  outcome. No response from the proxy and no log line means the request did not
  reach the proxy; check the lockdown in [[craft-sandboxes]].
- `setup-policy-test` **Set up a policy test.** Set one action to Disabled and one to Ask. The
  first returns 403 `policy_denied` with no proxy log line. The second shows an
  approval card, and after approval the proxy logs the decision as `APPROVED`.

---

## Verification

- Proxy: `backend/tests/unit/sandbox_proxy/` and
  `backend/tests/external_dependency_unit/sandbox_proxy/` (includes the
  approval claim race).
- Matching and policies: `backend/tests/unit/external_apps/`,
  `backend/tests/external_dependency_unit/permissions/` and
  `backend/tests/integration/tests/external_apps/`.
- Approval routes: `backend/tests/external_dependency_unit/craft/`.
- End to end with a real sandbox and proxy:
  `backend/tests/integration/tests/craft/docker_e2e/`.
