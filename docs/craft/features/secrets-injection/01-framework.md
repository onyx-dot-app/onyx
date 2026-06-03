# Plan 1 — Unified Credential-Injection Seam

A single host-claim dispatcher in the egress proxy, run from the gate's post-verdict path, hosts
three credential sources behind one Protocol: user-connected external apps, the per-sandbox Onyx
PAT ([Plan 2](./02-onyx-pat.md)), and per-tenant LLM provider keys ([Plan 3](./03-llm-key.md)).
Long-lived secrets live only in the proxy; the sandbox pod ships placeholders that the proxy
overwrites on the wire. Action gating (matcher) and credential injection (dispatcher) compose at
the gate but are independent — a request can need injection without gating (the Onyx API, LLM
calls).

## How it works

The gate's verdict ladder is unchanged: `_resolve_and_match` produces one of four outcomes —
off-catalog forward, `DENY` block, `ALWAYS` auto-approved forward, or `ASK` (which becomes
`APPROVED` / `REJECTED` / `EXPIRED` via the approval pipeline). Today only the two
forward-with-credentials paths (`ALWAYS` and `ASK → APPROVED`) call `_inject_credentials_or_block`,
which 403s with `SandboxProxyError.CREDENTIAL_ERROR` on a resolver exception and forwards otherwise.
Off-catalog forwards uncredentialed, even when it shouldn't (the Onyx API, LLM providers).

This plan generalises that single call site into a dispatcher with a uniform contract:

```python
@dataclass(frozen=True)
class InjectionContext:
    sandbox: ResolvedSandbox
    match: RequestMatch | None     # None on off-catalog flows


class CredentialUnavailableError(Exception):
    """A resolver claimed a request but couldn't produce its credential."""


class CredentialResolver(Protocol):
    def claims(self, request: http.Request, ctx: InjectionContext) -> bool:
        """Cheap, no-DB: does this resolver own this request? First claim wins."""
        ...

    def resolve(self, request: http.Request, ctx: InjectionContext) -> dict[str, str]:
        """Render auth headers; raise CredentialUnavailableError to fail closed."""
        ...
```

`CredentialInjectionDispatcher.apply(flow, ctx)` iterates resolvers in registered order, calls the
first whose `claims(request, ctx)` returns True, and sets the returned headers on `flow.request`
(set/replace, never append). The dispatcher never raises:

- No resolver claims → `PASS_THROUGH`.
- Resolver returns headers → `INJECTED`.
- Resolver raises `CredentialUnavailableError` (or any other exception) → `BLOCKED`; the gate maps
  it to `http_403(SandboxProxyError.CREDENTIAL_ERROR)`.

The dispatch points are the three verdicts that forward: `ALWAYS`, `ASK → APPROVED`, and
`OFF_CATALOG`. `DENY` and `ASK → REJECTED` still skip injection. The off-catalog path is the new
one — today's gate returns uncredentialed, and the dispatcher now runs there with `match=None` so
the Onyx PAT and LLM resolvers get a chance to claim.

**Fail policy.** Two layers, deliberately distinct. A resolver that raises
`CredentialUnavailableError` blocks the request (system credentials are configuration errors;
surfacing them as Craft 403s beats a fingerprintable upstream 401). Within the external-app
resolver, the existing `build_auth_headers` continues to silently drop an individual header whose
placeholder can't be rendered — that's correct for user-in-the-loop apps where the upstream 401
surfaces to the user. The dispatcher's outer `BLOCKED` and the renderer's per-header drop coexist.

**Claim disjointness.** External-app hosts come from `ExternalApp.upstream_url_patterns`; the Onyx
API host is `SANDBOX_API_SERVER_URL`; LLM hosts are the canonical provider hosts. These sets are
disjoint by construction. The dispatcher's unit test fails the build on overlap, and startup logs
any predicate collision.

**Placeholder / overwrite contract.** The pod ships a non-empty placeholder for each credential
header — opencode's AI SDK throws on unset keys and onyx-cli treats empty as unconfigured. The
proxy overwrites only the named header. The real secret never leaves the proxy.

## Resolvers

- **`ExternalAppResolver`** — claims iff `match is not None`. The matcher has already done URL→app
  resolution; the resolver opens a session via `get_session_with_tenant(tenant_id=ctx.sandbox.tenant_id)`
  and delegates to `resolve_injection_headers(db, ctx.match.external_app_id, ctx.sandbox.user_id)`.
  Behaviour identical to the current `_inject_credentials`.
- **`OnyxPatResolver`** — claims the `SANDBOX_API_SERVER_URL` host; reads `Sandbox.encrypted_pat`.
  See [Plan 2](./02-onyx-pat.md).
- **`LLMProviderKeyResolver`** — claims the canonical LLM provider hosts (custom `api_base` out of
  scope); reads `llm_provider` rows. See [Plan 3](./03-llm-key.md).

In-proxy decryption works because the proxy Deployment already has `ENCRYPTION_KEY_SECRET` wired.

