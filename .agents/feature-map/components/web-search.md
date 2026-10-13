# Web Search

> Searching the public internet and fetching arbitrary web pages, as opposed to
> searching the company's connected knowledge sources. Covers the `web_search`
> and `open_url` tools, their admin configuration, and the standalone `/web-search`
> API used outside the chat loop.

**Verified against:** `268e4d5a3d` (2026-10-05)
**Domain:** core-loop
**Edition:** CE
**Owns:**
`backend/onyx/tools/tool_implementations/web_search/` (`web_search_tool.py`, `models.py`,
`providers.py`, `utils.py`, `clients/`), `backend/onyx/tools/tool_implementations/open_url/`
(`open_url_tool.py` and its helpers), `backend/onyx/db/web_search.py`,
`backend/onyx/server/manage/web_search/` (admin CRUD), `backend/onyx/server/features/web_search/`
(the standalone runtime API), `web/src/views/admin/WebSearchPage/`

**Read first:** `[[tools-framework]]`. It supplies the `Tool` interface, per-turn
construction, and the citation-numbering scheme this document assumes.

---

## 1. What the user experiences

Inside a chat turn, the assistant can search the open internet and read specific
pages, not just the company's indexed documents. The user sees a search block with
the queries it ran, a list of result documents, and numbered citations that work the
same way as citations from an internal document search.

None of this exists until an admin configures a web search provider at
`/admin/web-search`. Until then, the web search tool is not offered to the model at
all, it does not appear as an option and does not fail loudly, it is simply absent.

Reading a specific link (`open_url`) is a second, related capability. It works even
without a web search provider configured, because it can serve a link's content from
the connected knowledge sources when the URL happens to match an already-indexed
document. If web search is turned off for one message, `open_url` keeps working in
that indexed-only mode: pasted links still resolve if they are indexed, but nothing
new is fetched from the live internet.

---

## 2. Surfaces

### Admin route

| Route | What it configures |
|---|---|
| `/admin/web-search` (`web/src/app/admin/web-search/page.tsx` → `web/src/views/admin/WebSearchPage/index.tsx`) | Add, edit, activate, deactivate, test, and delete web search providers and web content providers. |

### Admin API (`backend/onyx/server/manage/web_search/api.py`, router prefix `/admin/web-search`)

| Method | Path | Handler | Notes |
|---|---|---|---|
| GET | `/admin/web-search/search-providers` | `list_search_providers` | Lists configured search providers, API key returned masked. |
| POST | `/admin/web-search/search-providers` | `upsert_search_provider_endpoint` | Create or update a search provider row. |
| POST | `/admin/web-search/search-providers/test` | `test_search_provider` | Runs a live probe call against the provider before saving. |
| POST | `/admin/web-search/search-providers/{id}/activate`, `/deactivate` | `activate_search_provider`, `deactivate_search_provider` | Activation makes the provider the single active row. |
| POST | `/admin/web-search/content-providers/{id}/activate`, `/deactivate` | `activate_content_provider`, `deactivate_content_provider` | |
| POST | `/admin/web-search/content-providers/reset-default` | `reset_content_provider_default` | Returns to the built-in crawler. |
| POST | `/admin/web-search/content-providers/test` | `test_content_provider` | Same idea for content (page-fetch) providers. On `MULTI_TENANT`, this refuses to reuse a stored API key with a different `base_url` than the one already saved for that provider type (`api.py:411-419`). |
| POST/GET/DELETE | analogous endpoints for `content-providers` | `upsert_content_provider_endpoint`, etc. | |

All admin endpoints gate on `Permission.FULL_ADMIN_PANEL_ACCESS`
(`onyx/server/manage/web_search/api.py`).

Search and content providers whose API key is shared between the two sides
(currently Exa and Tavily) are cross-seeded on upsert: entering a key on one side
seeds the other's stored key, via `_SEARCH_TO_CONTENT_SYNC` /
`_CONTENT_TO_SEARCH_SYNC` (`api.py`).

