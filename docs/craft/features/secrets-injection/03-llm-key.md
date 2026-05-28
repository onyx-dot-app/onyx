# Plan 3 — LLM Provider-Key Resolver

Reference: [Plan 1](./01-framework.md) for the shared dispatcher and `InjectionContext` this plugs
into. Independent of [Plan 2](./02-onyx-pat.md).

## Issues to Address

LLM provider keys are baked into the sandbox today. `_build_provider_block` in
`onyx/server/features/build/sandbox/util/opencode_config.py` writes
`provider.<id>.options.apiKey = <real key>`, and the resulting JSON is mounted as
`OPENCODE_CONFIG_CONTENT` on the pod. This plan removes the key from the pod and injects it from
the proxy via an `LLMProviderKeyResolver` that claims the canonical provider hosts plus each
tenant's `LLMProvider.api_base`.

While here, fix an existing bug: a tenant's custom endpoint is currently written as `block["api"]`,
but the opencode schema reads it from `provider.<id>.options.baseURL`. The wrong key silently
routes to canonical hosts ([[project_craft_beta_no_backcompat]]).

## Important Notes

**Per-tenant key scope, not per-user.** Plan 1's `InjectionContext` carries
`sandbox: ResolvedSandbox`, so the resolver keys off `ctx.sandbox.tenant_id` — one key per
`(tenant_id, provider)` is shared across the tenant's users.

**Keys stay in `llm_provider` rows.** Per Plan 1, LLM keys are not migrated into the `ExternalApp`
data model. The resolver reads `llm_provider` directly via `fetch_all_build_mode_llm_providers` /
`fetch_llm_provider_by_type_for_build_mode` (`onyx/server/features/build/db/build_session.py`),
both of which return `LLMProviderView` with the key already decrypted by
`LLMProviderView.from_model()`. This works in-proxy because Plan 1 wires `ENCRYPTION_KEY_SECRET`
into the proxy Deployment.

**Per-provider auth conventions** (overwrite only the named header):

| Provider | Canonical host | Header convention |
|---|---|---|
| OpenAI | `api.openai.com` | `Authorization: Bearer {key}` |
| Anthropic | `api.anthropic.com` | `x-api-key: {key}` — leave `anthropic-version` intact |
| Google Gemini | `generativelanguage.googleapis.com` | `x-goog-api-key: {key}`; strip any `?key=` query param |
| OpenRouter | `openrouter.ai` | `Authorization: Bearer {key}` |

**Custom `api_base`.** A tenant can configure a per-provider endpoint via `LLMProvider.api_base`.
The resolver must claim both the canonical host *and* each tenant's configured `api_base` host —
miss this and the request 401s against the custom gateway.

**Placeholder, not empty.** Opencode's AI SDK throws `LoadAPIKeyError` before sending if
`options.apiKey` is unset (opencode #21737), so the pod ships a non-empty placeholder for each
`options.apiKey`. The AI SDK turns that into the wire header per provider convention; the proxy
overwrites that header. Never set `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` env vars in the pod.

**Keep opencode pointed at the real provider hosts.** Don't repoint `baseURL` at the proxy;
traffic already routes and MITMs through the proxy, so host-matching stays simple.

**Streaming-safe.** Per Plan 1, injection runs at header time without reading body or response, so
SSE and long-running streams pass through untouched.

**Fail closed.** Per Plan 1, a missing or unreadable LLM key for a claimed host raises
`CredentialUnavailableError` and the dispatcher serves a Craft 403.

## Implementation Strategy

1. **Emit placeholders in the opencode config.** In `_build_provider_block` /
   `build_multi_provider_opencode_config` (`opencode_config.py`), write the Plan 1 placeholder for
   each `options.apiKey` behind the LLM-key resolver flag. Keep `model`, `enabled_providers`, and
   provider blocks intact. *Also* fix the custom-endpoint field: `block["api"]` →
   `block["options"]["baseURL"]`.

2. **`LLMProviderKeyResolver`** implementing Plan 1's `CredentialResolver` Protocol.
   - `claims(host, match)`: returns True iff `host` is one of the canonical LLM provider hosts or
     a configured tenant `api_base` host. Ignores `match`. A per-tenant `api_base` cache is
     populated lazily on first claim for a tenant and refreshed on provider-row updates.
   - `resolve(request, ctx)`: opens a session via `ctx.db_session_factory(ctx.sandbox.tenant_id)`,
     finds the matching provider row by host (canonical or `api_base`), pulls the decrypted key
     off its `LLMProviderView`, and renders the per-provider header. Strips `?key=` from the URL
     for Gemini. Raises `CredentialUnavailableError` if no provider/key is configured for the
     matched host+tenant.

3. **Register in `build_resolvers()`** (Plan 1, step 7) alongside `ExternalAppResolver` and
   `OnyxPatResolver`. Provider hosts are disjoint from the other resolvers; order is for clarity.

4. **Config flag** independent of the PAT resolver, gating both the proxy-side resolver and the
   pod-side placeholder swap.

## Tests

External-dependency unit tests (real Postgres for `llm_provider` rows; sandbox proxy under test;
upstream HTTP mocked) in `backend/tests/external_dependency_unit/sandbox_proxy/`:

- **One test per provider header convention.** OpenAI / OpenRouter → `Authorization: Bearer`;
  Anthropic → `x-api-key` with `anthropic-version` preserved; Gemini → `x-goog-api-key` with
  `?key=` stripped. Assert the header the resolver *produces*.
- **Custom `api_base`** — a tenant with `LLMProvider.api_base = https://llm.tenant.example/v1`:
  the resolver claims that host and injects the right key.
- **Fail closed** — a request to a canonical provider host from a tenant with no configured
  build-mode provider for that type → `CredentialUnavailableError` → 403.
- **Opencode config emits placeholder only**, never a real key, with the flag on. Pin against the
  spec (documented header conventions + placeholder constant), not against the resolver constant
  under test ([[feedback_tests_pin_spec_not_impl]]); a completeness check asserts the per-provider
  header table is exhaustive over the configured provider set.

## Out of scope

- LLM admin UI changes — keys keep being managed through the existing LLM-provider settings.
- Migrating `llm_provider` rows into the `ExternalApp` data model.
- Per-user (rather than per-tenant) LLM keys.
- Per-provider scoping/rotation; lifecycle is unchanged.
- Changes to the matcher, gating semantics, or anything [Plan 1](./01-framework.md) /
  [Plan 2](./02-onyx-pat.md) owns.
