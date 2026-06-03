# Plan 2 — Onyx PAT Resolver

The Onyx PAT resolver brokers the sandbox's auth back to the Onyx API. It claims the
`SANDBOX_API_SERVER_URL` host on the [Plan 1](./01-framework.md) dispatcher, reads the sandbox's
persisted PAT, and overwrites the `Authorization` and `X-Onyx-Authorization` headers on the
outbound request — so onyx-cli in the pod runs against a non-secret placeholder while the real
CRAFT PAT lives only in the proxy.

## How it works

**What gets injected.** The resolver claims by host and port (the Onyx API is never an external app,
so `match` is ignored) and renders two headers:

| Header | Value |
|---|---|
| `Authorization` | `Bearer <pat>` |
| `X-Onyx-Authorization` | `Bearer <pat>` |

No tenant header is injected. The tenant is embedded in the PAT itself
(`onyx_pat_<tenant>.<random>`), and the server derives it from the token.
`get_hashed_bearer_token_from_request` checks `X-Onyx-Authorization` first, then `Authorization`
(`API_KEY_HEADER_ALTERNATIVE_NAME` / `API_KEY_HEADER_NAME` in `auth/constants.py`); both are
overwritten so whichever the server reads carries the real PAT.

**Where the PAT lives.** `Sandbox.encrypted_pat` (`SensitiveValue[str]` over `EncryptedString`)
stores the raw token encrypted on the sandbox row. The companion `PersonalAccessToken` row holds
only a SHA-256 `hashed_token` for the server's lookup path. The resolver loads the sandbox by
`ctx.sandbox.sandbox_id`, calls `get_value(apply_mask=False)` on `encrypted_pat`, and decrypts
in-process — `ENCRYPTION_KEY_SECRET` is wired into the proxy Deployment by Plan 1. The `Sandbox`
model has no `tenant_id` column; the resolver opens its session with the tenant carried on
`ctx.sandbox.tenant_id` (from `ResolvedSandbox`). `Sandbox.user_id` is `unique=True`, so the
one-pod, one-user, one-PAT identity is unambiguous.

**PAT lifecycle.** `ensure_sandbox_pat` (in `onyx/server/features/build/db/sandbox.py`) enforces
exactly one non-expired `CRAFT` PAT per user with a 30-day expiry (`_PAT_EXPIRATION_DAYS = 30`).
On any drift — no row, hash mismatch, multiple rows — it revokes the existing PATs, mints a fresh
one, and writes it back to `Sandbox.encrypted_pat`. The resolver always reads the currently
materialized value, so rotations take effect on the next request.

**NO_PROXY is loopback only.** `_proxy_main_container_env_vars()` in
`kubernetes_sandbox_manager.py` sets `NO_PROXY` to the `_NO_PROXY = "127.0.0.1,localhost"`
constant. Loopback is the only thing `firewall-init.sh` permits to bypass the proxy, so the Onyx
API host transits the proxy and the PAT is injected on the wire. (Previously a
`_compute_no_proxy_list()` helper appended the API host, which let clients try direct DNS and hit
`EPERM`; that helper is gone.)

**MITM trust.** Because the API host routes through the proxy, onyx-cli (pip-installed) trusts
the proxy's MITM CA. The K8s sandbox wires the bundle through the
standard env vars in `_proxy_main_container_env_vars()` — `REQUESTS_CA_BUNDLE`, `SSL_CERT_FILE`,
`CURL_CA_BUNDLE`, `NODE_EXTRA_CA_CERTS`, `GIT_SSL_CAINFO`, `AWS_CA_BUNDLE` — and `firewall-init.sh`
installs the CA into the system trust store via `update-ca-certificates`.