### Runtime API (`backend/onyx/server/features/web_search/api.py`, router prefix `/web-search`)

This is a **separate surface from the chat tool**, used by callers that want web
search or page-fetch outside the LLM tool loop (for example the public API or MCP).
It gates on `Permission.READ_SEARCH`, not the chat endpoint's permission set.

| Method | Path | Handler | Notes |
|---|---|---|---|
| POST | `/web-search/search` | `execute_web_search` | Search, then immediately fetch full content for every unique result URL. |
| POST | `/web-search/search-lite` | `execute_web_search_lite` | Search only, snippets and URLs, no page fetch. |
| POST | `/web-search/open-urls` | `execute_open_urls` | Fetch content for a specific list of URLs via the active content provider. The request accepts at most `OPEN_URLS_MAX_URLS_PER_REQUEST` URLs (default 20). The MCP `open_urls` tool applies the same cap. |

These endpoints build a provider directly from the active DB row
(`_get_active_search_provider`, `_get_active_content_provider` in
`server/features/web_search/api.py`) rather than going through the `Tool` interface,
so `is_available` gating does not apply here: an unconfigured search provider raises
`OnyxError(OnyxErrorCode.INVALID_INPUT, ...)` instead of the tool being silently
absent (`api.py:_get_active_search_provider`). An unconfigured content provider falls
back to the built-in `OnyxWebCrawler` (`api.py:_get_active_content_provider`).

### Environment configuration (`backend/onyx/configs/app_configs.py`)

| Variable | Default | Effect |
|---|---|---|
| `OPEN_URL_MAX_HTML_SIZE_BYTES` | 20 MiB | Size cap for an HTML body the built-in crawler reads. |
| `OPEN_URL_MAX_PDF_SIZE_BYTES` | 50 MiB | Size cap for a PDF body. |
| `OPEN_URL_BODY_DEADLINE_SECONDS` | 120 | Wall-clock limit to read one response body. |
| `OPEN_URLS_MAX_URLS_PER_REQUEST` | 20 | URL cap for `/web-search/open-urls` and the MCP tool. |

### Data model surface

See §3.

---

## 3. Data model

Two tables, mirrored in shape (`backend/onyx/db/models.py`):

- **`InternetSearchProvider`** (`internet_search_provider`): `name` (unique),
  `provider_type`, `api_key` (`EncryptedString`, decrypted on read via
  `SensitiveValue.get_value(apply_mask=...)`), `config` (JSONB, provider-specific
  options such as `num_results`, `searxng_base_url`, `country`), `is_active`.
- **`InternetContentProvider`** (`internet_content_provider`): same shape, for the
  page-fetch side (Firecrawl base URL, timeouts).

Only one row per table can have `is_active = True`. Activating a provider
deactivates every other row of that table in the same transaction
(`db/web_search.py:set_active_web_search_provider`,
`set_active_web_content_provider`), so the two tables each behave as a single
current-provider slot, not a priority list.

The API key never leaves the database in plaintext except at the moment a client
constructs the provider object server-side (`providers.py:_build_search_provider`,
`build_content_provider_from_config`). List endpoints only ever return
`api_key.get_value(apply_mask=True)` (`db/web_search.py` model views in
`server/manage/web_search/api.py`). The key is read once per tool construction and
held only in the in-process provider client; it is never included in the
`llm_facing_response` or any streamed packet.

---

## 4. How it works

### 4.1 Provider abstraction

`WebSearchProvider` (`web_search/models.py`) is the interface every search client
implements: `search(query) -> Sequence[WebSearchResult]`,
`supports_site_filter`, `test_connection`. `WebContentProvider`
(`open_url/models.py`, not reproduced here) is the parallel interface for page
fetching: `contents(urls) -> list[WebContent]`.

Supported search provider types (`shared_configs/enums.py:WebSearchProviderType`),
each with a client under `web_search/clients/`:

