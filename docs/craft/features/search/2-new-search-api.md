# Part 2: Search API — Implementation Plan

> **Status: IMPLEMENTED** — shipped and merged via PR #10966.
> Annotations marked *[Diverged]* or *[New]* note where the final implementation
> differs from or adds to the original plan.

> Parent design doc: [search-design.md](search-design.md)

## Objective

Create `POST /api/search` — an authenticated endpoint that exposes the full chat-mode search pipeline as a standalone retrieval primitive. The endpoint instantiates `SearchTool` and calls `.run()` — the same code path `tool_constructor.py:182` uses for chat — returning ranked, permissioned results without generating an LLM answer.

The goal is feature parity with the core chat flow's search — not improving `SearchTool`'s constructor API or exposing significantly more configuration than the chat UI already allows.

Consumers: onyx-cli (Part 3), Craft sandbox (Part 4), and any authenticated integration.

---

## What the Endpoint Does

Constructs a `SearchTool`, calls `.run()`, maps the output to a JSON response. The pipeline executes:

1. LLM query expansion — `semantic_query_rephrase()` + `keyword_query_expansion()` in parallel
2. Multi-query hybrid retrieval against Vespa (semantic + keyword queries with different hybrid alpha values)
3. Weighted reciprocal rank fusion across all query results
4. LLM document selection — relevance filtering of top-N sections
5. LLM context expansion — adjacent chunk inclusion based on per-section relevance classification
6. Federated retrieval (Slack, etc.) in parallel with Vespa queries

All of this happens inside `SearchTool.run()`. The endpoint's job is to construct the tool, call it, and format the output.

---

## Request

```python
class SearchAPIRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2048)

    # Filtering — all optional, maps directly to BaseFilters
    sources: list[DocumentSource] | None = None
    document_sets: list[str] | None = None
    tags: list[Tag] | None = None
    time_cutoff_days: int | None = Field(None, ge=1)

    # Result count — maps to SearchToolOverrideKwargs.num_hits
    num_results: int = Field(default=50, ge=1, le=100)

    # Persona scoping — when set, the search inherits the persona's document set
    # filters, search start date, attached documents, hierarchy nodes, and LLM
    # configuration. This is the same configuration that takes effect when a user
    # selects a persona in the chat UI.
    persona_id: int | None = None

    # LLM to use for query expansion and document selection.
    # When omitted, uses the persona's LLM (if persona_id set) or the deployment default.
    provider: str | None = None
    model: str | None = None

    # Skip LLM query expansion — maps to SearchToolOverrideKwargs.skip_query_expansion
    skip_query_expansion: bool = False

    # Conversational context for query expansion. When omitted, the handler
    # creates a single USER message from the query.
    message_history: list[ChatMinimalTextMessage] | None = None

    @model_validator(mode="after")
    def _provider_model_pair(self) -> Self:
        if (self.provider is None) != (self.model is None):
            raise ValueError("provider and model must both be set or both omitted")
        return self
```

*[New -- not in original plan] `message_history` was added to the request model as an enhancement for consumers that need conversational context in query expansion (e.g. an agent mid-conversation). The plan explicitly deferred this ("no V1 consumer").*

Every parameter beyond `query` is optional with a default that matches chat search behavior. Filter parameters map directly to `BaseFilters`. `num_results` and `skip_query_expansion` map to existing `SearchToolOverrideKwargs` fields. `persona_id` configures the search the same way selecting a persona in the chat UI does — document set scoping, search start date, attached docs, and LLM selection all come from the persona.

Parameters deliberately not exposed: query weights, hybrid alpha, RRF K, recency bias (internal tuning constants), bypass ACL (security boundary).

---

## Response

```python
class SearchAPIResult(BaseModel):
    citation_id: int | None   # not all docs appear in citation_mapping
    document_id: str
    chunk_ind: int
    title: str
    blurb: str
    link: str | None
    source_type: str          # DocumentSource.value
    score: float | None
    updated_at: str | None    # ISO 8601

class SearchAPIResponse(BaseModel):
    results: list[SearchAPIResult]
    llm_facing_text: str
    citation_mapping: dict[int, str]
```

### Mapping from `SearchTool.run()` output

`SearchTool.run()` returns a `ToolResponse` with:
- `rich_response`: `SearchDocsResponse` containing `search_docs`, `citation_mapping`, and `displayed_docs`
- `llm_facing_response`: str (JSON string from `convert_inference_sections_to_llm_string()`)

Field mapping:

- **`results`** — built from `rich_response.displayed_docs` if present, otherwise `rich_response.search_docs`. `displayed_docs` is the LLM-selected subset but is nullable; `search_docs` is always populated. For each `SearchDoc`, build a `SearchAPIResult` by reverse-looking up the `citation_id` from `citation_mapping` (which maps `int → document_id`; invert to `document_id → int`). `source_type` is `SearchDoc.source_type.value` (it's a `DocumentSource` str enum). `updated_at` is serialized to ISO 8601 via `SearchDoc.updated_at.isoformat()` if not None.
- **`llm_facing_text`** — `llm_facing_response`, passed through directly. This is the same content format the LLM sees in chat.
- **`citation_mapping`** — `rich_response.citation_mapping`, passed through directly.

The `llm_facing_text` is what agents consume. The `results` array is structured metadata for programmatic consumers. The CLI (Part 3) will print `llm_facing_text` to stdout by default and the full response in `--json` mode.

---

## Endpoint Handler

**File:** `backend/onyx/server/features/search/api.py`

```python
router = APIRouter(prefix="/search")

@router.post("", dependencies=[Depends(require_vector_db)])
def search(
    request: SearchAPIRequest,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> SearchAPIResponse:
```

Sync `def` handler — `SearchTool.run()` is synchronous (uses internal thread pools). FastAPI runs sync handlers in a threadpool automatically. Auth uses `require_permission(Permission.BASIC_ACCESS)`, consistent with other feature endpoints.

**Note on router prefix:** The EE search backend already registers a router at `prefix="/search"` (with endpoints at `/send-search-message` and `/search-flow-classification`). Our `POST ""` on the same prefix creates `POST /api/search`, which does not collide with those sub-paths. FastAPI resolves these correctly.

The handler does:

1. **Load persona (if specified).** If `persona_id` is set, load the persona with eager loading (`eager_load_for_tools=True` to get document_sets, attached_documents, hierarchy_nodes). Verify the user has access. Raise `OnyxError(OnyxErrorCode.PERSONA_NOT_FOUND)` if it doesn't exist or is inaccessible. Extract `PersonaSearchInfo`:
   ```python
   PersonaSearchInfo(
       document_set_names=[ds.name for ds in persona.document_sets],
       search_start_date=persona.search_start_date,
       attached_document_ids=[doc.id for doc in persona.attached_documents],
       hierarchy_node_ids=[node.id for node in persona.hierarchy_nodes],
   )
   ```
   If no `persona_id`, use empty `PersonaSearchInfo(document_set_names=[], search_start_date=None, attached_document_ids=[], hierarchy_node_ids=[])`.
2. **Get LLM.** Resolution priority:
   - If `provider`/`model` are specified: look up the provider via `fetch_existing_llm_provider(request.provider, db_session)`, check access via `can_user_access_llm_provider(provider_model, user_group_ids, persona, is_admin=...)`, convert via `LLMProviderView.from_model(provider_model)`, create via `llm_from_provider(model_name=request.model, llm_provider=provider_view)`.
   - Else if `persona_id` is set: `get_llm_for_persona(persona, user)` — uses the persona's model configuration if it has one, otherwise falls back to default.
   - Else: `get_default_llm()`.

   *[Diverged] The implementation also calls `check_llm_cost_limit_for_provider()` before running search. This was not in the plan but is good multi-tenant practice.*

3. **Build filters:** Map request params to `BaseFilters(source_type=request.sources, document_set=request.document_sets, tags=request.tags, time_cutoff=...)`. Convert `time_cutoff_days` to `datetime.now() - timedelta(days=N)`.
4. **Get document index:** `get_default_document_index(search_settings, None, db_session)`.
5. **Get tool_id:** Query the `tool` table for `in_code_tool_id = "internal_search"`.
6. **Construct SearchTool:**
   ```python
   search_tool = SearchTool(
       tool_id=tool_id,
       emitter=NullEmitter(),
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
7. **Call `.run()`:**
   ```python
   tool_response = search_tool.run(
       placement=Placement(turn_index=0),
       override_kwargs=SearchToolOverrideKwargs(
           starting_citation_num=1,
           original_query=request.query,
           skip_query_expansion=request.skip_query_expansion,
           num_hits=request.num_results,
       ),
       queries=[request.query],
   )
   ```
8. **Map output** to `SearchAPIResponse` and return.

### The Emitter Dependency

`SearchTool` requires an `Emitter` (inherited from `Tool`). In chat, the emitter streams progress packets to the frontend. The search API has no streaming consumer.

`NullEmitter` is a trivial subclass defined in `backend/onyx/chat/emitter.py` that discards all packets:

```python
class NullEmitter(Emitter):
    def __init__(self) -> None:
        self._model_idx = 0
        self._merged_queue = None  # type: ignore[assignment]
        self._drain_done = None

    def emit(self, packet: Packet) -> None:
        pass
```

`SearchTool.run()` also takes a `Placement` parameter for tagging emitted packets. Pass `Placement(turn_index=0)` — it's discarded by the `NullEmitter`.

### SearchTool.run() Invocation Details

`SearchTool.run()` expects `queries` as a key in `**llm_kwargs` (line 610). In chat, this comes from the LLM's tool call arguments. For the API, pass `[request.query]` as a single-element list.

`original_query` in `SearchToolOverrideKwargs` is used for Slack federated search (line 772) and LLM document selection (line 826). Set it to `request.query`.

### Error Handling

- Persona not found / inaccessible → `OnyxError(OnyxErrorCode.PERSONA_NOT_FOUND)`
- LLM provider not found → `OnyxError(OnyxErrorCode.NOT_FOUND)`
- LLM provider access denied → `OnyxError(OnyxErrorCode.UNAUTHORIZED)`
- Invalid source types → `OnyxError(OnyxErrorCode.INVALID_INPUT)`
- LLM provider error → `OnyxError(OnyxErrorCode.LLM_PROVIDER_ERROR)`
- Vespa failure → `OnyxError(OnyxErrorCode.BAD_GATEWAY)`

Authentication errors are handled by the `require_permission` dependency before the handler runs.

---

## Authentication and Permissioning

Uses `Depends(require_permission(Permission.BASIC_ACCESS))`, consistent with other feature endpoints. The token resolves to a `User`; the search runs with that user's permissions. No new auth mechanism.

ACL enforcement happens automatically inside `SearchTool.run()` — it calls `build_access_filters_for_user(self.user, db_session)` (search_tool.py:556) to build access filters passed to Vespa.

Tenant isolation is handled by `CURRENT_TENANT_ID` being set on the request context by auth middleware. `SearchTool.run()` opens its own DB session via `get_session_with_current_tenant()` (line 553), which reads the tenant from the context var.

Rate limiting is deferred from V1 (R2.6).

---

## File Changes

### New Files

| File | Purpose |
|------|---------|
| ~~`backend/onyx/server/features/search/__init__.py`~~ | Not created — Python namespace packages handle this |
| `backend/onyx/server/features/search/api.py` | Endpoint handler |
| `backend/onyx/server/features/search/models.py` | `SearchAPIRequest`, `SearchAPIResponse`, `SearchAPIResult` |

### Modified Files

| File | Change |
|------|--------|
| `backend/onyx/main.py` | Register the search router via `include_router_with_global_prefix_prepended` |
| `backend/onyx/chat/emitter.py` | `NullEmitter` subclass (see Emitter section above) |

No modifications to `SearchTool`, `ToolResponse`, `SearchToolOverrideKwargs`, or any other existing code.

---

## Tests

*[Diverged] The original plan specified external dependency unit tests and model unit tests. The implementation uses integration tests instead, testing against a full Onyx deployment. Validation is covered implicitly through the integration tests.*

### Integration Tests

**File:** `backend/tests/integration/tests/search/test_search_api.py`

Run against a real Onyx deployment. Six tests:

1. **Basic search returns results.** Search for indexed content, assert non-empty results with expected fields.
2. **Document set filtering.** Filter to a specific document set, assert only matching docs returned.
3. **ACL enforcement.** Search as a user without access, assert restricted docs not returned. *(Enterprise-only: skipped without `ENABLE_PAID_ENTERPRISE_EDITION_FEATURES`.)*
4. **Persona scoping.** Search with a persona that has document set filters, assert scoping is applied.
5. **Invalid persona 404.** Request with a nonexistent `persona_id`, assert 404 response.
6. **Unauthenticated rejected.** No auth header, assert 401/403 response.

---

## Implementation Notes

This section summarizes genuinely new additions or architectural decisions not covered by the original plan.

### `message_history` parameter *[New]*

`message_history: list[ChatMinimalTextMessage] | None = None` was added to the request. When omitted, the handler creates a single USER message from the query. This allows consumers that have conversational context (e.g. an agent mid-conversation) to pass it through for better query expansion. The plan explicitly deferred this ("no V1 consumer"), but it was added as a low-cost enhancement.

### `NullEmitter` in `emitter.py` *[Diverged]*

Placed in `backend/onyx/chat/emitter.py` instead of `api.py`. As a proper subclass of `Emitter`, it can be reused by any code path that needs to invoke tools without a streaming consumer.

### `require_vector_db` dependency *[New]*

The route includes `dependencies=[Depends(require_vector_db)]` to short-circuit with a clear error when the vector database is not configured. This matches the pattern used by other search-dependent endpoints.

### LLM cost limit check *[New]*

The handler calls `check_llm_cost_limit_for_provider()` before running search. This enforces per-tenant LLM cost limits, preventing a single tenant from exhausting shared LLM budget via search queries.

### What matched the plan exactly

- Endpoint at `POST /api/search` via `router = APIRouter(prefix="/search")`
- Auth: `require_permission(Permission.BASIC_ACCESS)`
- Sync `def` handler
- Persona loading with eager load, `PersonaSearchInfo` construction
- LLM resolution priority (explicit provider -> persona -> default)
- Filter building (sources, document_sets, tags, time_cutoff)
- `SearchTool` construction and `.run()` call shape
- Output mapping from `SearchDocsResponse` to `SearchAPIResponse`
- `Placement(turn_index=0)` for `NullEmitter`
- Router registered in `main.py`

### Items deferred or skipped

- `__init__.py` for the search package was not created (Python namespace packages handle this).
- External dependency unit tests and model unit tests were replaced by integration tests.
- Planned tests for source filtering, time cutoff, cross-tenant isolation, skip query expansion, and invalid source rejection were not included in the integration test suite.
