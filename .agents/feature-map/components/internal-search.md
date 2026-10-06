# Internal Search

> The `internal_search` tool. It turns a chat query into a set of expanded search
> lanes, runs them in parallel against the index and any federated sources, fuses
> the results, has an LLM pick and expand the best sections, and returns a
> citation-ready string plus a rich response for the UI.

**Verified against:** `268e4d5a3d` (2026-10-05)
**Domain:** search
**Edition:** CE, with EE field censoring hooked in via `fetch_ee_implementation_or_noop`
**Owns:**
`backend/onyx/tools/tool_implementations/search/search_tool.py`, `search_utils.py`,
`constants.py`,
`backend/onyx/context/search/pipeline.py`, `retrieval/search_runner.py`, `models.py`,
`federated/slack_search.py`, `preprocessing/access_filters.py`, `forced_document_set.py`,
`backend/onyx/secondary_llm_flows/query_expansion.py`, `source_filter.py`, `time_filter.py`,
`document_filter.py`

**Read first:** the module docstring at the top of
`backend/onyx/tools/tool_implementations/search/search_tool.py`. It is a five-step
summary of this component written by the people who built it. This document maps
it to code and adds verification guidance.

---

## 1. What the user experiences

The user asks a question. The assistant decides to search, and the UI shows the
queries it actually ran (which may differ from what the user typed, since they
are expanded), then a row of source cards for the documents it found, then a
streamed answer with numbered citations that open those same documents.

If the user's question implies a source ("in Zendesk...") or a time window
("...from last quarter"), the search narrows to that automatically, and the UI
shows a small filter note. If the user has selected filters by hand (source
type, document set, date range) in the chat settings, those apply on top.
Nothing about reranking is visible to the user because there is no reranking
step; what the user sees as "the model chose these documents" is an LLM
selection stage, not a scoring model.

---

## 2. Surfaces

### The tool itself

`SearchTool.NAME = "internal_search"` (`search_tool.py`). The LLM-visible tool
schema (`SearchTool.tool_definition`) has one required field, `queries: string[]`.
Its description tells the LLM that query expansion and filter extraction happen
downstream, so it should not hand-craft time or source scoping into the query text.

### HTTP endpoints

| Method | Path | Handler | Notes |
|---|---|---|---|
| POST | `/search` | `search` (`server/features/search/api.py`) | Runs the same `SearchTool.run()` pipeline as chat, for programmatic callers (onyx-cli, Craft sandbox, integrations). Returns ranked sections, no LLM answer. |
| POST | `/admin/search` | `admin_search` (`server/query_and_chat/query_backend.py`) | Admin-only. Calls `document_index.keyword_retrieval` or `random_retrieval` directly, bypassing this whole pipeline. Used for admin document inspection, not for chat. |
| GET | `/query/valid-tags` | `get_tags` (`server/query_and_chat/query_backend.py`) | Tag autocomplete for the filter UI. |

The EE Search UI backend (`ee/onyx/server/query_and_chat/search_backend.py`,
`ee/onyx/search/process_search_query.py`) is a **separate, lighter pipeline**. It
calls `search_pipeline()` directly with its own query expansion
(`ee/onyx/secondary_llm_flows/query_expansion.py:expand_keywords`) and its own
constant `TARGET_NUM_SECTIONS_FOR_LLM_SELECTION`. It shares `search_pipeline`,
`merge_individual_chunks`, `weighted_reciprocal_rank_fusion`, and
`select_sections_for_expansion` with this component, but is not the
`internal_search` tool and has no query-scope or time-filter auto-detection.

### Environment configuration

