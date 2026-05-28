# Plan 3 — LLM Provider-Key Resolver

A Craft sandbox calls LLM provider APIs (OpenAI, Anthropic, Gemini, OpenRouter, plus any
tenant-configured custom endpoint) from `opencode serve`. Today the tenant's real provider keys
ship inside the pod, written into `OPENCODE_CONFIG_CONTENT` by `_build_provider_block` as
`provider.<name>.options.apiKey`. This plan moves those keys out of the pod: the pod ships
non-empty placeholders, and the egress proxy injects the real per-tenant key — read fresh from
`llm_provider` on each request — via an `LLMProviderKeyResolver` plugged into the
[Plan 1](./01-framework.md) dispatcher. Independent of [Plan 2](./02-onyx-pat.md).

## How it works

**Hosts the resolver claims.** The four canonical provider hosts plus each tenant's configured
`LLMProvider.api_base` host:

| Provider | Canonical host | Header convention |
|---|---|---|
| OpenAI | `api.openai.com` | `Authorization: Bearer {key}` |
| Anthropic | `api.anthropic.com` | `x-api-key: {key}` — leave `anthropic-version` intact |
| Google Gemini | `generativelanguage.googleapis.com` | `x-goog-api-key: {key}` (defensively strip any `?key=` query param) |
| OpenRouter | `openrouter.ai` | `Authorization: Bearer {key}` |

**Row resolution.** Tenancy is per-PostgreSQL-schema; `llm_provider` has no `tenant_id` column,
so the resolver opens a session via `ctx.db_session_factory(ctx.sandbox.tenant_id)` and reads the
tenant's rows directly. `llm_provider` has no uniqueness constraint on `provider`, so a tenant
can have multiple rows of the same type. For canonical hosts the resolver calls
`fetch_llm_provider_by_type_for_build_mode` (`build/db/build_session.py`), which prefers the
`build-mode-{type}` row and falls back to any row of that type. For a custom-host match the
resolver scans `fetch_all_build_mode_llm_providers` by `api_base`; that helper returns only rows
whose `name` matches `build-mode-%`, so a tenant's custom endpoint is routed only when configured
on a `build-mode-{type}` row. Both helpers return `LLMProviderView`, which decrypts `api_key`
through `EncryptedString` in `LLMProviderView.from_model()`. The proxy decrypts in-process via
the `ENCRYPTION_KEY_SECRET` Plan 1 wires into the Deployment.

**Placeholder / overwrite.** Opencode's AI SDK refuses to send when `options.apiKey` is unset, so
each provider block in `OPENCODE_CONFIG_CONTENT` ships a non-empty placeholder. The AI SDK turns
that into the per-provider wire header; the proxy overwrites only the named header (set/replace).
No `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` env vars are set in the pod. `baseURL` stays pointed at
the real provider host — traffic already MITMs through the proxy, so host-matching stays simple.

**Streaming-safe, fail-closed.** Per Plan 1, injection runs at header time without touching the
body or response, so SSE and long-running streams pass through untouched. A missing row,
unrenderable header, or undecryptable key raises `CredentialUnavailableError`; the dispatcher
serves `_http_403(_CODE_CREDENTIAL_ERROR)`.

**No hot-reload in the pod.** `opencode serve` reads `OPENCODE_CONFIG_CONTENT` once at startup
(sst/opencode#22213) and does not reload. The placeholder swap is a provisioning-time concern;
the proxy still injects the *current* tenant key on every request, so a stale placeholder in a
running pod is harmless. Key rotation takes effect on the next request, not the next pod.

**Kubernetes-only.** The egress proxy exists only in the K8s sandbox backend (Plan 1, "Kubernetes
only"). The docker manager keeps writing real keys into the opencode config.

**Keys keep living in `llm_provider`.** No migration into the `ExternalApp` data model; no sync
surface with the LLM-admin UI.

## Implementation

1. **Emit placeholders in the opencode config** (K8s manager only). In `_build_provider_block` /
   `build_multi_provider_opencode_config` (`opencode_config.py`), substitute the Plan 1
   placeholder for each `options.apiKey` behind the LLM-key resolver flag. `model`,
   `enabled_providers`, and the rest of each provider block are unchanged. The adjacent
   `block["api"]` → `provider.<name>.options.baseURL` fix is owned by
   [Plan 1](./01-framework.md) step 4 and lands atomically with this swap.

2. **`LLMProviderKeyResolver`** implementing Plan 1's `CredentialResolver` Protocol.
   - `claims(host, match)`: True iff `host` is one of the four canonical hosts or a
     `build-mode-*` row's `api_base` host. A per-tenant `api_base` cache is populated lazily on
     first claim and refreshed on provider-row updates.
   - `resolve(request, ctx)`: opens a session via `ctx.db_session_factory(ctx.sandbox.tenant_id)`;
     for a canonical host calls `fetch_llm_provider_by_type_for_build_mode`, for a custom host
     scans `fetch_all_build_mode_llm_providers` by `api_base`; pulls the decrypted key off
     `LLMProviderView.api_key` and renders the per-provider header; strips `?key=` on Gemini.
     Raises `CredentialUnavailableError` if no row matches or `api_key is None`.

3. **Register in `build_resolvers()`** (Plan 1 step 5) alongside `ExternalAppResolver` and
   `OnyxPatResolver`. Hosts are disjoint; order is for clarity.

4. **Config flag** independent of the PAT resolver, gating both the proxy-side resolver and the
   pod-side placeholder swap atomically.

## Tests

External-dependency unit tests (real Postgres for `llm_provider`; sandbox proxy under test;
upstream HTTP mocked) in `backend/tests/external_dependency_unit/sandbox_proxy/`:

- **One test per header convention.** OpenAI / OpenRouter → `Authorization: Bearer`; Anthropic →
  `x-api-key` with `anthropic-version` preserved; Gemini → `x-goog-api-key` with `?key=` stripped.
- **Custom `api_base`** — a tenant with `LLMProvider.api_base = https://llm.tenant.example/v1` on
  a `build-mode-anthropic` row: the resolver claims that host and injects the right key.
- **Build-mode naming required for custom hosts** — the same `api_base` on a non-`build-mode-*`
  row is not claimed.
- **Fail closed** — a canonical-host request from a tenant with no matching build-mode provider
  raises `CredentialUnavailableError` → 403.
- **Opencode config emits placeholder only** with the flag on, never a real key. Pin against the
  spec (documented header conventions + the Plan 1 placeholder constant), not against the
  resolver's own constants ([[feedback_tests_pin_spec_not_impl]]); a completeness check asserts
  the header table is exhaustive over the configured provider set.

## Out of scope

- LLM admin UI changes — keys keep being managed through the existing LLM-provider settings.
- Migrating `llm_provider` rows into the `ExternalApp` data model.
- Per-user (rather than per-tenant) LLM keys.
- Per-provider scoping or rotation; lifecycle is unchanged.
- The matcher, gating semantics, or anything [Plan 1](./01-framework.md) /
  [Plan 2](./02-onyx-pat.md) owns.
