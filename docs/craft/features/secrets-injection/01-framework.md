# Plan 1 — Unified Credential-Injection Seam

Replaces the original Phase 1 (a host-keyed dispatcher run in `requestheaders`). Defines a single
host-claim seam, run from the gate's post-verdict path, that hosts three credential sources — Dane's
user-connected external apps, the per-sandbox Onyx PAT ([Plan 2](./02-onyx-pat.md)), and the
per-tenant LLM provider keys ([Plan 3](./03-llm-key.md)) — so long-lived secrets live only in the
proxy and never in the sandbox pod.

## Status after Dane's PRs land

Dane's stack delivers credential injection for one source — user-connected external apps:
`dane/ea-matcher` adds the matcher and the `DENY` / off-catalog gate paths; `dane/ea-inject-creds`
adds `GateAddon._inject_credentials`, called on `ALWAYS` and `ASK → APPROVED`. `DENY` blocks;
off-catalog forwards uncredentialed.

That covers external apps but not the two system credentials this project must broker:

| Source | Lives in | Why Dane's API doesn't fit |
|---|---|---|
| External-app credentials | `external_app_user_credentials` (per user × app) | What Dane built. |
| Onyx PAT ([Plan 2](./02-onyx-pat.md)) | `Sandbox.encrypted_pat` | The PAT lives on the `Sandbox` row, not on any `ExternalApp`; the Onyx API isn't a third-party app a user "connected". |
| LLM provider keys ([Plan 3](./03-llm-key.md)) | `llm_provider` rows (per tenant schema) | Per-tenant infrastructure, not user-connected. Modelling them as `ExternalApp`s would duplicate the LLM-admin data model. |

And: off-catalog hosts (the Onyx API, LLM providers) forward uncredentialed today.

## Issues to Address

1. The credential-injection seam is hard-wired to one source. No plug-in point for additional sources.
2. Off-catalog flows forward uncredentialed — fine for arbitrary traffic, wrong for known system
   endpoints.
3. Dane's fail-open semantic is right for user-in-the-loop apps but wrong for system credentials:
   a missing PAT or LLM key is a configuration error, and a Craft 403 is safer than fingerprinting
   the upstream's response.
4. The Onyx API host is on `NO_PROXY` (`_compute_no_proxy_list()`); its traffic bypasses the proxy
   entirely.

## Important Notes

**Two orthogonal concerns at the gate.** Action *gating* (matcher) decides whether a request needs
user approval. Credential *injection* (dispatcher) decides what auth headers go on the wire. They
compose at the gate but are independent — a request can need injection without gating (the Onyx API,
LLM calls).

**Disjoint host responsibilities.** External-app hosts come from `ExternalApp.upstream_url_patterns`;
the Onyx API host is `SANDBOX_API_SERVER_URL`; LLM provider hosts are the canonical provider hosts
plus each tenant's `LLMProvider.api_base`. The dispatcher logs at startup if two resolvers' claim
predicates overlap; the dispatcher unit test fails on overlap.

