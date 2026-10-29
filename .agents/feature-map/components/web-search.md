# Web Search

> Search of the public internet and fetch of web pages: the `web_search` and
> `open_url` tools, the admin page that picks the active providers, and the
> `/web-search` API for callers outside the chat loop.

**Verified against:** `a4e97fcea1` (2026-10-29)
**Edition:** CE

---

## User experience

- **An admin** opens Admin > Web Search, adds a search provider and an optional
  content provider, tests the key, and activates one of each. Without an active
  search provider, the model is not offered web search, and nothing shows an
  error.
- **A chat user** sees a search block with the queries the model ran, a list
  of web results, and numbered citations that work like internal-search
  citations. When the model reads a link (a search result or a link the user
  pasted), the user sees the pages it opened.
- **A user who turns off web search for a message** still gets pasted links
  that match indexed documents. A link that is not indexed is reported to the
  model as unavailable. Nothing is fetched from the internet.
- **When it fails**, one failed query is logged and the others still return
  results. The model gets an error only when every query fails or no result
  comes back. When `open_url` can read no page, the model gets a message that
  lists each failed URL and its reason.
- **An API or MCP caller** uses `/web-search/search`, `/search-lite` or
  `/open-urls`. With no active search provider, the two search routes return
  an `INVALID_INPUT` error, not a missing tool. `/open-urls` needs no search
  provider and uses the built-in crawler when no content provider is active.

---

## Scope

This component owns `WebSearchTool` and its search clients, `OpenURLTool` and
its content clients, the provider records and their key handling, the admin
API and page, and the runtime API.

Its neighbours own:
- [[tools-framework]]: tool construction, `should_disable_open_url_web_fetch`,
  call merging and citation ranges.
- [[citations]]: the citation number blocks and the document JSON format.
- [[internal-search]]: `InferenceSection` handling and the search packets that
  both tools reuse.
- [[mcp-server]]: the MCP tools that call the runtime API.

---

## Architecture

```
web_search(queries)                         WebSearchTool.run
  -> one provider call per query, parallel  errors kept per query
  -> drop results with no title or snippet, round-robin merge,
     dedupe by (title, link), cap at DEFAULT_MAX_RESULTS
  -> inference_section_from_internet_search_result
  -> convert_inference_sections_to_llm_string        [[citations]]

open_url(urls)                              OpenURLTool.run
  -> resolve URLs to indexed document IDs   _resolve_urls_to_document_ids
  -> in parallel: indexed retrieval (user ACL)  +  crawl via content provider
  -> _fallback_link_lookup for URLs both missed
  -> _merge_indexed_and_crawled_results      indexed copy wins when it has content
```

**URL resolution.** `tools/tool_implementations/open_url/url_normalization.py` maps a pasted URL to an
indexed document id through the connector class's `normalize_url`
([[connectors]]). A connector may return `candidate_document_ids`, as
[[google-drive]] does because a pasted URL does not show the file type.
Resolution takes whichever candidate is indexed.

**One active row per table.** `InternetSearchProvider` and
`InternetContentProvider` each act as a single slot. Activation clears
`is_active` on every other row of that table in one transaction
(`db/web_search.py:set_active_web_search_provider`,
`set_active_web_content_provider`). A second provider is not a fallback. It
waits until an admin activates it.

**Provider factory.** `tools/tool_implementations/web_search/providers.py:build_search_provider_from_config`
and `build_content_provider_from_config` turn a type, key and config into a
client. They raise when a type's required config is missing, such as a
SearXNG base URL or a Firecrawl base URL. See `shared_configs/enums.py` for
the current provider types. `provider_requires_api_key` exempts only SearXNG.
With no active content provider, `open_url` uses the built-in `OnyxWebCrawler`.