**Pod-side placeholder is non-empty.** onyx-cli treats an empty token as unconfigured, so the
pod's `ONYX_PAT` env ships a non-empty placeholder (`_PROXY_INJECTED_PLACEHOLDER =
"replaced_by_egress_proxy"`, a private constant in `kubernetes_sandbox_manager.py` shared with the
LLM apiKey placeholders) and the proxy overwrites both auth headers per the Plan 1
placeholder/overwrite contract.

**Failure mode.** A missing row, a `None` `encrypted_pat`, or a decrypt failure raises
`CredentialUnavailableError`; the dispatcher serves `http_403(SandboxProxyError.CREDENTIAL_ERROR)`.
The sandbox never sees a partial-auth fallback.

**Inert outside Kubernetes.** When `SANDBOX_API_SERVER_URL` is unset the resolver computes no API
host and `claims` always returns False. The docker self-hosted backend doesn't route through the
proxy and continues to inject the real PAT directly as the `ONYX_PAT` env var.

## Implementation

1. **`OnyxPatResolver`** (`onyx/sandbox_proxy/resolvers/onyx_pat.py`) implementing the Plan 1
   `CredentialResolver` protocol.
   - `claims(request, ctx)`: True iff `request.host` (case-insensitive) and `request.port` match the
     host and port of `SANDBOX_API_SERVER_URL` (port defaults to 443/80 by scheme); False when the
     var is unset.
   - `resolve(request, ctx)`: open a session via `get_session_with_tenant(tenant_id=ctx.sandbox.tenant_id)`,
     load `Sandbox` by `ctx.sandbox.sandbox_id`, decrypt `encrypted_pat`, return the two headers.
     Raise `CredentialUnavailableError` on missing row, `None` PAT, or decrypt failure.

2. **Pod-side placeholder swap** in `kubernetes_sandbox_manager.py`: the pod's `ONYX_PAT` env is
   set to `_PROXY_INJECTED_PLACEHOLDER`, and `_create_sandbox_pod` no longer takes an `onyx_pat`
   argument. `provision()` still takes and validates `onyx_pat` — it guarantees the PAT was minted
   and persisted to `Sandbox.encrypted_pat` before the pod starts, even though the pod only ships
   the placeholder. `ensure_sandbox_pat` is unchanged. The docker manager keeps injecting the real
   PAT.

3. **`NO_PROXY` collapse** to the `_NO_PROXY = "127.0.0.1,localhost"` constant (replacing
   `_compute_no_proxy_list()`), so the Onyx API host transits the proxy.

4. **Register in `build_resolvers()`** (`server.py`):
   `[OnyxPatResolver(), LLMProviderKeyResolver(), ExternalAppResolver()]`. Hosts are disjoint.

## Tests

- **Unit** (`backend/tests/unit/sandbox_proxy/test_onyx_pat_resolver.py`): with a fake `Sandbox`
  row and a patched `get_session_with_tenant`, the resolver returns both auth headers as
  `Bearer <pat>`. Negative cases — missing row, `encrypted_pat is None`, decrypt raises — each raise
  `CredentialUnavailableError`. `claims` is True for the API host and port (case-insensitive), False
  for others, and False when `SANDBOX_API_SERVER_URL` is unset.

- **External-dependency unit**
  (`backend/tests/external_dependency_unit/sandbox_proxy/test_onyx_pat_resolver.py`): against a
  real DB, provision a `Sandbox`, mint a PAT with `ensure_sandbox_pat`, run `OnyxPatResolver.resolve`
  with a real `InjectionContext`, and assert both auth headers carry the minted token — round-trips
  through real `EncryptedString`.

- **Pod spec** (`backend/tests/unit/onyx/server/features/build/sandbox/test_pod_spec.py`): the
  pod's `ONYX_PAT` env equals `_PROXY_INJECTED_PLACEHOLDER` (never the real token); `NO_PROXY` is
  loopback only.

## Out of scope

- PAT scopes — a CRAFT PAT grants full user access today; scope work is separate.
- Per-session PAT minting / revocation. The persistent per-sandbox PAT (30-day, rotated on
  re-provision) is sufficient.
- LLM provider keys — see [Plan 3](./03-llm-key.md).
- Any change to `_inject_credentials`, the matcher, or the gate's verdict paths — owned by
  [Plan 1](./01-framework.md).
