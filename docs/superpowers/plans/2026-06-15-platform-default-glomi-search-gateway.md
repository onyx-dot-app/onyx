# Platform Default Glomi Search Gateway Implementation Plan

## Issues to Address

- Automatically seed a platform default `Glomi Search / glomi` web search provider when Glomi gateway config is enabled.
- Add a provider client that speaks the Glomi Search Gateway batch protocol instead of binding Onyx to Tavily directly.
- Extend `web_search` tool calls with `mode=lite|deep`, with ordinary chat defaulting to `lite` and Deep Research defaulting to `deep`.
- Keep Admin Web Search and frontend provider type handling from breaking when provider type is `glomi`.
- Update prompt guidance so the agent chooses search strength in the tool call without a backend keyword router.

## Important Notes

- Database operations stay under `backend/onyx/db`; the new seed helper belongs there and is called from both `setup_postgres()` and tenant provisioning.
- Existing providers use per-query `search(query)`. The Glomi gateway needs a batch path, so the provider abstraction should add a default `search_batch(...)` method that preserves old clients while allowing Glomi to override it.
- `open_url` should remain unchanged and continue to fall back to `OnyxWebCrawler` when there is no active content provider.
- The current branch is `glomi`, not `main/master`; existing untracked `coding_agent_tool.py` is unrelated and should be left alone.
- Admin API currently uses `HTTPException` in existing routes, but new backend logic should avoid adding new route-level error handling unless required.

## Implementation Strategy

1. Add shared search mode and batch provider support.
   - Add a `WebSearchMode` enum and `search_batch(...)` default to the web search models.
   - Add `default_mode` to `WebSearchToolOverrideKwargs`.
   - Preserve old search clients by keeping their existing `search(query)` method unchanged.

2. Add the Glomi gateway provider.
   - Add `WebSearchProviderType.GLOMI`.
   - Add `GlomiSearchClient` under the web search clients directory.
   - Build it from provider config keys `base_url`, optional `channel`, optional `timeout_seconds`, and existing `num_results`.
   - POST batch `queries`, `mode`, optional `channel`, `max_results`, and fixed `locale=zh-CN` to `/search`.
   - Map both `url` and `link` response fields to `WebSearchResult`.

3. Add default web search provider seeding.
   - Add `backend/onyx/db/glomi_search.py` with config/result dataclasses and `seed_glomi_default_web_search_provider`.
   - Add app config envs: `GLOMI_DEFAULT_WEB_SEARCH_ENABLED`, `GLOMI_DEFAULT_WEB_SEARCH_API_BASE`, `GLOMI_DEFAULT_WEB_SEARCH_API_KEY`, `GLOMI_DEFAULT_WEB_SEARCH_CHANNEL`.
   - Call the seed helper from `setup_postgres()` and `configure_default_api_keys()`.
   - Activate Glomi only when no provider is active or when the active provider is already Glomi.

4. Extend WebSearchTool mode handling.
   - Add `mode` to the tool schema and mark it required in schema guidance while keeping runtime backward compatible.
   - Validate `mode=lite|deep`; missing mode uses `override_kwargs.default_mode`.
   - Use batch provider execution for Glomi and old per-query parallel execution for existing providers.
   - Preserve partial failure behavior for old providers and all-fail `ToolCallException` behavior.

5. Make Deep Research default to deep.
   - Pass `default_mode=deep` when `run_tool_calls(...)` is executing inside the research agent.
   - Keep ordinary chat default at `lite`.

6. Update prompts and frontend/Admin type handling.
   - Update normal web search guidance and Deep Research tool guidance to explain `mode=lite|deep`.
   - Add `glomi` to frontend web search provider types, registry details, ordering, capabilities, and config field handling.

7. Update docs.
   - Update `summary.md` with implementation notes, pitfalls, and verification.
   - Update `docs/GlomiAI.md` if implementation status or behavior wording changes.

## Tests

- Backend unit tests:
  - Seed helper skips disabled/missing config and returns clear reasons.
  - Seed helper creates or updates `Glomi Search / glomi`.
  - Seed helper activates Glomi only when no provider is active or active provider is Glomi.
  - `GlomiSearchClient` sends batch queries, mode, optional channel, max results, and `zh-CN` locale.
  - `GlomiSearchClient` maps `url` and `link`, and maps gateway auth/rate-limit/non-JSON errors clearly.
  - `WebSearchTool` accepts explicit `mode`, defaults to `lite`, and uses override default `deep`.
  - Tool-call merge preserves `deep` when merged web search calls include it.
  - Prompt tests assert normal and Deep Research guidance mention `mode=lite|deep` and `mode=deep`.
  - Tenant provisioning test asserts the Glomi seed hook is invoked.

- Frontend verification:
  - Run `npm run types:check` from `web` after type updates.

- Focused commands:
  - `$env:PYTHONUTF8='1'; .venv\Scripts\python.exe -m pytest backend\tests\unit\onyx\db\test_glomi_search.py backend\tests\unit\onyx\tools\tool_implementations\websearch\test_glomi_search_client.py backend\tests\unit\onyx\tools\tool_implementations\websearch\test_web_search_tool_run.py backend\tests\unit\onyx\tools\test_tool_runner.py backend\tests\unit\onyx\prompts\test_tool_prompts.py backend\tests\unit\onyx\prompts\deep_research\test_research_agent_prompts.py backend\tests\unit\ee\onyx\server\tenants\test_provisioning.py`
  - `cd web; npm run types:check`
