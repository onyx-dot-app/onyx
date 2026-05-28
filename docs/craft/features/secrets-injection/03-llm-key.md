# Plan 3 — LLM Provider-Key Resolver

Reference: [Plan 1](./01-framework.md) for the shared dispatcher and `InjectionContext` this plugs
into. Independent of [Plan 2](./02-onyx-pat.md).

## Issues to Address

LLM provider keys are baked into the sandbox today. `_build_provider_block` in
`onyx/server/features/build/sandbox/util/opencode_config.py` writes
`provider.<provider_name>.options.apiKey = <real key>` for each enabled provider, and the resulting
JSON is mounted as `OPENCODE_CONFIG_CONTENT` on the pod. This plan removes the key from the pod and
injects it from the proxy via an `LLMProviderKeyResolver` that claims the canonical provider hosts
plus each tenant's `LLMProvider.api_base`.

While here, fix an existing bug: a tenant's custom endpoint is currently written as `block["api"]`,
but the opencode schema reads it from `provider.<provider_name>.options.baseURL` — so the custom
endpoint silently doesn't take effect and traffic goes to the canonical host
([[project_craft_beta_no_backcompat]]).

## Important Notes

**Per-tenant key scope, not per-user.** Tenancy is per-PostgreSQL-schema, not a column on
`llm_provider`. Plan 1's `InjectionContext` carries `sandbox: ResolvedSandbox`, so the resolver
opens a session via `ctx.db_session_factory(ctx.sandbox.tenant_id)` and reads the tenant's rows.

**Row resolution rule.** `llm_provider` has no uniqueness constraint, so a tenant can have multiple
rows of the same `provider` type (e.g. both `build-mode-anthropic` and `anthropic`). The resolver
reuses `fetch_llm_provider_by_type_for_build_mode` (`onyx/server/features/build/db/build_session.py`),
which prefers the `build-mode-{type}` named row and falls back to any row of that `provider` type.
For custom-host matching, it iterates `fetch_all_build_mode_llm_providers` and matches the request's
host against each row's `api_base`. Both helpers return `LLMProviderView` with the `api_key` already
decrypted by `LLMProviderView.from_model()`. This works in-proxy because Plan 1 wires
`ENCRYPTION_KEY_SECRET` into the proxy Deployment.

**Keys stay in `llm_provider`.** Per Plan 1, LLM keys are not migrated into the `ExternalApp` data
model — no sync surface with the LLM-admin UI.

**Per-provider auth conventions** (overwrite only the named header):

| Provider | Canonical host | Header convention |
|---|---|---|
| OpenAI | `api.openai.com` | `Authorization: Bearer {key}` |
| Anthropic | `api.anthropic.com` | `x-api-key: {key}` — leave `anthropic-version` intact |
| Google Gemini | `generativelanguage.googleapis.com` | `x-goog-api-key: {key}` (defensively strip any `?key=` query param the client may have set) |
| OpenRouter | `openrouter.ai` | `Authorization: Bearer {key}` |

**Custom `api_base`.** A tenant can configure a per-provider endpoint via `LLMProvider.api_base`.
The resolver must claim both the canonical host *and* each tenant's configured `api_base` host —
miss this and the request 401s against the custom gateway.

**Placeholder, not empty.** Opencode's AI SDK refuses to send when `options.apiKey` is unset, so
the pod ships a non-empty placeholder for each provider's `options.apiKey`. The AI SDK turns that
into the wire header per provider convention; the proxy overwrites that header. Never set
`OPENAI_API_KEY` / `ANTHROPIC_API_KEY` env vars in the pod.

**Keep opencode pointed at the real provider hosts.** Don't repoint `baseURL` at the proxy;
traffic already routes and MITMs through the proxy, so host-matching stays simple.

**Streaming-safe.** Per Plan 1, injection runs at header time without reading body or response, so
SSE and long-running streams pass through untouched.

**Fail closed.** Per Plan 1, a missing or unreadable LLM key for a claimed host raises
`CredentialUnavailableError` and the dispatcher serves a Craft 403.

## Implementation Strategy

1. **Emit placeholders in the opencode config** for the K8s manager only (the docker manager keeps
   the real keys — docker self-hosted doesn't route through the proxy; see Plan 1's
   "Kubernetes-only" note). In `_build_provider_block` / `build_multi_provider_opencode_config`
   (`opencode_config.py`), write the Plan 1 placeholder for each `options.apiKey` behind the LLM-key
   resolver flag. Keep `model`, `enabled_providers`, and provider blocks intact. *Also* fix the
   custom-endpoint field: `block["api"]` → `block["options"]["baseURL"]`.

2. **`LLMProviderKeyResolver`** implementing Plan 1's `CredentialResolver` Protocol.
   - `claims(host, match)`: True iff `host` is one of the canonical LLM provider hosts or a
     configured tenant `api_base` host. Ignores `match`. A per-tenant `api_base` cache is populated
     lazily on first claim for a tenant and refreshed on provider-row updates.
   - `resolve(request, ctx)`: opens a session via `ctx.db_session_factory(ctx.sandbox.tenant_id)`,
     finds the matching provider row (canonical host → `fetch_llm_provider_by_type_for_build_mode`;
     custom host → scan `fetch_all_build_mode_llm_providers` by `api_base`), pulls the decrypted
     key off `LLMProviderView.api_key`, and renders the per-provider header. Strips any `?key=`
     query param on Gemini requests. Raises `CredentialUnavailableError` if no row / no key.

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