**Kubernetes-only, and mandatory there.** The egress proxy exists only in the K8s sandbox backend,
where it is now unconditional: `provision()` requires `SANDBOX_PROXY_HOST` (and
`SANDBOX_API_SERVER_URL`) and always wires the initContainer, proxy env vars, and CA bundle — the
earlier `SANDBOX_PROXY_HOST`-empty skip for tests/dev is gone (#11604), so every secret-bearing
request provably transits the proxy. The docker self-hosted manager has no `HTTPS_PROXY` /
`NO_PROXY` / CA env vars and keeps injecting real credentials via env vars. Every pod-side
placeholder swap below is scoped to the K8s manager.

## Implementation

1. **Refactor the gate call site.** `_inject_credentials_or_block` delegates to the dispatcher:

   ```python
   ctx = InjectionContext(sandbox=sandbox, match=match)
   if self._dispatcher.apply(flow, ctx) is InjectionOutcome.BLOCKED:
       flow.response = http_403(SandboxProxyError.CREDENTIAL_ERROR)
   ```

   Add the third invocation for off-catalog forwards inside `_resolve_and_match`, just before its
   off-catalog `return None`, with `match=None`. `_inject_credentials` collapses into the
   `ExternalAppResolver`.

2. **Route the Onyx API through the proxy.** `firewall-init.sh` drops everything except loopback
   and TCP to `sandbox-proxy:8080`, so any host in `NO_PROXY` other than loopback makes clients try
   direct DNS and hit `EPERM`. The `_compute_no_proxy_list()` helper (which appended the API host)
   is replaced by a `_NO_PROXY = "127.0.0.1,localhost"` constant — loopback is the only thing the
   firewall permits to bypass the proxy. Pinned by a regression test.

3. **Add `OnyxPatResolver` and `LLMProviderKeyResolver`** per Plans 2 and 3.

4. **Swap pod-side credentials for placeholders** (K8s manager only):
   - `ONYX_PAT` env in `kubernetes_sandbox_manager.py` → non-empty placeholder. `ensure_sandbox_pat`
     keeps minting and persisting the PAT on the `Sandbox` row.
   - LLM keys in `OPENCODE_CONFIG_CONTENT` (built by `opencode_config.py`) → non-empty placeholders
     for each `options.apiKey`.

   Not yet landed: the pre-existing `block["api"]` → `provider.<provider_name>.options.baseURL`
   field-name bug in `_build_provider_block` (`opencode_config.py` still writes
   `block["api"] = provider_config.api_base`). Tracked separately; placeholder swaps shipped without it.

   The docker manager continues to inject real credentials in both cases.

5. **Wire in `server.py`.** `build_resolvers()` returns
   `[OnyxPatResolver(), LLMProviderKeyResolver(), ExternalAppResolver()]`. The dispatcher
   is constructed once at startup and passed into `GateAddon`.

## Tests

Reuse the shared helpers in `backend/tests/unit/sandbox_proxy/conftest.py` (`make_flow`,
`make_resolved_sandbox`, `StubResolver`).

- **Dispatcher unit (mocked resolvers).** First-claim-wins; unclaimed → `PASS_THROUGH`; resolver
  raises `CredentialUnavailableError` → `BLOCKED` → 403; the `InjectionContext` passed to `resolve`
  carries the right `sandbox` and `match`. Two resolvers that both claim the same `(host, match)`
  fail the build.
- **`ExternalAppResolver` regression.** The existing
  `backend/tests/external_dependency_unit/craft/test_credential_injection.py` passes unchanged.
- **Gate integration.** Dispatcher fires on `ALWAYS`, `OFF_CATALOG`, and `ASK → APPROVED`; skipped
  on `DENY` and `ASK → REJECTED`.
- **`NO_PROXY` regression.** Pins the `_NO_PROXY` constant so non-loopback entries can't be added
  by accident.

Per-resolver tests live in [Plan 2](./02-onyx-pat.md) and [Plan 3](./03-llm-key.md).

## Landing plan

Each step is an independently revertible PR (Craft is beta — no feature flags):

1. **Seam extraction (refactor only).** Protocol + dispatcher + `ExternalAppResolver`.
   `_inject_credentials` becomes a delegation; the off-catalog call site is added but, with only
   the external-app resolver registered, off-catalog stays a no-op. _Shipped._
2. **Route the Onyx API through the proxy.** Loopback-only `NO_PROXY`; also fixes a pre-existing
   `EPERM` on outbound Onyx API calls from the sandbox. _Shipped with the Onyx PAT resolver._
3. **Onyx PAT resolver** ([Plan 2](./02-onyx-pat.md)). _Shipped._
4. **LLM provider-key resolver** ([Plan 3](./03-llm-key.md)). _Shipped._

## Out of scope

- Action gating (matcher).
- Migrating `llm_provider` rows into the `ExternalApp` data model.
- PAT scopes — a CRAFT PAT grants full user access today.
- The pre-body `requestheaders` injection seam and its `INJECTION_HANDLED_FLAG`. Abandoned;
  injection runs post-verdict in the same `request` task as the gate.