| Type | Client | Needs an API key |
|---|---|---|
| `google_pse` | `google_pse_client.py:GooglePSEClient` | Yes, plus a search-engine id (`cx`) |
| `serper` | `serper_client.py:SerperClient` | Yes |
| `exa` | `exa_client.py:ExaClient` | Yes |
| `searxng` | `searxng_client.py:SearXNGClient` | No, needs `searxng_base_url` instead |
| `brave` | `brave_client.py:BraveClient` | Yes |
| `tavily` | `tavily_client.py:TavilyClient` | Yes |

`provider_requires_api_key` (`providers.py`) hardcodes the rule: every provider
except SearXNG requires a key. `build_search_provider_from_config` (`providers.py`)
is the single factory that turns a `provider_type` + `api_key` + `config` dict into
a concrete client, validating provider-specific required config (e.g. Google PSE's
`cx`, SearXNG's `searxng_base_url`) and raising `ValueError` if missing.

Content provider types (`shared_configs/enums.py:WebContentProviderType`):
`onyx_web_crawler` (the built-in crawler, no key needed), `firecrawl` (needs a key
and a `base_url`), `exa`, `tavily`. `build_content_provider_from_config`
(`providers.py`) is the matching factory.

### 4.2 Selecting a provider

There is exactly one active row per table (`is_active`), not a ranked list.
`fetch_active_web_search_provider` / `fetch_active_web_content_provider`
(`db/web_search.py`) fetch it. Configuring a second provider does not create
fallback behaviour, it simply sits inactive until the admin activates it.

### 4.3 Search flow (`WebSearchTool.run`, `web_search_tool.py`)

1. Sanitize and normalize the LLM's `queries` (`_sanitize_query`,
   `_normalize_queries_input`), stripping control characters.
2. Run every query against the active provider in parallel
   (`run_functions_tuples_in_parallel`, `_safe_execute_single_search`), capturing
   per-query errors instead of failing the whole call on one bad query.
3. Filter out results with neither title nor snippet
   (`utils.py:filter_web_search_results_with_no_title_or_snippet`), cap each query's
   results at `DEFAULT_MAX_RESULTS` (20, `web_search/models.py`).
4. Interweave results from each query round-robin, de-duplicating by
   `(title, link)`, up to `DEFAULT_MAX_RESULTS` total (`web_search_tool.py:run`).
5. Convert each `WebSearchResult` into an `InferenceSection` via
   `inference_section_from_internet_search_result` (`web_search/utils.py`), the same
   type internal search produces. See [[internal-search]] and [[citations]].
6. Emit `SearchToolQueriesDelta` then `SearchToolDocumentsDelta` packets
   (`Placement`-stamped, see [[streaming-protocol]]).
7. Format the sections into the LLM-facing string and citation map via
   `convert_inference_sections_to_llm_string`, using
   `override_kwargs.starting_citation_num` as the citation floor for this call.

### 4.4 Fetch flow (`OpenURLTool.run`, `open_url_tool.py`)

`open_url` tries up to three sources per URL, not strictly sequential, most run in
parallel and merged:

1. **Indexed documents.** `_resolve_urls_to_document_ids` matches the URL against
   already-indexed document IDs (connector-defined candidate variants), then
   `_retrieve_indexed_documents_with_filters` pulls them through the document index
   with the acting user's ACL filters (`_build_index_filters`). Always tried first,
   including when web fetch is disabled.
2. **Live crawl**, via whichever content provider is active: `OnyxWebCrawler`
   (built-in, default) or a configured client (Firecrawl, Exa, Tavily). Skipped
   entirely when `web_fetch_disabled=True` (see §4.5) or when `DISABLE_VECTOR_DB`
   forces crawl-only mode in the opposite direction. Runs in parallel with step 1
   via `run_functions_tuples_in_parallel` when both are eligible.
3. **Link-based fallback** (`_fallback_link_lookup`): for URLs that neither
   resolved to a document ID nor were successfully crawled, retries indexed lookup
   by raw link match, with no timeout. Last resort before reporting the URL as
   unavailable.

