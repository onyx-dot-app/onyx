# Part 2: Search API — Implementation Plan

> Parent design doc: [search-design.md](search-design.md)

## Objective

Create `POST /api/search` — a general-purpose, PAT-authenticated endpoint that exposes Onyx's full chat-mode hybrid search pipeline as a standalone retrieval primitive. The endpoint instantiates `SearchTool` and calls `.run()` with the same code path that powers chat search, returning ranked, permissioned results without generating an LLM answer.

Consumers: onyx-cli (Part 3), Craft sandbox (Part 4), Onyx MCP server (future migration from `send_search_query`), and any authenticated integration.

---

## Requirements Summary


| ID   | Requirement                                                         | Section                                                 |
| ---- | ------------------------------------------------------------------- | ------------------------------------------------------- |
| R2.1 | Exact search pipeline parity via `SearchTool.run()`                 | [Pipeline Parity](#1-pipeline-parity-via-searchtoolrun) |
| R2.2 | Layered interface — simple for agents, configurable for power users | [Request Model](#2-request-model)                       |
| R2.3 | Structured + LLM-facing response format                             | [Response Model](#3-response-model)                     |
| R2.4 | PAT-based authentication                                            | [Authentication](#4-authentication)                     |
| R2.5 | Full ACL enforcement and tenant isolation                           | [Permissioning](#5-permissioning-and-tenant-isolation)  |
| R2.6 | Rate limiting deferred from V1                                      | [Rate Limiting](#6-rate-limiting)                       |
| R2.7 | Endpoint at `/api/search`                                           | [Router Placement](#7-router-placement)                 |


---

## Proposed Implementation

### 1. Pipeline Parity via `SearchTool.run()`

The endpoint constructs a `SearchTool` instance and calls `.run()` — the identical code path `tool_constructor.py:182` uses for chat. This gives us the full pipeline for free:

1. **Query expansion** — `semantic_query_rephrase()` (weight 1.3) + `keyword_query_expansion()` (weight 1.0) run in parallel
2. **Multi-query hybrid retrieval** — semantic queries (hybrid_alpha=None) + keyword queries (hybrid_alpha=0.2) against Vespa, plus federated Slack search
3. **Weighted RRF fusion** — `weighted_reciprocal_rank_fusion()` across all query results
4. **LLM document selection** — `select_sections_for_expansion()` filters top-N by relevance
5. **LLM context expansion** — `expand_section_with_context()` classifies each section (NOT_RELEVANT / MAIN_SECTION_ONLY / INCLUDE_ADJACENT_SECTIONS / FULL_DOCUMENT) and expands accordingly
6. **Federated retrieval** — Slack etc. runs automatically inside `SearchTool.run()`

**The Emitter problem.** `SearchTool` inherits from `Tool` which requires an `Emitter` instance. In the chat flow, the `Emitter` streams packets (`SearchToolStart`, `SearchToolQueriesDelta`, `SearchToolDocumentsDelta`) to the frontend via a shared queue. The search API has no streaming consumer — but it *does* want to capture the `SearchToolQueriesDelta` packet to return query expansion info in the response (R2.3).

**Solution: `CapturingEmitter`.** A thin `Emitter` subclass that collects packets into a list instead of putting them on a streaming queue. After `SearchTool.run()` returns, the endpoint inspects the captured packets to extract query expansion data. See [section 3](#3-response-model) for the implementation.

This is the minimal change. The alternative — making `Emitter` optional in `Tool.__init__` — would require touching every tool subclass and every call site that constructs tools. Not worth it.

**The Placement problem.** `SearchTool.run()` takes a `Placement` parameter (used to tag emitted packets with position info for the streaming UI). The search API doesn't use placements.

**Solution:** Pass a default `Placement(turn_index=0)`. This is harmless since the `CapturingEmitter` just collects everything into a list regardless of placement.

### 2. Request Model

**File:** `backend/onyx/server/features/search/models.py` (new)

The interface follows a layered design: only `query` is required, everything else has sensible defaults.

```python
class SearchAPIRequest(BaseModel):
    # Required
    query: str = Field(..., min_length=1, max_length=2048)

    # Filtering (optional)
    sources: list[DocumentSource] | None = None
    document_sets: list[str] | None = None
    tags: list[Tag] | None = None
    time_cutoff_days: int | None = Field(None, ge=1)

    # Persona scoping (optional)
    persona_id: int | None = None

    # Result control (optional)
    num_results: int = Field(default=50, ge=1, le=100)
    max_context_chunks: int = Field(default=25, ge=1, le=50)

    # Pipeline control (optional)
    skip_query_expansion: bool = False

    # Message history for query expansion context (optional, deferred from V1)
    # message_history: list[...] | None = None
```

#### Knob Audit — What to Expose

The search pipeline has many internal knobs. Here's the audit of every per-query configurable and the decision on exposure:


| Internal Knob                                                   | Expose?  | API Parameter             | Rationale                                                                                                                                              |
| --------------------------------------------------------------- | -------- | ------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Source type filter (`BaseFilters.source_type`)                  | Yes      | `sources`                 | Core filtering. Agents use this to scope by source.                                                                                                    |
| Document set filter (`BaseFilters.document_set`)                | Yes      | `document_sets`           | Power users with admin-configured doc sets.                                                                                                            |
| Time cutoff (`BaseFilters.time_cutoff`)                         | Yes      | `time_cutoff_days`        | Common agent pattern: "recent changes only." Converted to datetime internally.                                                                         |
| Tag filter (`BaseFilters.tags`)                                 | Yes      | `tags`                    | Tag-based scoping for structured metadata.                                                                                                             |
| Persona scoping (`persona_id`)                                  | Yes      | `persona_id`              | Access to admin-configured "search profiles" (doc sets, search start date, attached docs, hierarchy nodes).                                            |
| Result count (`num_hits` in `SearchToolOverrideKwargs`)         | Yes      | `num_results`             | Control result volume. Default 50 matches `NUM_RETURNED_HITS`.                                                                                         |
| Max LLM chunks (`max_llm_chunks` in `SearchToolOverrideKwargs`) | Yes      | `max_context_chunks`      | Control LLM context budget. Default 25 matches `MAX_CHUNKS_FED_TO_CHAT`.                                                                               |
| Skip query expansion (`skip_query_expansion`)                   | Yes      | `skip_query_expansion`    | Trade quality for speed/cost. Useful for precise queries. Already exists in `SearchToolOverrideKwargs`.                                                |
| Message history                                                 | Deferred | —                         | Significant interface complexity (defining a message format). The quality gap is real but most API callers send self-contained queries. Revisit in V2. |
| Query weights (LLM_SEMANTIC_QUERY_WEIGHT etc.)                  | No       | —                         | "No chance users can do a good job customizing this" (constants.py comment). Internal tuning, not a per-query knob.                                    |
| Hybrid alpha                                                    | No       | —                         | Internal search parameter. Controlled by query type (semantic vs keyword) automatically.                                                               |
| RRF K value                                                     | No       | —                         | Global tuning constant, not per-query.                                                                                                                 |
| Recency bias multiplier                                         | No       | —                         | Default of 1.0 is correct for standalone search. Per-query recency tuning is a V2 concern.                                                             |
| Context expansion type                                          | No       | —                         | LLM decides per-section. Overriding would require per-section control, too complex.                                                                    |
| Bypass ACL                                                      | No       | —                         | Security boundary. Never exposed to external callers.                                                                                                  |


#### Persona Scoping Design Decision

**Decision: Expose `persona_id` as an optional parameter.**

When `persona_id` is provided:

1. Load the persona from DB, verify the user has access to it
2. Extract `PersonaSearchInfo` (document_set_names, search_start_date, attached_document_ids, hierarchy_node_ids)
3. Use the persona's LLM configuration if it has one (via `get_llm_for_persona()`)
4. Merge persona filters with any explicit request filters (explicit filters take precedence)

When `persona_id` is omitted:

- Use empty `PersonaSearchInfo(document_set_names=[], search_start_date=None, attached_document_ids=[], hierarchy_node_ids=[])`
- Use the deployment's default LLM (via `get_default_llm()`)

This gives the API access to admin-configured search profiles without re-specifying all their settings, while keeping the simple case (no persona) as the default.

#### LLM Selection Design Decision

**Decision: Use the deployment's default LLM, or the persona's LLM if `persona_id` is specified.**

- No `persona_id` → `get_default_llm()` — simplest path, predictable cost
- With `persona_id` → `get_llm_for_persona(persona)` — respects admin LLM configuration on the persona
- No per-request model selection in V1. Adding `llm_provider` + `llm_model` parameters would require validating the user has access to the provider, handling model-specific token limits, etc. This is a V2 concern.

### 3. Response Model

**File:** `backend/onyx/server/features/search/models.py` (same file as request)

```python
class SearchAPIResult(BaseModel):
    citation_id: int
    document_id: str
    chunk_ind: int
    title: str
    blurb: str
    content: str
    link: str | None
    source_type: str
    score: float | None
    updated_at: str | None

class SearchAPIQueryExpansion(BaseModel):
    semantic_queries: list[str]
    keyword_queries: list[str]

class SearchAPIResponse(BaseModel):
    results: list[SearchAPIResult]
    llm_facing_text: str
    citation_mapping: dict[int, str]
    query_expansion: SearchAPIQueryExpansion | None
```

#### Mapping from `SearchTool.run()` output

`SearchTool.run()` returns a `ToolResponse`:

- `rich_response`: `SearchDocsResponse` with `search_docs`, `citation_mapping`, `displayed_docs`
- `llm_facing_response`: str (JSON string produced by `convert_inference_sections_to_llm_string`)

The mapping:


| Response field     | Source                                                                                                                                                              |
| ------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `results`          | Built from `rich_response.displayed_docs` (the LLM-selected subset) or `rich_response.search_docs` (if no selection). Each `SearchDoc` maps to a `SearchAPIResult`. |
| `llm_facing_text`  | `llm_facing_response` from `ToolResponse`. This is the JSON string that `convert_inference_sections_to_llm_string()` produces.                                      |
| `citation_mapping` | `rich_response.citation_mapping` — directly passed through.                                                                                                         |
| `query_expansion`  | Not directly available from `ToolResponse`. We need to capture the queries that `SearchTool` expanded. See below.                                                   |


**Query expansion capture.** `SearchTool.run()` computes expanded queries internally and emits them via `SearchToolQueriesDelta` to the `Emitter`, but doesn't return them in `ToolResponse`. Two options:

**Option A: Capture from Emitter.** Instead of a pure no-op emitter, use a `CapturingEmitter` that collects emitted packets. After `.run()` returns, extract the `SearchToolQueriesDelta` packet to get the queries.

**Option B: Extend `ToolResponse` to include query expansion data.** Add a field to `ToolResponse` or `SearchDocsResponse`.

**Go with Option A.** It requires no changes to `SearchTool` or `ToolResponse`, and the emitter is already our adapter layer:

```python
class CapturingEmitter(Emitter):
    """Emitter that captures packets for later inspection instead of streaming."""

    def __init__(self) -> None:
        self._model_idx = 0
        self._merged_queue = None  # type: ignore[assignment]
        self._drain_done = None
        self.packets: list[Packet] = []

    def emit(self, packet: Packet) -> None:
        self.packets.append(packet)

    def get_queries(self) -> list[str] | None:
        for packet in self.packets:
            if isinstance(packet.obj, SearchToolQueriesDelta):
                return packet.obj.queries
        return None
```

**Content field in results.** The `SearchDoc` model has `blurb` but not full `content`. The `llm_facing_response` contains the full content, but it's a formatted JSON string, not per-result content. For the `content` field in `SearchAPIResult`, we need to extract it from the `InferenceSection.combined_content`. This means we need access to the sections, not just the `SearchDoc` objects.

**Solution:** The `CapturingEmitter` also captures the `SearchToolDocumentsDelta` packet, which contains the `displayed_docs` (SearchDoc objects). But for full content, we need to also capture the sections. Two approaches:

1. **Parse `llm_facing_response`** — it's a JSON string with per-document content. Parse it and map content back to results by citation ID.
2. **Add sections to `SearchDocsResponse`** — extend the rich response to include the raw sections.

**Go with approach 1.** The `llm_facing_response` is already the authoritative content blob. Parse it, extract per-document content, and map back via citation ID. No changes to `SearchTool` internals.

### 4. Authentication

**Uses existing PAT auth.** The endpoint uses `Depends(current_user)` (or the PAT-aware `Depends(optional_user)` → require non-None). PAT auth already works:

1. Request includes `Authorization: Bearer onyx_pat_...`
2. `optional_user()` in `backend/onyx/auth/users.py:1667` extracts the token
3. `get_hashed_pat_from_request()` → `fetch_user_for_pat()` validates and returns the `User`
4. User's tenant is resolved from the User object

No new auth mechanism needed. The same auth dependency used by chat, personas, and other API endpoints.

**Auth dependency:**

```python
from onyx.auth.users import current_user

@router.post("")
async def search(
    request: SearchAPIRequest,
    user: User = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> SearchAPIResponse:
    ...
```

### 5. Permissioning and Tenant Isolation

The search runs as the authenticated user with full ACL enforcement. This happens automatically because `SearchTool.run()` calls `build_access_filters_for_user(self.user, db_session)` (line 556-559 of search_tool.py) to build ACL filters, which are passed to Vespa as `IndexFilters.access_control_list`.

Tenant isolation is handled by `CURRENT_TENANT_ID` being set on the request context by the auth middleware before the endpoint handler runs. `SearchTool.run()` opens its own DB session via `get_session_with_current_tenant()` (line 553), which reads the tenant from the context var.

**Explicit test requirement:** Cross-tenant document leakage is a security boundary. The integration test must index a document under tenant A and verify it is NOT returned when searching as a user in tenant B.

### 6. Rate Limiting

Deferred from V1 per the design doc (R2.6). The PAT scopes access to a single user. Agents iterating through multiple searches to refine results is expected behavior. Rate limiting can be added later via the standard `RATE_LIMITED` error code if usage patterns warrant it.

### 7. Router Placement

**File:** `backend/onyx/server/features/search/api.py` (new)

```python
router = APIRouter(prefix="/search")

@router.post("")
async def search(
    request: SearchAPIRequest,
    user: User = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> SearchAPIResponse:
    ...
```

Registered in `backend/onyx/main.py` via `include_router_with_global_prefix_prepended(application, search_router)`, alongside the existing chat, query, and MCP routers. The final URL is `POST /api/search`.

This is a top-level Onyx API, not under `/api/build/` (not Craft-specific) or `/api/chat/` (not chat-specific).

---

## File Changes

### New Files


| File                                              | Purpose                                                              |
| ------------------------------------------------- | -------------------------------------------------------------------- |
| `backend/onyx/server/features/search/__init__.py` | Package init                                                         |
| `backend/onyx/server/features/search/api.py`      | Endpoint handler                                                     |
| `backend/onyx/server/features/search/models.py`   | `SearchAPIRequest`, `SearchAPIResponse`, and related Pydantic models |


### Modified Files


| File                         | Change                         |
| ---------------------------- | ------------------------------ |
| `backend/onyx/chat/emitter.py` | Add `CapturingEmitter` subclass |
| `backend/onyx/main.py`         | Register the new search router  |


---

## Implementation Steps

### Step 1: `CapturingEmitter`

**File:** `backend/onyx/chat/emitter.py`

Add `CapturingEmitter` as described in [section 3](#3-response-model). This is a self-contained addition — no existing code changes.

### Step 2: Request and Response Models

**File:** `backend/onyx/server/features/search/models.py` (new)

Define `SearchAPIRequest`, `SearchAPIResult`, `SearchAPIQueryExpansion`, and `SearchAPIResponse` as specified in sections 2 and 3.

### Step 3: Endpoint Handler

**File:** `backend/onyx/server/features/search/api.py` (new)

The handler:

1. **Resolve LLM.** If `persona_id` is set, load persona and call `get_llm_for_persona()`. Otherwise, `get_default_llm()`.
2. **Build PersonaSearchInfo.** If `persona_id` is set, extract from the persona's document sets, search start date, attached documents, and hierarchy nodes. Otherwise, use empty `PersonaSearchInfo`.
3. **Build BaseFilters.** Convert request parameters to `BaseFilters`:
  - `sources` → `BaseFilters.source_type`
  - `document_sets` → `BaseFilters.document_set`
  - `time_cutoff_days` → `BaseFilters.time_cutoff` (convert to `datetime.now() - timedelta(days=N)`)
  - `tags` → `BaseFilters.tags`
4. **Get document index.** `get_default_document_index(search_settings, None, db_session)`.
5. **Get tool_id.** Look up the SearchTool's database ID from `BUILT_IN_TOOL_MAP` / the Tool table. This is the `id` of the row in the `tool` table where `in_code_tool_id = "internal_search"`.
6. **Construct SearchTool:**
  ```python
   emitter = CapturingEmitter()
   search_tool = SearchTool(
       tool_id=tool_id,
       emitter=emitter,
       user=user,
       persona_search_info=persona_search_info,
       llm=llm,
       document_index=document_index,
       user_selected_filters=base_filters,
       project_id_filter=None,
       persona_id_filter=None,
       bypass_acl=False,
       slack_context=None,
       enable_slack_search=True,
   )
  ```
7. **Build override kwargs:**
  ```python
   override_kwargs = SearchToolOverrideKwargs(
       starting_citation_num=1,
       original_query=request.query,
       message_history=None,
       user_memory_context=None,
       user_info=None,
       skip_query_expansion=request.skip_query_expansion,
       num_hits=request.num_results,
       max_llm_chunks=request.max_context_chunks,
   )
  ```
8. **Call SearchTool.run():**
  ```python
   placement = Placement(turn_index=0)
   tool_response = search_tool.run(
       placement=placement,
       override_kwargs=override_kwargs,
       queries=[request.query],  # The llm_kwargs["queries"] that SearchTool expects
   )
  ```
9. **Build response.** Map `ToolResponse` → `SearchAPIResponse`:
  - Extract `displayed_docs` (or `search_docs`) from `rich_response`
  - Extract `citation_mapping` from `rich_response`
  - Use `llm_facing_response` as `llm_facing_text`
  - Parse `llm_facing_response` JSON to populate per-result `content` fields
  - Extract query expansion from `CapturingEmitter.get_queries()`
  - Build `SearchAPIQueryExpansion` separating semantic vs keyword queries (best-effort; the emitter captures the combined list)
10. **Error handling.** Wrap the entire flow in a try/except:
  - Persona not found → `OnyxError(OnyxErrorCode.PERSONA_NOT_FOUND)`
    - Invalid source types → `OnyxError(OnyxErrorCode.INVALID_INPUT)`
    - LLM provider error → `OnyxError(OnyxErrorCode.LLM_PROVIDER_ERROR)`
    - Vespa/document index failure → `OnyxError(OnyxErrorCode.BAD_GATEWAY)`
    - General errors → `OnyxError(OnyxErrorCode.INTERNAL_ERROR)`

### Step 4: Router Registration

**File:** `backend/onyx/main.py`

Add:

```python
from onyx.server.features.search.api import router as search_api_router

include_router_with_global_prefix_prepended(application, search_api_router)
```

Place near the existing `query_router` and `chat_router` registrations.

---

## Persona Scoping — Detailed Flow

When `persona_id` is provided:

1. **Load persona** from DB with eager loading (`eager_load_for_tools=True` to get document_sets, attached_documents, hierarchy_nodes).
2. **Verify access** — check that the user can access this persona (same check the chat flow uses).
3. **Extract PersonaSearchInfo:**
  ```python
   PersonaSearchInfo(
       document_set_names=[ds.name for ds in persona.document_sets],
       search_start_date=persona.search_start_date,
       attached_document_ids=[doc.id for doc in persona.attached_documents],
       hierarchy_node_ids=[node.id for node in persona.hierarchy_nodes],
   )
  ```
4. **Merge filters.** If the request also has explicit `sources`, `document_sets`, etc., the explicit request filters take precedence. The persona's document set names and search start date are additive constraints (the persona scopes *down*, explicit filters scope *further* down).
5. **LLM resolution.** `get_llm_for_persona(persona, user)` — uses the persona's model configuration if set, otherwise falls back to default.

---

## Important Implementation Notes

### SearchTool.run() Invocation Contract

`SearchTool.run()` expects `queries` as a key in `**llm_kwargs` (line 610-619). The call looks like:

```python
tool_response = search_tool.run(
    placement=placement,
    override_kwargs=override_kwargs,
    queries=[request.query],
)
```

The `queries` kwarg is cast to `list[str]` at line 619. These are the "LLM queries" — in the chat flow, they come from the LLM's tool call. For the search API, we pass the user's query as a single-element list. The query expansion phase then generates additional semantic + keyword queries from this.

### original_query in SearchToolOverrideKwargs

`original_query` is used as the basis for:

- Slack federated search (line 772)
- LLM document selection query (line 826-830)

It should be set to `request.query`. If omitted, the code falls back to the semantic query or the first LLM query, which is fine but less predictable.

### Synchronous Execution

The endpoint is `async def` but `SearchTool.run()` is synchronous (it uses `run_functions_tuples_in_parallel` with thread pools internally). Wrap in `asyncio.to_thread()` or use `def` (FastAPI runs sync handlers in a threadpool automatically). Since SearchTool internally uses threads for parallelism, using a sync `def` handler is simplest and matches the chat endpoint pattern.

### LLM Cost Visibility

Every search request triggers 3-4 LLM calls:

1. `semantic_query_rephrase()` — 1 call
2. `keyword_query_expansion()` — 1 call
3. `select_sections_for_expansion()` — 1 call
4. `expand_section_with_context()` — N calls (one per selected section, run in parallel)

With `skip_query_expansion=True`, calls 1-2 are eliminated, reducing latency and cost at the expense of retrieval breadth.

### Tracing Compliance

Per CLAUDE.md, every LLM invocation must be tagged with a `LLMFlow` value. The LLM calls inside `SearchTool.run()` are already instrumented (they go through the same code path as chat search). No additional tracing work needed for the API layer itself.

---

## Tests

### External Dependency Unit Tests (primary value)

**File:** `backend/tests/external_dependency_unit/search/test_search_api.py`

These tests run against real Vespa + Postgres but not the full Onyx deployment. They call the endpoint via FastAPI test client.

1. **Basic search returns results.** Index test documents, call `POST /api/search { "query": "..." }`, assert results come back with non-empty blurbs, sequential citation IDs, valid source types.
2. **Source filtering works.** Index docs from two sources (e.g., google_drive and slack). Search with `sources: ["slack"]`. Assert only Slack docs returned.
3. **Time cutoff works.** Index docs with different `updated_at` timestamps. Search with `time_cutoff_days: 7`. Assert only recent docs returned.
4. **Persona scoping works.** Create a persona with a document set filter. Search with `persona_id`. Assert results are scoped to the persona's document set.
5. **ACL enforcement.** Index a doc accessible only to user A. Search as user B. Assert doc is NOT returned. This is the load-bearing security assertion.
6. **Cross-tenant isolation.** Index a doc under tenant A. Search as a user in tenant B. Assert doc is NOT returned.
7. **Skip query expansion.** Search with `skip_query_expansion: true`. Assert results still come back (just without LLM-expanded queries). Verify `query_expansion` in response is null or contains only the original query.
8. **Invalid source type rejected.** Send `sources: ["not_a_source"]`. Assert 400 with `INVALID_INPUT` error code.
9. **Unauthenticated request rejected.** Send request without auth header. Assert 401 with `UNAUTHENTICATED` error code.
10. **Response format.** Assert response matches `SearchAPIResponse` schema: `results` is a list, `llm_facing_text` is a non-empty string, `citation_mapping` maps ints to strings.

### Unit Tests (lightweight)

**File:** `backend/tests/unit/onyx/server/features/search/test_search_models.py`

1. **Request validation.** Verify `SearchAPIRequest` rejects empty query, query over max length, `num_results` out of range, negative `time_cutoff_days`.
2. **CapturingEmitter.** Verify it captures packets, `get_queries()` returns the right queries from a `SearchToolQueriesDelta` packet.
3. **Response construction.** Verify the mapping from `ToolResponse` + emitter packets to `SearchAPIResponse` handles edge cases (empty results, missing fields, null scores).

---

## Open Questions for Discussion

1. `**llm_facing_text` format.** The current `convert_inference_sections_to_llm_string()` produces a JSON string (not markdown, despite the design doc saying "citation-rich markdown"). The JSON format is `{"results": [{"document": 1, "title": "...", "content": "...", ...}]}`. Should the API return this JSON string as-is (matching chat behavior), or should we add a markdown formatter for the API? **Recommendation:** Return the JSON string as-is for V1. It's what the LLM actually sees in chat, so it's proven. The CLI (Part 3) can format it into markdown for human display.
2. **Query expansion separation.** The `CapturingEmitter` captures the combined query list from `SearchToolQueriesDelta`, but it doesn't separate semantic vs keyword queries. Should `SearchToolQueriesDelta` be extended to include the separation, or should the API response just return the combined list? **Recommendation:** Return the combined list in V1. The separation is an internal implementation detail. If callers need it later, extend `SearchToolQueriesDelta`.
3. **Document set name validation.** When `document_sets` is provided, should we validate that the names exist and the user has access? Or let the search pipeline silently return empty results for non-existent sets? **Recommendation:** Validate upfront. Return `NOT_FOUND` for non-existent sets. Fail fast is better than silent empty results that confuse agents.
4. **Endpoint verb.** The design doc says `POST /api/search`. Search is semantically a read operation, but the request body can be complex (lists of sources, tags, etc.) and may exceed URL length limits as a GET. POST is the right choice here — it matches the existing `POST /search/send-search-message` pattern.