| Variable | Effect |
|---|---|
| `DISABLE_VECTOR_DB` (`configs/app_configs.py`) | When true, `SearchTool.is_available` returns `False` unconditionally: the tool cannot function without a vector DB. |
| `FORCED_DOCUMENT_SET_NAMES` (`configs/app_configs.py`, read by `forced_document_set.py:get_forced_document_set_names`) | Search UI only (`force_configured_document_set_scope=True` in `_build_index_filters`); hard-restricts retrieval to the named document sets. Disabled under `MULTI_TENANT`. Not applied to chat's `internal_search` calls. |
| `MAX_CHUNKS_FED_TO_CHAT` (`configs/chat_configs.py`) | Default for `SearchToolOverrideKwargs.max_llm_chunks`, the token-approximate cap on the final LLM string. |
| `HYBRID_ALPHA`, `NUM_RETURNED_HITS` (`configs/chat_configs.py`) | Default hybrid weighting and hit count when a lane doesn't override them. |
| `ENABLE_CC_PAIR_ACCESS_FILTER` (`configs/app_configs.py`, read by `OnyxRuntime.get_cc_pair_access_filter_enabled`) | Turns on the query-time cc-pair access filter in shadow mode. Results still use the old ACL filter, and disagreements are logged. The `enforce` flag is cache-only (default off) and only applies after the cc-pair ID backfill is complete (`access/cc_pair_access.py:get_cc_pair_access_mode`). |

---

## 3. Data model

This component reads document-set, ACL, and federated-connector state; it does
not own any tables. What it produces is written by [[core-chat-loop]]'s
`save_chat_turn`: `SearchDoc` rows (persisted `rich_response.search_docs`) and the
citation mapping on `ChatMessage`. See [[chat-persistence]] for those tables.

No new tables belong to this component. `PersonaSearchInfo`
(`context/search/models.py`) is a plain snapshot, not a table: it is built once
from the ORM `Persona` in `tool_constructor.py:_build_search_tool` before the DB
session that loaded it closes, so downstream code never lazy-loads a persona
relationship after the session is gone.

---

## 4. How it works

### 4.1 The nine stages, in order, inside `SearchTool.run`

```
run()                                              search_tool.py
 1. _expand_queries_and_decide_scope                search_tool.py
      ├─ semantic_query_rephrase                    secondary_llm_flows/query_expansion.py
      ├─ keyword_query_expansion                     secondary_llm_flows/query_expansion.py
      ├─ decide_search_scope                          secondary_llm_flows/source_filter.py
      └─ decide_time_filter                            secondary_llm_flows/time_filter.py
      (all four run in one run_functions_tuples_in_parallel batch)

 2. one lane per query, in parallel               ┐
      _run_search_for_query → search_pipeline      │  threadpool_concurrency.
      (+ optional _run_slack_search lane)          ┘  run_functions_tuples_in_parallel
        search_pipeline                              context/search/pipeline.py
          ├─ _build_index_filters                     context/search/pipeline.py
          └─ search_chunks                            context/search/retrieval/search_runner.py

 3. (no separate filtering stage; filters are compiled into the index query in step 2)

 4. weighted_reciprocal_rank_fusion                 tools/tool_implementations/search/search_utils.py
 5. merge_individual_chunks                          context/search/pipeline.py
 6. _trim_sections_by_tokens                          search_tool.py
    select_sections_for_expansion                     secondary_llm_flows/document_filter.py
 7. expand_section_with_context (parallel per doc)    search_utils.py
      └─ _retrieve_adjacent_chunks → document_index.id_based_retrieval
 8. merge_overlapping_sections                        search_utils.py
 9. convert_inference_sections_to_llm_string           tools/tool_implementations/utils.py
```

Lane fan-out and fusion, visually:

```
semantic query ──┐
LLM query(ies) ──┼─► search_pipeline lane ──► InferenceChunk[] ──┐
keyword query(s)─┘                                                │
                                                                    ├─► weighted_reciprocal_rank_fusion
Slack (optional) ─► _run_slack_search ────────────────────────────┘        (RRF_K_VALUE=50)
                                                                             │
                                                            merge_individual_chunks
                                                                             │
                                                             top_sections (num_hits cap)
```

### 4.2 Query expansion and scope (`_expand_queries_and_decide_scope`)