`_merge_indexed_and_crawled_results` prefers the indexed section over the crawled
one whenever both exist and the indexed one has content, on the theory that the
indexed copy is cleaner (`open_url_tool.py:_merge_indexed_and_crawled_results`
comment). Crawled content becomes an `InferenceSection` via
`inference_section_from_internet_page_scrape` (`web_search/utils.py`), which
truncates the page around the search snippet if one is available
(`_truncate_content_around_snippet`), else truncates to `MAX_CHARS_PER_URL`
(15000 chars).

### 4.5 The WebSearch/OpenURL coupling

`OpenURLTool` is always constructed (it is not gated behind a configured provider,
`is_available` always returns `True`, `open_url_tool.py:is_available`), but its
live-fetch behavior depends on whether `WebSearchTool` is in play for that message.
`should_disable_open_url_web_fetch` (`tool_constructor.py`, owned by
[[tools-framework]]) returns `True` when `WebSearchTool` is explicitly excluded via
`allowed_tool_ids`. The constructor then passes `web_fetch_disabled=True` to
`OpenURLTool.__init__`, which:

- skips building a content provider at all (`self._provider = None`),
- in `run`, never calls the crawl path, seeds every URL that doesn't resolve to an
  indexed document as a `FailedFetch(reason=WEB_FETCH_DISABLED_REASON)`, and still
  lets the link-based fallback try to rescue them from the index.

So `web_search` finds new URLs on the open internet, `open_url` fetches whatever URL
it is given (from a search result or pasted directly by the user), and `open_url`
can also serve an already-indexed document by URL independent of both. Disabling
`web_search` for one message removes the "find new URLs" capability and forces
`open_url` into indexed-only mode; it does not remove `open_url` from the tool set.

### 4.6 Reaching the LLM and citations

Both tools convert their results into `InferenceSection`, the exact type
[[internal-search]]'s `SearchTool` produces, through
`inference_section_from_internet_search_result` and
`inference_section_from_internet_page_scrape` (`web_search/utils.py`). This is why
web citations render identically to internal-search citations, downstream citation
code (see [[citations]]) has no special case for web results.

Citation numbering does not collide with a parallel internal search or another
web-search call in the same turn: `tool_runner.py` assigns each search-like tool
call (`SearchTool`, `WebSearchTool`, `OpenURLTool`) a `starting_citation_num`, then
advances a shared counter by 100 before constructing the next tool's override
kwargs (`tool_runner.py:run_tool_calls`, `starting_citation_num += 100` at each of the
three branches). See [[internal-search]] for the internal side
of the same mechanism.

---

## 5. Contracts and invariants

1. **No active search provider means the tool is absent, not a call-time
   failure**, inside the chat loop. `WebSearchTool.is_available` (called by
   `tool_constructor.py`, [[tools-framework]]) checks
   `fetch_active_web_search_provider(...) is not None` before the tool is ever
   constructed (`web_search_tool.py:is_available`). If it were constructed
   anyway, `__init__` raises `RuntimeError`, that path is a defensive backstop, not
   the intended gate. This contract only holds for the chat tool; the standalone
   `/web-search/*` runtime API (§2) raises an `OnyxError` instead, by design, since
   it has no "absent" concept for a direct HTTP caller.
2. **Both tools must emit `InferenceSection`s, not a bespoke shape**, so citation
   resolution and rendering stay uniform with [[internal-search]]. A change that
   returns a different shape breaks citations silently rather than loudly.
3. **Citation ranges must not collide.** Any new search-like tool added to
   `tool_runner.py`'s branch list must also reserve a `starting_citation_num` block
   and advance the shared counter, or a parallel call can produce duplicate
   citation numbers across tools.
4. **A fetched page must not bypass the SSRF guard.** `OnyxWebCrawler._fetch_url`
   routes every request through `ssrf_safe_get` (`onyx/utils/url.py`). Any new
   content-fetch path added directly to `open_url_tool.py` (bypassing a
   `WebContentProvider`) must go through the same guard, not raw `requests`.
