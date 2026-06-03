# Plan 3 — LLM Provider-Key Resolver

A Craft sandbox calls LLM provider APIs (OpenAI, Anthropic, OpenRouter — the
`BUILD_MODE_ALLOWED_PROVIDER_TYPES`) from `opencode serve`. The tenant's real
provider key used to ship inside the pod, written into `OPENCODE_CONFIG_CONTENT`
as `provider.<name>.options.apiKey`. This plan moves the key out: the pod ships
a non-empty placeholder, and the egress proxy injects the real per-tenant key —
read fresh from `llm_provider` on each request — via an `LLMProviderKeyResolver`
plugged into the [Plan 1](./01-framework.md) dispatcher. Independent of
[Plan 2](./02-onyx-pat.md).

## How it works

**Hosts the resolver claims.** The canonical host of each build-mode provider
type:

| Provider | Canonical host | Header convention |
|---|---|---|
| OpenAI | `api.openai.com` | `Authorization: Bearer {key}` |
| Anthropic | `api.anthropic.com` | `x-api-key: {key}` — `anthropic-version` left intact |
| OpenRouter | `openrouter.ai` | `Authorization: Bearer {key}` |

`claims()` matches `request.host` against this table; no DB session is opened.

**Row resolution.** Tenancy is per-PostgreSQL-schema, so the resolver opens a
session via `get_session_with_tenant(tenant_id=ctx.sandbox.tenant_id)`, loads the sandbox
owner (`fetch_user_by_id`), and calls `fetch_all_supported_build_llm_providers`
— the same access-scoped fetch provisioning uses. It then takes the first
provider of the claimed type, matching how provisioning picks the key
(`get_all_build_mode_llm_configs` dedups by type, first wins), so the injected
key is the one the sandbox was provisioned with, decrypted in-process.

**Placeholder / overwrite.** Opencode's AI SDK refuses to send when
`options.apiKey` is unset, so K8s provisioning swaps each provider's real key
for the shared proxy placeholder (`_PROXY_INJECTED_PLACEHOLDER`, the same
sentinel `ONYX_PAT` ships) before building `opencode.json`; `provider`, `model`,
and `api_base` are untouched so opencode still routes to the canonical host. The
AI SDK renders the placeholder into the per-provider wire header; the proxy
overwrites only the named header. No `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` env
vars are set in the pod.

**Streaming-safe, fail-closed.** Per Plan 1, injection runs at header time
without touching the body or response, so SSE and long-running streams pass
through untouched. A missing user, no accessible provider of the type, or an
unset key raises `CredentialUnavailableError`; the dispatcher serves
`http_403(SandboxProxyError.CREDENTIAL_ERROR)`.

**No hot-reload in the pod.** `opencode serve` reads its config once at startup
(sst/opencode#22213), but the proxy injects the current tenant key on every
request — so a stale placeholder in a running pod is harmless and key rotation
takes effect on the next request, not the next pod.

**Kubernetes-only.** The egress proxy exists only in the K8s sandbox backend
(Plan 1, "Kubernetes only"). The docker manager keeps writing real keys into the
opencode config.

## Implementation

1. **Swap keys for the placeholder at provision time** (K8s manager only).
   Before `build_multi_provider_opencode_config`, replace each
   `LLMProviderConfig.api_key` with `_PROXY_INJECTED_PLACEHOLDER`.

2. **`LLMProviderKeyResolver`** implementing Plan 1's `CredentialResolver`
   Protocol. `claims` matches `request.host` against the canonical-host table;
   `resolve` opens the tenant session, loads the user, fetches the access-scoped
   build providers, picks the first of the claimed type, and renders the
   per-provider header from the decrypted key.

3. **Register in `build_resolvers()`** alongside `OnyxPatResolver` and
   `ExternalAppResolver`. Host-claim sets are disjoint; order is for clarity.

## Tests

- **Unit** (`tests/unit/sandbox_proxy/test_llm_provider_key_resolver.py`): the
  canonical-host claim rule, the per-provider header conventions (pinned against
  the documented spec), first-of-type selection, the fail-closed cases, and a
  completeness check that the host table covers every
  `BUILD_MODE_ALLOWED_PROVIDER_TYPES`.
- **External-dependency unit**
  (`tests/external_dependency_unit/sandbox_proxy/test_llm_provider_key_resolver.py`):
  an access-scoped `llm_provider` row's key, stored encrypted, round-trips
  through real `EncryptedString` onto its wire header for a request to its
  canonical host.

## Out of scope

- **Custom `api_base` hosts.** Build-mode providers default to `api_base=None`
  (opencode uses the SDK's built-in base URL), so the canonical-host table
  covers the standard case. A provider pointed at a custom gateway is not
  claimed; supporting it would require a per-tenant host cache in `claims()`.
