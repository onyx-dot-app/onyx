# Plan 2 — Onyx PAT Resolver

Reference: [Plan 1](./01-framework.md) for project context and the shared seam this plugs into.

## Issues to Address

The sandbox authenticates back to the Onyx API server with a CRAFT-type Personal Access Token,
currently provisioned into the pod as the `ONYX_PAT` env var (`kubernetes_sandbox_manager.py`;
docker manager too). It's a 30-day token scoped to the owning user (`ensure_sandbox_pat`,
`sandbox.py`). This plan moves it out of the pod so it lives only in the proxy: an `OnyxPatResolver`
behind the [Plan 1](./01-framework.md) seam injects auth on requests to the Onyx API host.

## Important Notes

**Blocker — the Onyx API host is on `NO_PROXY`, so the proxy never sees that traffic.**
`_compute_no_proxy_list()` (`kubernetes_sandbox_manager.py`) adds the `SANDBOX_API_SERVER_URL`
hostname. Routing it through the proxy (step 2) is the central change of this plan; the external-app
and LLM hosts already traverse the proxy.

**onyx-cli works with a non-empty placeholder (confirmed against v1.0.3 Go source).** `IsConfigured()`
only checks the token is non-empty (no format validation), and the client sets it on **both**
`Authorization` and `X-Onyx-Authorization` — so per Plan 1's placeholder/overwrite contract, keep
`ONYX_PAT` a non-empty placeholder and have the resolver overwrite both headers. onyx-cli honors
`HTTPS_PROXY`/`NO_PROXY` (it clones `http.DefaultTransport`) and trusts the proxy MITM CA via
`SSL_CERT_FILE` (which Go honors; it ignores `REQUESTS_CA_BUNDLE`) plus the system-store install in
`firewall-init.sh` — so it routes through the proxy once off `NO_PROXY`. That path isn't exercised
today, so cover it with an integration test. `ONYX_SERVER_URL` stays set (onyx-cli appends `/api`).

**How the resolver obtains the PAT: read + decrypt the stored per-sandbox PAT (chosen).** The proxy
has `ENCRYPTION_KEY_SECRET` (Plan 1), so `OnyxPatResolver` reuses the PAT provisioning already mints
and stores encrypted on the `Sandbox` row (`ensure_sandbox_pat`): resolve `sandbox_id` from source
IP, read the row, decrypt. Provisioning is unchanged except the pod gets the placeholder; lifecycle
is unchanged (30-day, rotated on re-provision).

> **Pre-implementation check.** Confirm the `Sandbox` PAT column stores the *raw token encrypted*
> (recoverable), not just the SHA-256 lookup hash. If only the hash, persist the raw token encrypted
> at provisioning — acceptable under [[project_craft_beta_no_backcompat]]. This gates the chosen path.

*Alternative (not chosen):* the resolver mints + caches its own session PAT (`create_pat`), revoked
on teardown — tighter lifecycle, more machinery. Revisit only if we want per-session revocation.

**What the resolver injects.** `Authorization: Bearer <pat>` + `X-Onyx-Authorization: Bearer <pat>`,
and `X-Onyx-Tenant-ID = resolved.tenant_id` (the server resolves the PAT via the standard auth path
and the tenant via `add_onyx_tenant_id_middleware`).

Scopes are out of scope — see Plan 1 (a CRAFT PAT grants full user access today).

## Implementation Strategy

1. **Stop pre-populating the real PAT.** In `kubernetes_sandbox_manager.py` and the docker manager,
   set `ONYX_PAT` to the Plan 1 placeholder. `ensure_sandbox_pat` keeps minting and storing the
   encrypted PAT on the `Sandbox` row — the resolver reads from there.

2. **Route API traffic through the proxy.** Remove the `SANDBOX_API_SERVER_URL` hostname from
   `_compute_no_proxy_list()` (keep `127.0.0.1`/`localhost`); verify the proxy can reach the API host.

3. **Implement `OnyxPatResolver`** for the Onyx API host: read + decrypt the `Sandbox` PAT, overwrite
   both `Authorization` and `X-Onyx-Authorization`, set `X-Onyx-Tenant-ID`; fail closed if identity
   or token can't be resolved.

4. **Config**: an enable flag for the PAT resolver, separate from the LLM-key resolver.

## Tests

Integration test (CI only — [[feedback_no_integration_tests_locally]]) in
`backend/tests/integration/tests/craft/`:

- A request with the placeholder, routed through the proxy from a known sandbox IP, reaches the API
  and authenticates as the owning user (proxy overwrote the headers + set the tenant header).
- A request from an unidentifiable source IP to the API host is blocked (fail-closed).

External-dependency unit test in `sandbox_proxy/`: given a `Sandbox` row with a stored PAT, a request
from that sandbox's IP gets both auth headers overwritten and the tenant header set; and
`_compute_no_proxy_list` no longer contains the API host.
