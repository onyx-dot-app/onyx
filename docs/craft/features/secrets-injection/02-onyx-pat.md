# Plan 2 — Onyx PAT Resolver

Reference: [Plan 1](./01-framework.md) for the shared dispatcher and `InjectionContext` this plugs
into.

## Issues to Address

The sandbox authenticates back to the Onyx API with a CRAFT-type Personal Access Token, currently
provisioned into the pod as the `ONYX_PAT` env var (`kubernetes_sandbox_manager.py` and the docker
manager). It's a 30-day per-user token minted by `ensure_sandbox_pat` (`onyx/server/features/build/
db/sandbox.py`). This plan removes the real PAT from the pod and injects it from the proxy via an
`OnyxPatResolver` that claims the `SANDBOX_API_SERVER_URL` host on the [Plan 1](./01-framework.md)
dispatcher.

## Important Notes

**The PAT is materialized on the `Sandbox` row.** The `PersonalAccessToken` row stores only a
SHA-256 `hashed_token` (lookup-only); the raw token is recoverable from `Sandbox.encrypted_pat`
(`SensitiveValue[str]` over `EncryptedString`), written by `ensure_sandbox_pat` at provisioning
and read back with `get_value(apply_mask=False)`. The resolver loads it via
`ctx.sandbox.sandbox_id` (Plan 1's `InjectionContext` already pins the sandbox; `Sandbox.user_id`
is `unique=True`, so there's no ambiguity to resolve). The proxy decrypts in-process via
`ENCRYPTION_KEY_SECRET` (wired by Plan 1).

**PAT lifecycle.** `ensure_sandbox_pat` enforces exactly one non-expired `CRAFT` PAT per user with a
30-day expiry (`_PAT_EXPIRATION_DAYS`); on any state drift (no row, hash mismatch, multiple rows)
it revokes the existing PATs and mints a new one, updating `Sandbox.encrypted_pat`. The proxy
always reads the current materialized PAT.

**Depends on Plan 1's NO_PROXY change.** `_compute_no_proxy_list()` in
`kubernetes_sandbox_manager.py` currently adds the API host, so the pod talks to the API directly.
[Plan 1](./01-framework.md) (step 5) removes that entry; until it lands, the resolver claims a host
the proxy never sees.

**MITM TLS trust.** Once the API host is off `NO_PROXY`, onyx-cli (Python, pip-installed via
`onyx-cli==1.0.3`) must trust the proxy MITM CA. The K8s sandbox already wires the bundle through
the standard env vars — `REQUESTS_CA_BUNDLE`, `SSL_CERT_FILE`, `CURL_CA_BUNDLE`,
`NODE_EXTRA_CA_CERTS`, `GIT_SSL_CAINFO`, `AWS_CA_BUNDLE` — in `_proxy_main_container_env_vars()`,
and `firewall-init.sh` additionally installs the CA into the system trust store via
`update-ca-certificates`. This route isn't exercised today — integration test required.

**Pod-side placeholder is non-empty.** onyx-cli treats an empty token as unconfigured and the
client sets the same value on `Authorization` and `X-Onyx-Authorization` (the server accepts
either; see `API_KEY_HEADER_*` and `auth/utils.py`). Per Plan 1's placeholder/overwrite contract,
`ONYX_PAT` ships as a non-empty placeholder and the resolver overwrites both headers.

**Fail closed.** Per Plan 1, a missing or undecryptable PAT raises `CredentialUnavailableError`,
and the dispatcher serves `_http_403(_CODE_CREDENTIAL_UNAVAILABLE)`.

**Headers injected:**

| Header | Value |
|---|---|
| `Authorization` | `Bearer <pat>` |
| `X-Onyx-Authorization` | `Bearer <pat>` |
| `X-Onyx-Tenant-ID` | `ctx.sandbox.tenant_id` |

The server resolves the PAT via the standard auth path and the tenant via
`add_onyx_tenant_id_middleware`.

## Implementation Strategy

1. **`OnyxPatResolver`** implementing Plan 1's `CredentialResolver` Protocol.
   - `claims(host, match)`: returns True iff `host` is the host of `SANDBOX_API_SERVER_URL`. Ignores
     `match` (the Onyx API is never an external app).
   - `resolve(request, ctx)`: opens a session via `ctx.db_session_factory(ctx.sandbox.tenant_id)`,
     loads `Sandbox` by `ctx.sandbox.sandbox_id`, decrypts `encrypted_pat`. Returns the three
     headers above. Raises `CredentialUnavailableError` if the row is missing, `encrypted_pat` is
     `None`, or decryption fails.

2. **Pod-side placeholder swap** in `kubernetes_sandbox_manager.py`: set `ONYX_PAT` to the Plan 1
   placeholder constant. `ensure_sandbox_pat` is unchanged. The docker manager continues to inject
   the real PAT (docker self-hosted has no proxy wiring; see Plan 1's "Kubernetes-only" note).

3. **Register in `build_resolvers()`** (Plan 1, step 7) alongside `ExternalAppResolver` and
   `LLMProviderKeyResolver`. Hosts are disjoint; order is for clarity.

4. **Config flag** independent of the LLM-key resolver, so each pod-side placeholder change is
   atomic with its proxy-side flip.

## Tests

**Unit** (`backend/tests/unit/sandbox_proxy/test_onyx_pat_resolver.py`): given a fake `Sandbox` row
with a stored `encrypted_pat` and a mock `db_session_factory`, the resolver returns the three
headers with `Bearer <pat>` on `Authorization` + `X-Onyx-Authorization`. Negative cases — row
missing, `encrypted_pat is None`, decrypt raises — each raise `CredentialUnavailableError`. `claims`
returns True for the configured API host and False for others.

**External-dependency unit** in `backend/tests/external_dependency_unit/sandbox_proxy/`: against a
real DB, provision a `Sandbox`, run `OnyxPatResolver.resolve` with a real `InjectionContext`, and
assert the returned `Authorization` token matches what `ensure_sandbox_pat` minted (round-trips
through real `EncryptedString`).

**Integration** (CI only — [[feedback_no_integration_tests_locally]], gated under
[[feedback_no_local_craft_k8s_tests]]) in `backend/tests/integration/tests/craft/`: onyx-cli inside
a real sandbox calls the Onyx API. The placeholder leaves the pod; the proxy overwrites both auth
headers and the tenant header; the API authenticates the request as the sandbox's owning user. This
exercises the MITM-trust path that isn't exercised today.

## Out of scope

- PAT scopes — a CRAFT PAT grants full user access today; scope work is separate.
- Per-session PAT minting / revocation. The persistent per-sandbox PAT (30-day, rotated on
  re-provision) is sufficient.
- LLM provider keys — see [Plan 3](./03-llm-key.md).
- Any change to `_inject_credentials`, the matcher, or the gate's verdict paths — owned by
  [Plan 1](./01-framework.md).
