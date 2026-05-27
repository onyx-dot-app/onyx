# Plan 3 — LLM Provider-Key Resolver

Reference: [Plan 1](./01-framework.md) for project context and the shared seam this plugs into.
Independent of plan 2.

## Issues to Address

The LLM provider key is currently written into the opencode config: `_build_provider_block` sets
`provider.<id>.options.apiKey = <real key>` (`opencode_config.py`), and the JSON is mounted as
`OPENCODE_CONFIG_CONTENT` (`kubernetes_sandbox_manager.py`). This plan moves the key out of the pod
so it lives only in the proxy: an `LLMProviderKeyResolver` behind the [Plan 1](./01-framework.md)
seam injects the per-tenant provider key on outbound LLM requests. It's the cleanest of the three:
LLM traffic already traverses and MITMs through the proxy.

## Important Notes

**Placeholder.** Per Plan 1's placeholder/overwrite contract, set each provider's `options.apiKey`
to the placeholder — required because opencode's AI SDK throws `LoadAPIKeyError` before sending if
the key is unset (opencode #21737). Never set `OPENAI_API_KEY`/`ANTHROPIC_API_KEY` in the pod.

**Per-provider auth_templates** (matched by host; overwrite only the named header — Plan 1):

| Provider | Host | auth_template |
|---|---|---|
| OpenAI | `api.openai.com` | `{"Authorization": "Bearer {key}"}` |
| Anthropic | `api.anthropic.com` | `{"x-api-key": "{key}"}` — leave `anthropic-version` intact |
| Google Gemini | `generativelanguage.googleapis.com` | `{"x-goog-api-key": "{key}"}`; strip any `?key=` param |
| OpenRouter | `openrouter.ai` | `{"Authorization": "Bearer {key}"}` |

**Key source.** Build-mode `llm_provider` rows: `fetch_all_build_mode_llm_providers` /
`fetch_llm_provider_by_type_for_build_mode` (`build_session.py`) return `LLMProviderView` with the
key decrypted via `LLMProviderView.from_model()` (works because the proxy has `ENCRYPTION_KEY_SECRET`
— Plan 1). The resolver: `tenant_id` from `ResolvedSandbox` → `get_session_with_tenant` → fetch by
provider/host.

**Custom `api_base`.** A tenant may set a custom endpoint via `LLMProvider.api_base`
(`opencode_config.py`), so the host differs from canonical. The resolver loads the tenant's
build-mode providers (including `api_base`) and matches both canonical and custom hosts — miss this
and the request 401s.

**Keep opencode pointed at the real provider hosts** — don't repoint `baseURL` at the proxy; traffic
already routes and MITMs through the proxy, so host-matching stays simple.

**Multi-provider sessions** (`enabled_providers`) work for free: matching keys on each request's
host. **Streaming** is stream-safe via Plan 1 (injection runs at `requestheaders`, never reads body
or response).

## Implementation Strategy

1. **Emit placeholders instead of real keys.** In `_build_provider_block` /
   `build_multi_provider_opencode_config` (`opencode_config.py`), write the Plan 1 placeholder for
   each `options.apiKey`, behind the LLM-key resolver flag. Keep `model`, `enabled_providers`, base
   URLs, and `api_base`; ensure the pod never sets the provider env keys. *While here:* the custom
   endpoint is written as `block["api"]`, but the current opencode schema uses
   `provider.<id>.options.baseURL` — fix it ([[project_craft_beta_no_backcompat]]).

2. **Implement `LLMProviderKeyResolver`** for the LLM provider hosts (canonical + tenant `api_base`):
   resolve `tenant_id`, fetch + decrypt the matching build-mode provider's key, render the host's
   auth_template (leaving `anthropic-version` intact); fail closed if no provider/key for that
   host+tenant.

3. **Config**: an enable flag, independent of the PAT resolver.

## Tests

External-dependency unit tests (real DB + provider config, sandbox mocked) extending `sandbox_proxy/`:

- OpenAI-bound request with the placeholder → `Authorization` overwritten with the decrypted tenant key.
- Anthropic-bound request → `x-api-key` set, `anthropic-version` left intact.
- Custom `api_base` provider → resolver host-matches the custom host and injects.
- Fail-closed: a provider-host request from a tenant with no configured provider is blocked.
- `opencode_config` output carries only the placeholder, never a real key, with the flag on. Pin
  against the spec, not the constant ([[feedback_tests_pin_spec_not_impl]]).

One test per header convention is enough; assert the header the resolver *produces*.