5. **The API key never crosses into the LLM prompt or a streamed packet.** It is
   read once to build the provider client (`providers.py:_build_search_provider`,
   `build_content_provider_from_config`) and never appears in
   `llm_facing_response`, `SearchDocsResponse`, or any admin list response (which
   returns `get_value(apply_mask=True)` only).
6. **`is_active` is exclusive per table.** Activating a provider deactivates every
   other row of the same type in the same transaction
   (`db/web_search.py:set_active_web_search_provider`/`set_active_web_content_provider`).
   Code that reads "the" active provider assumes at most one row satisfies
   `is_active = True`.

---

## 6. Relationships

**Depends on**
- [[tools-framework]]: supplies the `Tool` interface, `construct_tools`, and
  `should_disable_open_url_web_fetch` coupling logic.
- [[internal-search]]: defines `InferenceSection` and the citation conversion
  utilities (`convert_inference_sections_to_llm_string`,
  `convert_inference_sections_to_search_docs`) this component reuses rather than
  duplicates.
- [[citations]]: the citation resolution and rendering path both tools feed into
  identically.
- [[streaming-protocol]]: `SearchToolStart`, `SearchToolQueriesDelta`,
  `SearchToolDocumentsDelta`, `OpenUrlStart`, `OpenUrlUrls`, `OpenUrlDocuments`
  packets.
- [[access-control]] (via `open_url_tool.py:_build_index_filters`): the acting
  user's ACLs gate the indexed-document path of `open_url`, exactly like an
  internal search.
- [[multi-tenancy]]: `MULTI_TENANT` gates the base-URL-lock check in
  `test_content_provider` (§2), and stamps `tenant_id` into `open_url`'s index
  filters (`open_url_tool.py:_build_index_filters`).

**Depended on by**
- [[core-chat-loop]]: `construct_tools` includes `WebSearchTool` and `OpenURLTool`
  in the per-turn tool set the loop executes.
- [[agents-personas]]: a persona's `allowed_tool_ids` decides whether `WebSearchTool`
  is offered for a given persona/message, which in turn drives the coupling in §4.5.
- MCP and the public API, through `/web-search/search`, `/search-lite`,
  `/open-urls` (`server/features/web_search/api.py`), which run the same providers
  outside the chat loop.

---

## 7. Blast radius

| If your change… | Also check |
|---|---|
| adds a new search or content provider | `WebSearchProviderType`/`WebContentProviderType` (`shared_configs/enums.py`), the factory branch in `providers.py`, `provider_requires_api_key`, the admin upsert/test endpoints, and `web/src/views/admin/WebSearchPage/` for the config form |
| changes the result shape (`WebSearchResult`, `WebContent`, or the `InferenceSection` conversion in `web_search/utils.py`) | [[internal-search]] and [[citations]], since both assume the same `InferenceSection` contract; check citation rendering end to end |
| changes the `open_url` fallback order (indexed / crawl / link-based) | `_merge_indexed_and_crawled_results`, `_fallback_link_lookup`, and the `DISABLE_VECTOR_DB` crawl-only branch, which has its own simplified order |
| changes citation numbering (`starting_citation_num` increments) | `tool_runner.py`'s other two branches (`SearchTool`, and whichever new tool is added) and [[internal-search]] |
| touches the WebSearch/OpenURL coupling (`should_disable_open_url_web_fetch`) | `backend/tests/unit/onyx/tools/test_open_url_web_search_coupling.py`, and [[tools-framework]]'s tool-picker filtering |
| touches SSRF handling (`onyx/utils/url.py:ssrf_safe_get` or `OnyxWebCrawler._fetch_url`) | every caller of `ssrf_safe_get`, and whether a new content provider still routes through it or (like Firecrawl/Exa/Tavily) offloads fetching to a third-party service instead |
| changes provider activation (`set_active_web_search_provider`/`set_active_web_content_provider`) | the exclusivity invariant in §5.6, and `/web-search/*` runtime endpoints that assume a single active row |