**Shared keys.** Some vendors serve both search and content. Their key is
copied to the other side on upsert (`_SEARCH_TO_CONTENT_SYNC` and
`_CONTENT_TO_SEARCH_SYNC` in `server/manage/web_search/api.py`). A new copy is
inactive. An existing row gets the new key and keeps its active state. For
Firecrawl, the copied row also gets a base URL derived from the
sibling endpoint. If no URL can be derived, no copy is made.

**The web search and open_url coupling.** `OpenURLTool.is_available` is always
true, because `open_url` can serve indexed documents. When the agent has
`WebSearchTool` and the request's `allowed_tool_ids` excludes it,
`tools/tool_constructor.py:should_disable_open_url_web_fetch` returns true and
`construct_tools` builds `OpenURLTool` with `web_fetch_disabled=True`. The tool
then builds no content provider. It marks each unresolved URL as failed with
`WEB_FETCH_DISABLED_REASON`, and the link fallback can still serve it from the
index. The reason: `open_url` is hidden from the chat tool toggles, so turning
off web search must also cut its internet access.
`backend/tests/unit/onyx/tools/test_open_url_web_search_coupling.py` checks the
coupling.

**Without a vector DB.** When `DISABLE_VECTOR_DB` is set, `open_url` only
crawls. It has no indexed retrieval and no link fallback. If web fetch is also
disabled, `construct_tools` does not build `OpenURLTool`.

**Snippets and citations.** The chat loop and the research agent pass snippets from earlier results
(`tools/tool_implementations/web_search/utils.py:extract_url_snippet_map`) to `open_url`, which truncates
a crawled page around the snippet. `open_url` reuses the number that a URL
already has in the turn. `tools/tool_runner.py:run_tool_calls` builds that map
from the turn's citation mapping, which holds every numbered document, not only
the cited ones.

**Runtime API.** `server/features/web_search/api.py` builds clients from the
active rows with the same factories, but it does not use the tool classes.
Its behaviour differs from the tools in three ways. `/open-urls` and `/search`
only crawl, so they have no indexed lookup and no ACL path. The routes run the
queries one after another, and one failed query fails the whole request with
`BAD_GATEWAY` (`_run_web_search`). An error from the content provider also
fails the whole request (`_open_urls`). `/search` fetches the full content of
every result URL. All
three routes need only `READ_SEARCH`. `/open-urls` and the MCP `open_urls` tool
share the `OPEN_URLS_MAX_URLS_PER_REQUEST` cap. Do not build an MCP or API
change on tool behaviour, such as partial results or the indexed fallback.

---

## Contracts and traps

1. `no-provider-no-tool` **In chat, no active search provider means no tool.**
   `tools/tool_implementations/web_search/web_search_tool.py:WebSearchTool.is_available`
   checks `db/web_search.py:fetch_active_web_search_provider`.
   `__init__` raises `RuntimeError` only as a backstop. If web search seems
   broken, check the admin page before the code. The runtime API raises an
   `OnyxError` instead, because an HTTP caller has no "absent tool".
2. `open-url-uses-user-acl` **The indexed path of `open_url` must use the acting
   user's ACL.**
   `tools/tool_implementations/open_url/open_url_tool.py:OpenURLTool._build_index_filters`
   calls
   `build_access_filters_for_user`, and retrieval runs `censor_chunks_for_user`.
   A pasted link must not reveal an indexed document the user cannot search
   ([[access-control]]).