**Placeholder/overwrite contract.** The pod ships a non-empty placeholder for each credential header
(opencode's AI SDK throws on unset keys; onyx-cli treats empty as unconfigured). The proxy
overwrites only the named header.

**Decryption.** `ENCRYPTION_KEY_SECRET` is wired into the proxy Deployment (#11451), so
`LLMProviderView.from_model()` and the encrypted per-sandbox PAT both decrypt in-process.

**Kubernetes-only.** The egress proxy exists only in the K8s sandbox backend; the docker
self-hosted backend has no proxy wiring (`docker_sandbox_manager.py` has no `HTTPS_PROXY` /
`NO_PROXY` / CA env vars). This seam is a no-op on docker, which keeps injecting real credentials
via env vars. Step 6 below scopes pod-side changes to K8s.

**Supersedes the existing scaffold.** `onyx/sandbox_proxy/credential_injection.py` on
`whuang/craft-proxy-secrets-injection-scaffold` defines an early host-only dispatcher run in
`requestheaders`. This plan re-shapes it: post-verdict call site, `InjectionContext` that carries the
matcher's output, and `_inject_credentials` becomes a delegation to it.

## The seam

```python
@dataclass(frozen=True)
class InjectionContext:
    sandbox: ResolvedSandbox
    match: ActionMatch | None      # None for off-catalog flows
    db_session_factory: DBSessionFactory


class CredentialUnavailableError(Exception):
    """A resolver claimed a request but couldn't produce its credential."""


class CredentialResolver(Protocol):
    def claims(self, host: str, match: ActionMatch | None) -> bool:
        """Cheap, no-DB: does this resolver claim this request? First claim wins."""
        ...

    def resolve(self, request: http.Request, ctx: InjectionContext) -> dict[str, str]:
        """Render auth headers; raise CredentialUnavailableError to fail closed."""
        ...
```

`CredentialInjectionDispatcher.apply(flow, ctx)` iterates resolvers in registered order, picks the
first whose `claims(host, match)` returns True, calls `resolve`, and sets the returned headers on
`flow.request` (set/replace, never append). Outcome:

- No resolver claims → `PASS_THROUGH`.
- Resolver returns headers → `INJECTED`.
- Resolver raises `CredentialUnavailableError` (or any other exception) → `BLOCKED`; the gate maps
  it to `_http_403(_CODE_CREDENTIAL_UNAVAILABLE)`.

`apply` never raises.

## Implementation Strategy

1. **Refactor `GateAddon._inject_credentials`** to delegate:

   ```python
   ctx = InjectionContext(
       sandbox=sandbox, match=match, db_session_factory=self._db_session_factory
   )
   if self._dispatcher.apply(flow, ctx) is InjectionOutcome.BLOCKED:
       flow.response = _http_403(_CODE_CREDENTIAL_UNAVAILABLE)
   ```

   Move the call so it fires on `OFF_CATALOG` forwards too (today: only `ALWAYS` +
   `ASK → APPROVED`). `DENY` and `ASK → REJECTED` still skip injection. Pass `match=None` on
   `OFF_CATALOG`.

2. **`ExternalAppResolver`** — wraps Dane's existing logic.
   - `claims`: True iff `match is not None` (`ActionMatch.external_app_id` is non-Optional on the
     matcher today). The matcher already did URL→app resolution; the resolver delegates rather
     than redoing it.
   - `resolve`: opens a session via `ctx.db_session_factory(ctx.sandbox.tenant_id)` and calls Dane's
     existing `resolve_injection_headers(db, ctx.match.external_app_id, ctx.sandbox.user_id)`.
     Returns `{}` rather than raising on Dane's existing error paths — preserves the per-header
     fail-open contract he ships.

3. **`OnyxPatResolver`** ([Plan 2](./02-onyx-pat.md)) — claims by host.

4. **`LLMProviderKeyResolver`** ([Plan 3](./03-llm-key.md)) — claims by host (canonical + each
   tenant's `api_base`).

5. **Route the Onyx API through the proxy.** Today `_compute_no_proxy_list()` appends
   `SANDBOX_API_SERVER_URL`'s host to `NO_PROXY`, but `firewall-init.sh` drops everything except
   loopback and TCP to `sandbox-proxy:8080` — so clients honour `NO_PROXY`, try direct DNS, and
   get `EPERM`. Replace the function with a `_NO_PROXY = "127.0.0.1,localhost"` constant (loopback
   is the only thing the firewall permits to bypass the proxy) and a comment naming the firewall
   constraint; pin the value with a regression test so non-loopback entries can't be added by
   accident.

6. **Remove sandbox-side credentials** atomically with each resolver's flag (K8s only — see Note):
   - `ONYX_PAT` env in `kubernetes_sandbox_manager.py` → non-empty placeholder.
     `ensure_sandbox_pat` keeps minting and persisting the PAT on the `Sandbox` row. The docker
     manager continues to inject the real PAT.
   - LLM keys in `OPENCODE_CONFIG_CONTENT` (built by `opencode_config.py`) → non-empty placeholders
     for the K8s manager only; the docker manager keeps the real keys. While here, fix the existing
     `block["api"]` → `provider.<provider_name>.options.baseURL` mismatch
     ([[project_craft_beta_no_backcompat]]).

7. **Wire in `server.py`.** `build_resolvers()` returns
   `[OnyxPatResolver(), LLMProviderKeyResolver(), ExternalAppResolver()]`. The dispatcher is
   constructed once at startup and passed into `GateAddon`.

## Tests

- **Dispatcher unit** (mocked resolvers): first-claim-wins; unclaimed → `PASS_THROUGH`; resolver
  raises `CredentialUnavailableError` → `BLOCKED` → 403; the `InjectionContext` passed to `resolve`
  carries the right `sandbox` and `match`. Two resolvers that both claim the same `(host, match)`
  fail the test.
- **`ExternalAppResolver` regression**: Dane's existing external-dependency
  `test_credential_injection.py` passes unchanged — behaviour preserved.
- **Gate integration**: dispatcher runs on `ALWAYS` / `OFF_CATALOG` / `ASK → APPROVED`; skipped on
  `DENY` / `ASK → REJECTED`.
- **`NO_PROXY`**: the computed list no longer contains the Onyx API host.

Per-resolver tests live in [Plan 2](./02-onyx-pat.md) and [Plan 3](./03-llm-key.md).

## Landing plan (PRs)

Four PRs, in order; each flag-gated where behavioural and independently revertible.

1. **Seam extraction (refactor only).** Protocol + dispatcher + `ExternalAppResolver`.
   `_inject_credentials` becomes a delegation. Call site moves to fire on `OFF_CATALOG`. With only
   `ExternalAppResolver` registered, off-catalog stays a no-op. Dane's external-dep tests unchanged.
2. **Route the Onyx API through the proxy.** Per step 5: replace `_compute_no_proxy_list()` with a
   loopback-only constant and pin it with a regression test. Independently revertible. Also fixes
   a pre-existing `EPERM` on outbound calls to the Onyx API from inside a Craft sandbox.
3. **Onyx PAT resolver** ([Plan 2](./02-onyx-pat.md)).
4. **LLM provider-key resolver** ([Plan 3](./03-llm-key.md)).

(1) and (2) first, in either order; (3) and (4) parallel after.

## Out of scope

- Action gating (matcher) — unchanged.
- Migrating `llm_provider` rows into the `ExternalApp` data model.
- PAT scopes; a CRAFT PAT grants full user access today.
- The pre-body `requestheaders` injection seam and its `INJECTION_HANDLED_FLAG`. Both abandoned;
  injection runs post-verdict in the same `request` task as the gate.