---

## 8. How to verify a change

### Tests

```bash
# Unit: tool logic, provider factory, WebSearch/OpenURL coupling
cd backend && uv run pytest tests/unit/onyx/tools/tool_implementations/websearch -v
cd backend && uv run pytest tests/unit/onyx/tools/tool_implementations/open_url -v
cd backend && uv run pytest tests/unit/onyx/tools/test_open_url_web_search_coupling.py -v

# External dependency unit: real network calls to a provider
cd backend && uv run pytest tests/external_dependency_unit/tools/open_url/test_open_url_resolution.py -v

# Integration: the standalone /web-search/* API
cd backend && uv run pytest tests/integration/tests/web_search/test_web_search_api.py -v
```

See `backend/AGENTS.md` for the authoritative commands and required env
(`@pytest.mark.secrets(...)` resolves provider API keys the same way as any other
external test).

### Manual reproduction

1. Confirm services are up: `tail -f backend/log/api_server_debug.log`.
2. Sign in as `admin_user@example.com` / `TestPassword123!` at
   `http://localhost:3000`, go to `/admin/web-search`.
3. Add a search provider (SearXNG needs only a base URL, no key; any other type
   needs a real API key), activate it. Confirm the tool now appears as an option
   for a chat message (it should not have been offered before this step).
4. Send a message that requires current information, e.g. "what happened in the
   news today". Confirm a search block with queries and result documents appears,
   and the streamed answer has numbered citations that resolve to the web results.
5. Explicitly exclude web search for one message (via `allowed_tool_ids`/persona
   tool toggles) and paste a URL that is not indexed. Confirm `open_url` reports it
   as unavailable rather than fetching it live.
6. Paste a URL that *is* indexed with web search excluded. Confirm it still
   resolves, served from the index.

---

## 9. Footguns

- **The web search tool disappears silently with no provider configured.** There is
  no error state in the tool picker, no banner, nothing. If a PR looks like it broke
  web search, check `/admin/web-search` before the code: this is often just an
  unconfigured or deactivated provider, not a bug.
- **`OpenURLTool` is always present**, even without any web search provider,
  because it can serve indexed documents. Do not assume "no web search provider" ⇒
  "no web fetching happens at all"; `open_url` in indexed-only mode is a real,
  frequently-hit code path.
- **Excluding `WebSearchTool` for a message does not remove `OpenURLTool`.** It only
  disables its live-crawl path (`web_fetch_disabled=True`). A change that assumes
  the two tools are excluded together will break this coupling; see
  `test_open_url_web_search_coupling.py` for the expected behavior.
- **SSRF protection is not uniform across content providers.** It is enforced in
  `OnyxWebCrawler` via `ssrf_safe_get` (`onyx/utils/url.py`), which resolves DNS
  once and fetches the validated IP directly to defeat DNS-rebinding. Firecrawl,
  Exa, and Tavily content providers do not call `ssrf_safe_get` themselves, they
  hand the URL to a third-party API that does the actual fetch from outside
  Onyx's network. Adding a new content provider that fetches directly from the
  Onyx backend (rather than delegating to a third-party API) must add the same
  guard, or it reintroduces the exact SSRF surface `OnyxWebCrawler` was built to
  close.
- **A stored, shared API key cannot silently be repointed at a different host in a
  multi-tenant deployment.** `test_content_provider` refuses to reuse a stored key
  with a different `base_url` when `MULTI_TENANT` is set
  (`server/manage/web_search/api.py:411-419`). This is scoped narrowly to that one
  endpoint; it is not a general guarantee that `base_url` cannot change elsewhere.
- **Query sanitization is defensive, not a security boundary.**
  `_sanitize_query`/`_normalize_queries_input` (`web_search_tool.py`) strip control
  characters because LLMs sometimes emit them, not to prevent injection into the
  provider's own API.
