# Local Glomi Search Gateway Design

## Issues to Address

The Onyx side now knows how to call a `glomi` web search provider through `POST <base_url>/search`, but this repository does not yet include a runnable Gateway service. Local development with only a Tavily API key therefore cannot enable the new `web_search` path.

## Design

Add a small standalone FastAPI app under `backend/onyx/search_gateway`. It is a local implementation of the Glomi Search Gateway protocol, not an Onyx chat API route. Onyx continues to call it as an external provider through `GLOMI_DEFAULT_WEB_SEARCH_API_BASE`.

The service exposes:

- `GET /health` for startup checks.
- `POST /search` for the existing Gateway contract.

The Gateway authenticates Onyx requests with `Authorization: Bearer <GLOMI_SEARCH_GATEWAY_API_KEY>`. It supports `channel=tavily` in this first version and rejects unregistered channels with the standard Onyx error shape. Tavily credentials stay inside the Gateway process via `TAVILY_API_KEY`.

The Gateway is intentionally split into common strategy code and provider adapters:

```text
SearchGatewayService
  -> SearchPlanner        # lite / medium / deep query fan-out
  -> Adapter Registry     # channel -> adapter
  -> Capability Policy    # advanced/raw/extract degradation
  -> Result Merge/Rank    # URL dedupe and truncation
  -> SearchAdapter        # Tavily today, Brave/domestic providers later
```

Onyx still sends the same stable Gateway contract. Adding Brave, Serper, Baidu, Sogou, 360, or a private search source should add a new adapter and capability declaration, not change Onyx or the chat tool contract.

## Data Flow

1. Onyx `GlomiSearchClient` sends `queries`, `mode`, `channel`, `max_results`, and `locale` to the local Gateway.
2. Gateway validates bearer auth and request shape.
3. Gateway picks the requested channel or default channel from the adapter registry.
4. `mode=lite` maps to Tavily `search_depth=basic` and keeps the caller's original queries only.
5. `mode=medium` maps to `search_depth=advanced`, expands each query into a smaller bounded source-angle portfolio, and requests Tavily `raw_content`.
6. `mode=deep` maps to `search_depth=advanced`, expands each query into the broadest bounded source-angle portfolio, and requests Tavily `raw_content`.
7. Gateway normalizes Tavily `results` into `{title, url, snippet, author, published_date}` and dedupes URLs across query results. Medium and deep snippets prefer capped `raw_content` when available so search can still provide useful evidence when later page fetching hits 403 or crawler failures.
8. Gateway returns the unified `results` list to Onyx.
9. If `open_url` later cannot fetch one of those result URLs through indexed retrieval, the crawler, or link-based lookup, Onyx can turn the prior `web_search` snippet into a clearly labeled snippet fallback result. This is intentionally not treated as full page content.

If a future adapter does not support advanced search or raw content, `SearchGatewayService` degrades the normalized adapter options before calling it. For example, a Brave-like adapter can still participate in medium/deep searches as basic search plus snippet-only results, while Tavily or another extract provider can supply richer content.

## Search Mode Semantics

Medium and deep modes are research-oriented retrieval passes, not the full Deep Research orchestrator. They borrow useful search-side ideas from systems like Genspark while keeping this local Gateway simple:

- **Query fan-out**: the Gateway deterministically expands medium/deep queries into source angles. Technical/project queries add official documentation, GitHub architecture, changelog/release notes, comparison/benchmark, and for deep also issues/discussions plus limitation angles. Market queries add latest news, live chart/technical analysis, forecast commentary, and for deep also macro drivers plus risk/support-resistance angles. Generic queries add official source, latest analysis, examples, alternatives, and criticism angles.
- **Bounded cost**: medium expansion is capped at five effective queries. Deep expansion is capped at eight effective queries. Both modes split per-query `max_results` so one broad query cannot consume all result slots before source-specific queries run.
- **Content fallback**: medium and deep set Tavily `include_raw_content=true`. Medium caps normalized snippets to 800 characters, deep caps them to 1200 characters. This does not replace `open_url`, but it gives the LLM stronger fallback evidence if a selected page later blocks crawling. `OpenURLTool` can now return that evidence only after real page retrieval has failed, and labels it as a recent `web_search` snippet fallback.
- **Protocol stability**: Onyx still sends only the existing Gateway fields. The query portfolio and Tavily-specific options remain internal Gateway behavior.

## Configuration

Onyx `.vscode/.env`:

```env
GLOMI_DEFAULT_WEB_SEARCH_ENABLED=true
GLOMI_DEFAULT_WEB_SEARCH_API_BASE=http://localhost:7777
GLOMI_DEFAULT_WEB_SEARCH_API_KEY=dev-gateway-key
GLOMI_DEFAULT_WEB_SEARCH_CHANNEL=tavily
```

Gateway `.vscode/.env`:

```env
GLOMI_SEARCH_GATEWAY_API_KEY=dev-gateway-key
TAVILY_API_KEY=...
GLOMI_SEARCH_GATEWAY_TAVILY_API_URL=https://api.tavily.com/search
GLOMI_SEARCH_GATEWAY_TIMEOUT_SECONDS=15
GLOMI_RUN_REAL_SEARCH_BENCHMARK=true
```

## Local Startup

Run the Gateway from the repository root after filling `TAVILY_API_KEY`:

```powershell
python -m dotenv -f .vscode/.env run -- uvicorn onyx.search_gateway.server:app --host 0.0.0.0 --port 7777 --reload
```

Then restart the Onyx API server so the default `Glomi Search / glomi` provider seed reads the `GLOMI_DEFAULT_WEB_SEARCH_*` values.

## Error Handling

The Gateway registers the shared `OnyxError` handler so failures use the standard `{"error_code": "...", "detail": "..."}` shape. Upstream Tavily failures are surfaced as `BAD_GATEWAY`, `RATE_LIMITED`, or `GATEWAY_TIMEOUT` as appropriate. Secrets and upstream URLs are not returned in error details.

## Tests

Use unit tests with `httpx.MockTransport` and FastAPI `TestClient`.

- Tavily adapter maps `lite`, `medium`, and `deep` modes to the correct `search_depth`.
- Tavily adapter keeps lite queries unchanged and expands medium/deep queries into bounded query portfolios.
- Tavily adapter requests `raw_content` only for medium/deep searches and caps raw snippets by mode.
- Tavily adapter normalizes and dedupes results.
- Common `SearchGatewayService` routes by default/requested channel.
- Common `SearchGatewayService` degrades advanced/raw-content options based on adapter capabilities.
- Common `SearchGatewayService` dedupes URLs across adapter calls.
- Unknown channels return standard `INVALID_INPUT`.
- `/search` requires Gateway bearer auth.
- `/search` rejects unsupported channels.
- `/search` delegates valid requests to the search service.
- `OpenURLTool` converts failed URLs with prior web_search snippets into explicitly labeled fallback sections.
- `OpenURLTool` does not create snippet fallback sections when real indexed/crawled content is already available.
- Real Gateway/Tavily benchmark is opt-in with `GLOMI_RUN_REAL_SEARCH_BENCHMARK=true` and `TAVILY_API_KEY`; it verifies medium/deep results have URLs, usable snippets, and can feed the open_url fallback path.