3. `fetches-use-ssrf-guard` **The `open_url` fetchers use the SSRF guard on
   every hop** ([[auth-and-identity#outbound-fetch-uses-ssrf-guard]]).
   `tools/tool_implementations/open_url/onyx_web_crawler.py:OnyxWebCrawler`
   fetches with `ssrf_safe_get`. Its headless-browser fallback cannot use that
   function, so `utils/playwright_fetch.py:fetch_rendered_html` checks the URL,
   each request (`install_ssrf_guard`) and the final URL.
   `OnyxWebCrawler._should_validate_ssrf` reads the admin level. The third-party
   content clients send the URL to a vendor API and do not fetch it from Onyx.
4. `stored-key-target-locked` **On cloud, a stored key cannot move to a new
   target.**
   `server/manage/web_search/api.py:_require_stored_key_target_unchanged` runs on both upserts and
   both test endpoints when the request reuses the stored key. It rejects a
   change of provider type or base URL under `MULTI_TENANT`. Without it, an
   admin could send the stored key to a host they control. Self-hosted
   deployments skip it.
5. `api-key-never-exposed` **The API key never reaches the model, a packet or a
   list response.** The server reads the plain key only to build a provider
   client. Admin views return a masked key.
6. `return-inference-sections` **Both tools must return `InferenceSection` and
   `SearchDocsResponse`.** Web citations need no special case downstream because
   of this. A new shape breaks citations without an error.
7. `citation-block-per-tool` **A new search-like tool needs its own citation
   block.** Add a branch in `tools/tool_runner.py:run_tool_calls` that sets
   `starting_citation_num` and advances it ([[citations]] owns the rule).
8. `query-cleaning-not-security` **Query cleaning is not a security boundary.**
   `tools/tool_implementations/web_search/web_search_tool.py:_sanitize_query`
   strips control characters that models sometimes emit. It does not protect the
   provider API.

---

## Dependencies

- [[tools-framework]]: builds both tools, applies the coupling, merges repeated
  calls and assigns citation blocks.
- [[citations]]: numbers the sections both tools return.
- [[internal-search]]: shares the search packets and section conversion.
- [[access-control]]: ACL for the indexed path of `open_url`.
- [[document-index]]: `id_based_retrieval` for indexed URLs.
- [[streaming-protocol]]: the search and open-URL packets.
- [[agents-personas]]: an agent's tools decide whether `WebSearchTool` is
  offered.
- [[multi-tenancy]]: `MULTI_TENANT` gates the stored-key check and adds the
  tenant to `open_url` index filters.
- [[auth-and-identity]]: the SSRF guard and the admin SSRF protection level.

---

## Recipes

- `new-web-provider` **Add a search or content provider.** Copy the Firecrawl provider, which
  serves both sides. Add the type to `WebSearchProviderType` or
  `WebContentProviderType` in `shared_configs/enums.py`, add a client under
  `tools/tool_implementations/web_search/clients/` or
  `tools/tool_implementations/open_url/`, and add a branch to the matching
  factory in `tools/tool_implementations/web_search/providers.py`. List the
  current clients with `git ls-files backend/onyx/tools/tool_implementations/web_search/clients/`.
  Update `provider_requires_api_key` if it needs no key, the key-sync lists in
  `server/manage/web_search/api.py` if one key serves both sides, and the admin
  setup form in `web/src/views/admin/WebSearchPage/`. A client that fetches
  pages from Onyx must use the SSRF guard
  ([[auth-and-identity#outbound-fetch-uses-ssrf-guard]]).
- `no-web-search` **Investigate "the model never searches the web".** Check for an active row:
  `select name, provider_type, is_active from internet_search_provider;`. No
  active row means no tool ([[#no-provider-no-tool]]). Then check that the
  agent has the web search tool and that the message did not turn it off.
- `reproduce-index-only-open-url` **Reproduce the index-only `open_url` mode.** Activate a provider (SearXNG
  needs only a base URL), turn off web search for one message, and paste a link
  that is not indexed. The model must report it as unavailable. A pasted link
  that is indexed must still resolve.

---

## Verification

- Unit tests: `backend/tests/unit/onyx/tools/tool_implementations/websearch/`,
  `backend/tests/unit/onyx/tools/tool_implementations/open_url/`, and the
  coupling test in `backend/tests/unit/onyx/tools/`.
- External dependency: `backend/tests/external_dependency_unit/tools/open_url/`.
- Integration: `backend/tests/integration/tests/web_search/`.
