# Plan 2 — Onyx PAT Resolver

The Onyx PAT resolver brokers the sandbox's auth back to the Onyx API. It claims the
`SANDBOX_API_SERVER_URL` host on the [Plan 1](./01-framework.md) dispatcher, reads the sandbox's
persisted PAT, and sets the `Authorization`, `X-Onyx-Authorization`, and `X-Onyx-Tenant-ID` headers
on the outbound request — so onyx-cli in the pod runs against a non-secret placeholder while the
real CRAFT PAT lives only in the proxy.

## How it works

**What gets injected.** The resolver claims by host (the Onyx API is never an external app, so
`match` is ignored) and renders three headers:

| Header | Value |
|---|---|
| `Authorization` | `Bearer <pat>` |
| `X-Onyx-Authorization` | `Bearer <pat>` |
| `X-Onyx-Tenant-ID` | `ctx.sandbox.tenant_id` |

The server accepts the PAT on either auth header (`API_KEY_HEADER_NAME` /
`API_KEY_HEADER_ALTERNATIVE_NAME` in `auth/constants.py`) and reads the tenant via
`add_onyx_tenant_id_middleware`.

**Where the PAT lives.** `Sandbox.encrypted_pat` (`SensitiveValue[str]` over `EncryptedString`)
stores the raw token encrypted on the sandbox row. The companion `PersonalAccessToken` row holds
only a SHA-256 `hashed_token` for the server's lookup path. The resolver loads the sandbox by
`ctx.sandbox.sandbox_id`, calls `get_value(apply_mask=False)` on `encrypted_pat`, and decrypts
in-process — `ENCRYPTION_KEY_SECRET` is wired into the proxy Deployment by Plan 1.
`Sandbox.user_id` is `unique=True`, so the one-pod, one-user, one-PAT identity is unambiguous.

**PAT lifecycle.** `ensure_sandbox_pat` (in `onyx/server/features/build/db/sandbox.py`) enforces
exactly one non-expired `CRAFT` PAT per user with a 30-day expiry (`_PAT_EXPIRATION_DAYS = 30`).
On any drift — no row, hash mismatch, multiple rows — it revokes the existing PATs, mints a fresh
one, and writes it back to `Sandbox.encrypted_pat`. The resolver always reads the currently
materialized value, so rotations take effect on the next request.

**NO_PROXY.** Today `_compute_no_proxy_list()` in `kubernetes_sandbox_manager.py` appends the API
host to `NO_PROXY`, so traffic from the pod to the Onyx API bypasses the proxy. The resolver is
inert until [Plan 1](./01-framework.md) step 2 collapses `NO_PROXY` to loopback only; until then
it would claim a host the proxy never sees.

**MITM trust.** Once the API host routes through the proxy, onyx-cli (Python, pip-installed
`onyx-cli==1.0.3`) must trust the proxy's MITM CA. The K8s sandbox already wires the bundle
through the standard env vars in `_proxy_main_container_env_vars()` — `REQUESTS_CA_BUNDLE`,
`SSL_CERT_FILE`, `CURL_CA_BUNDLE`, `NODE_EXTRA_CA_CERTS`, `GIT_SSL_CAINFO`, `AWS_CA_BUNDLE` — and
`firewall-init.sh` installs the CA into the system trust store via `update-ca-certificates`. The
TLS path is in place; the resolver is its first real consumer.

**Pod-side placeholder is non-empty.** onyx-cli treats an empty token as unconfigured, so the
`ONYX_PAT` env var ships as a non-empty placeholder and the proxy overwrites both auth headers
per the Plan 1 placeholder/overwrite contract.

**Failure mode.** A missing row, a `None` `encrypted_pat`, or a decrypt failure raises
`CredentialUnavailableError`; the dispatcher serves `_http_403(_CODE_CREDENTIAL_ERROR)`. The
sandbox never sees a partial-auth fallback.

**Kubernetes only.** The docker self-hosted backend doesn't route through the proxy and continues
to inject the real PAT directly as the `ONYX_PAT` env var.

## Implementation

1. **`OnyxPatResolver`** implementing the Plan 1 `CredentialResolver` protocol.
   - `claims(host, match)`: True iff `host` is the host of `SANDBOX_API_SERVER_URL`.
   - `resolve(request, ctx)`: open a session via `ctx.db_session_factory(ctx.sandbox.tenant_id)`,
     load `Sandbox` by `ctx.sandbox.sandbox_id`, decrypt `encrypted_pat`, return the three
     headers. Raise `CredentialUnavailableError` on missing row, `None` PAT, or decrypt failure.

2. **Pod-side placeholder swap** in `kubernetes_sandbox_manager.py`: set `ONYX_PAT` to the Plan 1
   placeholder constant. `ensure_sandbox_pat` is unchanged. The docker manager keeps injecting
   the real PAT.

3. **Register in `build_resolvers()`** (Plan 1 step 5) alongside `ExternalAppResolver` and
   `LLMProviderKeyResolver`. Hosts are disjoint.

4. **Config flag** independent of the LLM-key resolver, so the pod-side placeholder swap and the
   proxy-side resolver flip atomically.

## Tests

- **Unit** (`backend/tests/unit/sandbox_proxy/test_onyx_pat_resolver.py`): given a fake `Sandbox`
  row with a stored `encrypted_pat` and a mock `db_session_factory`, the resolver returns the
  three headers with `Bearer <pat>` on both auth headers. Negative cases — missing row,
  `encrypted_pat is None`, decrypt raises — each raise `CredentialUnavailableError`. `claims` is
  True for the API host and False for others.

- **External-dependency unit** in `backend/tests/external_dependency_unit/sandbox_proxy/`: against
  a real DB, provision a `Sandbox`, run `OnyxPatResolver.resolve` with a real `InjectionContext`,
  assert the returned `Authorization` token matches what `ensure_sandbox_pat` minted — round-trips
  through real `EncryptedString`.

- **Integration** (CI only) in `backend/tests/integration/tests/craft/`: onyx-cli inside a real
  sandbox calls the Onyx API. The placeholder leaves the pod; the proxy overwrites both auth
  headers and the tenant header; the API authenticates the request as the sandbox's owning user.
  This is the first end-to-end exercise of the MITM-trust path.

## Out of scope

- PAT scopes — a CRAFT PAT grants full user access today; scope work is separate.
- Per-session PAT minting / revocation. The persistent per-sandbox PAT (30-day, rotated on
  re-provision) is sufficient.
- LLM provider keys — see [Plan 3](./03-llm-key.md).
- Any change to `_inject_credentials`, the matcher, or the gate's verdict paths — owned by
  [Plan 1](./01-framework.md).