Runs, in one parallel batch, whichever of these apply:
- `semantic_query_rephrase` and `keyword_query_expansion` (`secondary_llm_flows/query_expansion.py`),
  unless `override_kwargs.skip_query_expansion` is set (a repeat search within the
  same turn defers entirely to the LLM's own query).
- `decide_search_scope` (`secondary_llm_flows/source_filter.py`), gated by
  `auto_detect_filters` and skipped once `_scope_decision_settled` latches to
  `True` for the rest of the turn (a "no source directive" result cannot flip
  back mid-turn).
- `decide_time_filter` (`secondary_llm_flows/time_filter.py`), computed once per
  turn and cached in `_time_filter`/`_time_filter_computed`.

`decide_search_scope` returns a `list[DocumentSource] | None`, restricted to
`connected_sources` (`db/connector.py:fetch_unique_document_sources`) intersected
with any user/persona source restriction. `decide_time_filter` returns a
`TimeFilter` (`secondary_llm_flows/time_filter.py`) whose `apply_to` intersects
the inferred window with any caller-selected range, so an inferred window can
only narrow, never widen, an explicit one; a disjoint inferred window is dropped
rather than applied.

When the scope narrows to a subset of sources, `run` appends a note to the
response (`_build_scope_note`) that names the sources covered and the queries run, so a repeat
call can vary its terms. Each call also records a `SearchCycle`, which
`decide_search_scope` reads on later calls in the same turn.

### 4.3 Parallel retrieval lanes

One lane per deduplicated semantic-style query (`deduplicate_queries`, weight
`LLM_SEMANTIC_QUERY_WEIGHT = 1.3` for the rephrased query,
`LLM_NON_CUSTOM_QUERY_WEIGHT = 0.7` for the LLM's own queries,
`ORIGINAL_QUERY_WEIGHT = 0.5` for the literal user message), one lane per
deduplicated keyword query (`LLM_KEYWORD_QUERY_WEIGHT = 1.0`,
`hybrid_alpha = KEYWORD_QUERY_HYBRID_ALPHA = 0.2`), plus at most one Slack lane
(`_run_slack_search`, weight `ORIGINAL_QUERY_WEIGHT`) when a Slack access token
was pre-fetched and an `original_query` is available. All lanes are dispatched in
one `run_functions_tuples_in_parallel` call.

Each non-Slack lane calls `_run_search_for_query`, which calls `search_pipeline`
(`context/search/pipeline.py`). `search_pipeline`:
1. builds `IndexFilters` via `_build_index_filters`, which validates any
   caller-supplied `document_set` names against `filter_document_set_names_by_user_access`
   (`db/document_set.py`), floors `updated_at_range` at the persona's
   `search_start_date` (never loosens it), and attaches the pre-fetched
   `access_control_list`, `cc_pair_access`, `attached_document_ids`, and `hierarchy_node_ids`;
2. calls `search_chunks` (`context/search/retrieval/search_runner.py`), which
   fans out to `get_federated_retrieval_functions`
   (`federated_connectors/federated_retrieval.py`) for any non-Slack federated
   source, and to `_embed_and_hybrid_search` (or, only when
   `hybrid_alpha == 0.0`, `_keyword_search`) for the indexed sources, then merges
   with `combine_retrieval_results`;
3. runs EE per-field censoring via `fetch_ee_implementation_or_noop("onyx.external_permissions.post_query_censoring", "_post_query_chunk_censoring", ...)`.

There is **no separate filtering stage**. Source, document-set, time, ACL, and
project/persona scope are all compiled into the `IndexFilters` object that goes
into the index query itself; nothing is filtered out of results after the fact
except the EE field censoring above.

There is **no reranking model in this path**. `RerankingModel`
(`natural_language_processing/search_nlp_models.py:RerankingModel`) exists, but
its only instantiation in the codebase is inside `warm_up_cross_encoder`, itself
marked `# No longer used` and called from nowhere
(`grep -rn "warm_up_cross_encoder" backend/` returns only its own definition).
The functional replacement for a reranker is the LLM selection stage in 4.5.

### 4.4 Rank fusion and chunk merge

`weighted_reciprocal_rank_fusion` (`search_utils.py`) combines the per-lane
ranked chunk lists: `score(item) = sum(weight / (RRF_K_VALUE + rank))` across
lanes, `RRF_K_VALUE = 50`, deduped by `f"{document_id}_{chunk_id}"`. Ties break
by rank-within-source then round-robin source order.

`merge_individual_chunks` (`context/search/pipeline.py`) then joins chunks from
the same document whose `chunk_id`s differ by exactly 1 into one
`InferenceSection`, keeping the position of the section's earliest-ranked chunk.
The merged list is capped to `override_kwargs.num_hits`.

### 4.5 LLM selection

`_trim_sections_by_tokens` (`search_tool.py`) first drops sections once a token
budget (`max_llm_chunks * DOC_EMBEDDING_CONTEXT_SIZE * SELECTION_TOKEN_BUDGET_MULTIPLIER`,
`SELECTION_TOKEN_BUDGET_MULTIPLIER = 2`) is exhausted, counting at most
`MAX_CHUNKS_FOR_RELEVANCE = 3` chunks per section so one chunk-heavy document
cannot starve the budget. `select_sections_for_expansion`
(`secondary_llm_flows/document_filter.py`) then makes one LLM call over all
surviving sections together (so the model can compare across documents, not just
within one) and returns the sections it picked plus any `best_doc_ids` it flagged.

### 4.6 Context expansion

For each selected section, `expand_section_with_context` (`search_utils.py`) runs
in parallel (again via `run_functions_tuples_in_parallel`, wrapped in
`expand_section_safe` so one failure falls back to the unexpanded section). Unless
the section is in `best_doc_ids` (`expand_override=True`, which skips straight to
`FULL_DOCUMENT`), it first asks `classify_section_relevance`
(`secondary_llm_flows/document_filter.py`) whether to keep it as-is, pull the
immediately adjacent chunks, pull the full surrounding window, or drop it as not
relevant after all. `FULL_DOCUMENT` fetches `FULL_DOC_NUM_CHUNKS_AROUND = 5`
chunks on each side via `_retrieve_adjacent_chunks`, which calls
`document_index.id_based_retrieval`.

### 4.7 Final merge and serialization

`merge_overlapping_sections` (`search_utils.py`) merges expanded sections from
the same document whose chunk ranges now overlap or touch, since context
expansion can make previously separate sections adjacent.
`convert_inference_sections_to_llm_string`
(`tools/tool_implementations/utils.py`) then builds the JSON string returned to
the LLM, assigning one citation number per unique `document_id` starting at
`override_kwargs.starting_citation_num`, and the parallel `citation_mapping`
(`citation_id -> document_id`).

---

## 5. Contracts and invariants

1. **ACL prefetch happens once per `run()`, before any parallel work, and is not
   optional.** `build_access_filters_for_user(self.user, db_session)` runs inside
   the single DB session opened at the top of `run()`. It returns a `UserAccessFilters`
   object: the ACL list plus an optional `CCPairAccessFilter` (`cc_pair_access`).
   The filter is set when the cc-pair flag is on. It is also set in `OFF` mode when
   the user cannot see a `SYNC_RESTRICTED` pair, so the pair stays hidden
   (`_build_cc_pair_access_filter`). There is no flag that skips
   it: the only input that decides document access is the `user` the caller passes
   to `SearchTool`. A caller that wants a narrower scope passes a narrower user (the
   Slack bot passes the anonymous user in shared channels). Do not add a skip flag;
   see [[access-control]] §5.3.
2. **Document-set names supplied by a user are access-checked in `SearchTool.run`**
   with `filter_document_set_names_by_user_access`. `SearchTool` calls
   `search_pipeline` with prefetched `acl_filters` and no `db_session`, so the
   matching check in `_build_index_filters` is skipped on this path. That second
   check applies only to callers that pass a session. Both checks must stay in
   place; removing either reopens the bypass where a user overrides the persona's
   configured document sets with arbitrary names. Unauthorized names raise
   `OnyxError(OnyxErrorCode.INSUFFICIENT_PERMISSIONS)`.
3. **`llm_facing_response` and `rich_response` serve different audiences.**
   `llm_facing_response` is the compact, trimmed, citation-tagged string the
   model reads. `rich_response` (`SearchDocsResponse`) carries `search_docs` (all
   top sections before LLM selection), `displayed_docs` (only the LLM-selected
   ones; `None` means all retrieved documents, an empty list means none), and
   `citation_mapping`. Do not feed
   `rich_response` fields back into the prompt, and do not trim
   `llm_facing_response` content out of `rich_response`.
4. **Citation numbering ranges are per tool call, not per turn.**
   `tool_runner.py` advances `starting_citation_num` by 100 for every tool call
   in a parallel batch specifically to avoid collisions between concurrent
   `SearchTool`/`WebSearchTool`/`OpenURLTool` calls. A change that shares one
   counter across calls will silently collide citations.
5. **The tool must keep working with `DISABLE_VECTOR_DB=true` meaning
   unavailable, not degraded.** `SearchTool.is_available` returns `False`
   outright in that case; it does not fall back to a reduced pipeline.
6. **The persona's `search_start_date` is a floor, never negotiable downward.**
   `_build_index_filters` takes the `max()` of it and any caller-supplied
   `updated_at_range.start`. A change here must preserve that direction.
7. **`PersonaSearchInfo` must stay a detached snapshot.** It is built before the
   DB session that loaded the persona closes (`tool_constructor.py`). Passing a
   live ORM `Persona` into a parallel search worker is the same class of bug as
   in [[core-chat-loop]]'s `ChatTurnSetup`.
8. **The Slack federated lane carries no `access_control_list`.**
   `_run_slack_search` builds its `ChunkIndexRequest` with
   `IndexFilters(access_control_list=None)`; access is enforced entirely by the
   scope of the OAuth or bot token that was pre-fetched, not by the standard ACL
   list. Do not assume every lane in the fan-out is ACL-filtered the same way.

---

## 6. Relationships

**Depends on**
- [[document-index]]: `document_index.hybrid_retrieval`, `keyword_retrieval`, and
  `id_based_retrieval` are the actual index calls; this component only decides
  what to ask for and how to combine the answers.
- [[access-control]]: `build_access_filters_for_user` / `get_acl_for_user`
  produce the ACL list this component compiles into every non-bypassed,
  non-Slack lane.
- [[federated-search]]: `get_federated_retrieval_functions` supplies non-Slack
  federated lanes; Slack is handled as a dedicated lane inside this component
  rather than through that mechanism.
- [[citations]]: `convert_inference_sections_to_llm_string` produces the
  citation-tagged string and mapping this component hands back.
- [[tools-framework]]: `SearchTool` implements `Tool`; `tool_runner.py` merges
  repeated calls and allocates the citation range.
- [[llm-providers]]: every secondary flow (`query_expansion`, `source_filter`,
  `time_filter`, `document_filter`) and the selection/expansion stages make
  their own LLM calls through the persona's resolved `LLM`.

**Depended on by**
- [[core-chat-loop]]: `construct_tools` attaches `SearchTool` per turn; the loop
  executes it like any other tool and folds its `ToolResponse` into history.
- [[web-search]]: a separate tool (`WebSearchTool`), not part of this component,
  but merged alongside it by the same `tool_runner.py` citation-range logic.
- The onyx-cli/programmatic `/search` endpoint (`server/features/search/api.py`)
  and the EE Search UI backend both reuse pieces of this pipeline outside the
  chat loop; see §2.

---

## 7. Blast radius

| If your change... | Also check |
|---|---|
| changes a lane weight or the RRF formula | run a retrieval eval before merging; a weight swing changes which documents survive to LLM selection, which is invisible in a unit test |
| adds a retrieval lane | the RRF weight list and `lane_specs` must stay parallel to `search_functions` |
| adds a filter field to `BaseFilters`/`IndexFilters` | `_build_index_filters`, the two document-set access checks, [[document-index]]'s query builder, and the Search UI filter form |
| changes the LLM-facing string format in `convert_inference_sections_to_llm_string` | [[citations]]; this breaks citation parsing everywhere the string is consumed, not just here |
| changes `SearchDocsResponse` fields | the UI renderer for `SearchToolDocumentsDelta`/search cards, and [[chat-persistence]]'s `SearchDoc` persistence, both of which read this shape |
| touches query expansion prompts (`query_expansion.py`, `source_filter.py`, `time_filter.py`, `document_filter.py`) | needs an eval; see `backend/onyx/evals/` |
| changes which `user` a caller passes to `SearchTool`, or adds any way to skip `build_access_filters_for_user` | [[access-control]] §5.3 and the Slack bot's identity choice ([[slack-bot]] §5.1); a wrong user is a data-exposure bug |
| changes Slack lane token pre-fetch or scoping | [[federated-search]] and the Slack bot's own ACL model, since this lane does not use `access_control_list` |

---

## 8. How to verify a change

### Tests

```bash
cd backend && uv run pytest tests/integration -k search
cd backend && uv run pytest tests/unit -k "search_tool or search_utils or query_expansion or document_filter or source_filter or time_filter"
```

See `backend/AGENTS.md` for the authoritative commands and required env, and
`backend/tests/README.md` for shared fixtures.

### Manual reproduction

1. Confirm services are up: `tail -f backend/log/api_server_debug.log`.
2. Open `http://localhost:3000`, sign in as `admin_user@example.com` /
   `TestPassword123!`.
3. Ask a question that forces a search across a connected source, for example
   "what does our onboarding doc say".
4. Watch for, in order: the queries-run block (`SearchToolQueriesDelta`), any
   filter note (`SearchToolFilterDelta`) if the question implied a source or
   time window, the document cards (`SearchToolDocumentsDelta`), then the
   streamed answer with numbered citations that open the right documents.
5. Ask a follow-up naming a specific connector by name (for example "search only
   in Zendesk") and confirm the filter note reflects that scope.
6. Hit `POST /api/search` directly with a query and confirm it returns the same
   shape of ranked sections without an LLM answer.

Drive the browser with `claude-in-chrome` against the user's real Chrome rather
than launching Playwright ad hoc.

### What "working" looks like

- Citation numbers in the streamed answer resolve to real documents in
  `displayed_docs`, never to `search_docs` entries that were not selected.
- A scoped search ("only Zendesk") never returns documents from other sources.
- Two `internal_search` calls in the same parallel tool batch never collide on
  citation numbers.

---

## 9. Footguns

- **There is no reranker**, despite `RerankingModel` existing in
  `natural_language_processing/search_nlp_models.py`. It is only ever
  constructed inside dead code (`warm_up_cross_encoder`). Anyone reading
  `search_nlp_models.py` and assuming a cross-encoder scores results is wrong;
  the LLM selection stage (4.5) is what actually narrows the result set.
- **Chat history keeps the LLM's original query arguments.** `SearchTool.run`
  emits the expanded queries in `SearchToolQueriesDelta` for the UI. It does not
  replace `tool_call.tool_args`, so history shows what the model wrote. See also
  [[core-chat-loop]] §9.
- **Scope and time decisions are cached per turn**, not per call.
  `_scope_decision_settled` latches once `decide_search_scope` returns `None`
  (no source directive), and `_time_filter_computed` latches after the first
  `decide_time_filter` call. A second `internal_search` call in the same turn
  will not re-derive either, even if the conversation state looks like it
  should.
- **`hybrid_alpha == 0.0` short-circuits to pure keyword retrieval**
  (`_keyword_search` in `search_runner.py`), skipping the embedding call
  entirely.
  See [[document-index]].
- **An explicitly empty `source_type` list is a real answer, not a missing
  filter.** `SearchTool.run` treats `user_selected_filters.source_type == []`
  (outside project mode, which ignores user filters)
  as "search nothing" and returns an empty response immediately, while `None`
  means "no source filter at all". Do not normalize one into the other.
- **The Slack lane is not ACL-filtered the same way as every other lane.** Its
  `IndexFilters.access_control_list` is `None` by construction; access is
  whatever the pre-fetched Slack token can see. See §5.8.
