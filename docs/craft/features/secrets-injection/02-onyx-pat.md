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

**Per-sandbox key scope, not per-user.** Plan 1's `InjectionContext` carries
`sandbox: ResolvedSandbox`, so the resolver keys off `ctx.sandbox.sandbox_id` — it does not
re-resolve identity. A user can own multiple sandboxes; the dispatcher has already pinned the
request to one.

**Depends on Plan 1's NO_PROXY change.** `_compute_no_proxy_list()` in
`kubernetes_sandbox_manager.py` currently adds the API host so the pod talks to the API directly.
[Plan 1](./01-framework.md) (step 5) removes that entry; until it lands, the resolver claims a host
the proxy never sees.

**MITM TLS contract for onyx-cli (Go).** Once the API host is off `NO_PROXY`, onyx-cli must trust
the proxy MITM CA. It clones `http.DefaultTransport` (so it honors `HTTPS_PROXY`/`NO_PROXY`), and
Go's TLS stack reads `SSL_CERT_FILE` (it ignores `REQUESTS_CA_BUNDLE`); `firewall-init.sh` also
installs the CA into the system trust store. Both paths are already wired in
`_proxy_main_container_env_vars()`. This route isn't exercised today — integration test required.

**Pod-side placeholder is non-empty.** onyx-cli's Go `IsConfigured()` checks the token is non-empty
only (no format validation); the client sets the same value on `Authorization` and
`X-Onyx-Authorization`. Per Plan 1's placeholder/overwrite contract, `ONYX_PAT` ships as a non-empty
placeholder and the resolver overwrites both headers.

**PAT storage is already recoverable.** `Sandbox.encrypted_pat` is a `SensitiveValue[str]` over an
`EncryptedString` column — `ensure_sandbox_pat` stores the raw token encrypted at provisioning and
reads it back with `get_value(apply_mask=False)`. No schema or provisioning change needed.
(`PersonalAccessToken.hashed_token` is the API-side lookup hash, not what the proxy reads.) The
proxy decrypts in-process via `ENCRYPTION_KEY_SECRET` (already wired by Plan 1).

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

2. **Pod-side placeholder swap** in `kubernetes_sandbox_manager.py` and `docker_sandbox_manager.py`:
   set `ONYX_PAT` to the Plan 1 placeholder constant. `ensure_sandbox_pat` is unchanged.

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
