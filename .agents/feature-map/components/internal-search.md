# Internal Search

> The `internal_search` tool: it expands a query into parallel lanes over the
> document index and federated sources, fuses them, and has an LLM select and
> expand the best sections. The `/search` API and the EE Search page reuse it.

**Verified against:** `a4e97fcea1` (2026-10-29)
**Edition:** CE. EE adds post-query chunk censoring and the Search page.

---

## User experience

- **A chat user** asks a question and the assistant decides to search. The UI
  shows the queries that ran, which can differ from what the user typed. It then
  shows document cards and a streamed answer with numbered citations that open
  those documents.
- When the question names a source ("in Zendesk") or a time ("last quarter"),
  the search narrows to it and the UI shows a filter note. An admin can turn
  this detection off in the chat preferences; the search then uses only the
  filters that were picked. Filters the user picks in chat apply as an outer
  limit. A user who deselects every source gets
  an empty result, not an unfiltered one.
- A user who asks for a document set they cannot see gets an
  insufficient-permissions error, not a silent fallback.
- **An API caller** sends `POST /search` and gets the selected, expanded
  sections with no LLM answer. It is for programmatic callers such as the
  onyx-cli and the Craft sandbox.
- **An EE user** on the Search page gets ranked documents and the LLM's picks.
  If selection fails, the page still shows the documents.
- When no connector, federated connector or user file exists, or the vector DB
  is off, the model is not offered the tool.

---

## Scope

This component owns `SearchTool`, the retrieval pipeline that turns filters
into one index query per lane, the secondary LLM flows for query expansion,
source and time scope, selection and relevance, the `/search` API, the admin
document search, and the EE Search page backend.

Its neighbours own:
- [[document-index]]: the index queries (`hybrid_retrieval`,
  `keyword_retrieval`, `id_based_retrieval`) and how `IndexFilters` compiles.
- [[access-control]]: how the ACL and the cc-pair access filter are built,
  and what EE censoring removes.
- [[federated-search]]: the Slack lane's token and gate rules, and the
  federated registry.
- [[citations]]: numbering and the document JSON format.
- [[tools-framework]]: tool construction, call merging and citation ranges.
- [[projects]]: which project and agent files go inline and which go through
  this search.

---

## Architecture

```
SearchTool.run
  one DB session: ACL filters, document-set check, search settings,
  federated registry, Slack token prefetch            no DB use after this
  -> _expand_queries_and_decide_scope (parallel)
       semantic_query_rephrase, keyword_query_expansion   query_expansion.py
       decide_search_scope                                source_filter.py
       decide_time_filter                                 time_filter.py
  -> lanes in parallel, one per deduplicated query:
       _run_search_for_query -> search_pipeline -> search_chunks
       + at most one _run_slack_search lane              [[federated-search]]
  -> weighted_reciprocal_rank_fusion -> merge_individual_chunks (num_hits cap)
  -> _trim_sections_by_tokens -> select_sections_for_expansion (one LLM call)
  -> expand_section_with_context per section (parallel)
  -> merge_overlapping_sections -> convert_inference_sections_to_llm_string
```

The module docstring of `SearchTool` gives the authors' five-step design. Read
it first.

**Prefetch, then parallel work.** `run` reads everything it needs from the
database in one short session. The lane workers use plain objects. This keeps
parallel lanes from holding connections. Do not pass an ORM object or a session
into a lane. `PersonaSearchInfo`
(`context/search/models.py`) is the detached snapshot of the agent's document
sets, start date, attached documents and hierarchy nodes. Chat builds it in
`db/tools.py:capture_persona_tool_configuration`, and the `/search` API builds
its own.

**Lanes and weights.** The rephrased semantic query, the model's own queries,
the user's original message and the keyword queries each get a lane and an RRF
weight (`tools/tool_implementations/search/constants.py`). Keyword lanes use a
low `hybrid_alpha`. A `hybrid_alpha` of exactly 0 skips embedding and runs pure
keyword retrieval in `context/search/retrieval/search_runner.py:search_chunks`.

**Filters live in the index query.** For index lanes, source, document set,
time, ACL, cc-pair access and project or agent scope compile into one
`IndexFilters` in `context/search/pipeline.py:_build_index_filters`. Nothing
filters results afterwards except EE censoring
(`backend/onyx/access/access.py:censor_chunks_for_user`). The
Slack lane gets none of these filters.

**No reranker.** The LLM selection step replaces a cross-encoder. One LLM call
sees all candidate sections together, so it can compare across documents.
`RerankingModel` exists in `natural_language_processing/search_nlp_models.py`,
but only the unused `warm_up_cross_encoder` builds one.

**Two model clients.** Query expansion, scope and time decisions, and Slack
query processing use the agent's primary model. Selection and relevance
classification use `selection_llm`, which resolves lazily from the
SEARCH_SELECTION default after retrieval returns sections. If that fails or
is unset, it uses the primary model and checks the primary provider's cost
limit first (`SearchTool._check_primary_llm_cost`). The Slack lane makes the
same check, and a failure skips only that lane. When a separate selection
model is in use, `secondary_llm_flows/search_prompt_budget.py` trims candidates
until the prompt fits that model's limits ([[llm-providers]]).

**Scope within a turn.** The workspace setting `auto_detect_search_filters`
gates both the scope and the time decision. Chat and the `/search` API read it
and pass it to `SearchTool` as `auto_detect_filters`. Each call appends a
`SearchCycle`. The next call's
scope decision reads those cycles, so a "check A, then B" request advances to
the next unsearched source. `_build_scope_note` tells the model which sources
and queries ran. After the first search in a turn, `chat/llm_loop.py` sets
`skip_search_query_expansion`, which `tools/tool_runner.py` passes as
`SearchToolOverrideKwargs.skip_query_expansion`. A repeat search then makes no
rephrase or keyword-expansion LLM call and uses the model's own queries. The
one exception: when the call advances to a source not yet searched, it reuses
the turn's cached expansion (`_cached_expansion`). Selection and expansion run
whatever the flag's value. A change to this flag changes the LLM cost of every
multi-search turn.

**Other entry points.** `server/features/search/api.py` builds a `SearchTool`
with a `NullEmitter` and runs it outside the chat loop. `ee/onyx/search/process_search_query.py`
calls `search_pipeline` directly, with its own expansion and section target,
and is the only caller of `FORCED_DOCUMENT_SET_NAMES` scope
(`context/search/forced_document_set.py`). `backend/onyx/server/query_and_chat/query_backend.py:admin_search`
calls the index directly for admin document inspection.

---

## Contracts and traps

1. `access-from-user-only` **Document access depends only on the `user` passed
   to `SearchTool`.** `tools/tool_implementations/search/search_tool.py:SearchTool.run` always calls
   `context/search/preprocessing/access_filters.py:build_access_filters_for_user`. No
   flag skips it. A caller that needs a narrower scope passes a narrower user.
   The Slack bot passes the anonymous user for replies that are not a DM or
   ephemeral (`onyxbot/slack/handlers/handle_regular_answer.py`). Do not add a
   skip flag ([[access-control]], [[slack-bot]]).
2. `document-set-access-checks` **Three document-set access checks exist.** Each
   calls `backend/onyx/db/document_set.py:filter_document_set_names_by_user_access` on
   user-supplied names, and
   each skips anonymous users. `chat/process_message.py:_stream_chat_turn`
   rejects a chat turn before it starts. A code comment marks it for removal,
   because `SearchTool.run` makes the same check for every caller of the tool.
   Without it, the chat error comes from the tool call, not from setup.
   `SearchTool` calls `search_pipeline` with prefetched ACL filters and no
   `db_session`, so the check in `context/search/pipeline.py:_build_index_filters`
   does not run on that
   path. It covers callers that pass a session, such as the EE Search page. Keep
   the last two. Removing either lets a user replace the agent's document sets
   with any name.
3. `slack-lane-unfiltered` **The Slack lane gets none of the index filters.**
   `tools/tool_implementations/search/search_tool.py:SearchTool._run_slack_search` gets no `effective_filters`, so time,
   document-set and agent filters do not limit Slack results. The token decides
   what comes back ([[federated-search#slack-results-have-no-acl]]).
4. `llm-and-rich-responses-differ` **`llm_facing_response` and `rich_response`
   serve different readers.** The model reads the trimmed, cited string.
   `SearchDocsResponse.search_docs` holds every top section before selection.
   `displayed_docs` holds only the selected ones; `None` means all, and an empty
   list means none. Do not feed rich fields back into the prompt.
5. `empty-source-list-searches-nothing` **An empty source list means "search
   nothing".** `tools/tool_implementations/search/search_tool.py:SearchTool.run` returns an empty response when
   `user_selected_filters.source_type == []`, outside project-only search.
   `None` means no source filter. Do not normalize one into the other.
6. `start-date-is-a-floor` **The agent's `search_start_date` is a floor.**
   `context/search/pipeline.py:_build_index_filters` takes the later of it and any caller start date. An
   inferred time window (`context/search/models.py:TimeFilter.apply_to`) can
   only narrow a selected range. When the inferred window does not overlap the
   selected range, it is dropped and the selected range applies unchanged. Do
   not change this to an empty result.
7. `scope-and-time-cache-differently` **Scope and time decisions cache
   differently.** In
   `tools/tool_implementations/search/search_tool.py:SearchTool._expand_queries_and_decide_scope`,
   the time decision runs once per turn (`_time_filter_computed`). The scope decision latches only when it finds no
   source directive (`_scope_decision_settled`). A source list makes the next
   call decide again.
8. `weights-parallel-to-lanes` **Keep `search_weights` parallel to
   `search_functions`.** A new lane must append to both lists in the same order.
   `tools/tool_implementations/search/search_utils.py:weighted_reciprocal_rank_fusion`
   pairs them by position. A missing weight raises, and a weight in the wrong
   position gives that weight to another lane.
9. `ranking-changes-need-eval` **Lane weights, prompts and RRF need an eval, not
   only a unit test.** A weight change alters which documents reach selection.
   Prompts in `secondary_llm_flows/` change quality silently. The load-test
   mock (`tools/loadtest/mock_llm/search_workload.py:helper_kind`) recognizes
   the selection, classification, scope and time prompts by their first words,
   and the expansion prompts by phrases in their system prompts. A change to
   those words breaks the mock; `tools/loadtest/tests/test_mock_llm.py` checks
   it.
10. `inferred-scope-keeps-user-files` **Inferred scope keeps user files.** When
    project or agent files need retrieval, an inferred source scope adds
    `USER_FILE` unless the user's own filter excludes it
    (`tools/tool_implementations/search/search_tool.py:SearchTool.run`). Project-only searches
    ignore user filters.

---

## Known issues

- **Chat history keeps the model's original query arguments.** The UI shows
  the expanded queries from `SearchToolQueriesDelta`, but the saved tool call
  keeps what the model wrote.
- **Context expansion never drops a selected section.** A `NOT_RELEVANT`
  classification makes `expand_section_with_context` return `None`, and
  `expand_section_safe` then keeps the original section.
- **The EE Search page has no automatic scope or time detection.** It also
  returns no Slack results ([[federated-search]]).

---

## Dependencies

- [[document-index]]: runs the queries this component builds.
- [[access-control]]: builds the ACL that every index lane uses.
- [[federated-search]]: supplies the Slack lane rules and the registry.
- [[tools-framework]]: constructs `SearchTool`, merges repeated calls in one
  batch, and gives each call a citation range.
- [[llm-providers]]: resolves the SEARCH_SELECTION default.
- [[projects]]: decides when project and agent files go through search.
- [[observability]]: the `/search` API opens its own trace and tool span,
  because it does not pass through the chat loop.

---

## Recipes

- `new-filter-field` **Add a filter field.** Copy how `document_set` flows: add the field to
  `BaseFilters` and `IndexFilters` (`context/search/models.py`), compile it in
  `_build_index_filters`. List the current fields with
  `git grep -n "class BaseFilters" -A30 backend/onyx/context/search/models.py`.
  Decide whether the Slack lane should honour it ([[#slack-lane-unfiltered]]).
- `new-lane` **Add a lane.** Copy the keyword lane in `SearchTool.run`: append to
  `search_functions` and `search_weights` together
  ([[#weights-parallel-to-lanes]]), add its weight to
  `tools/tool_implementations/search/constants.py`, and run a retrieval eval.
- `document-not-found` **Investigate "search did not find my document".** Ask the same question and
  read the filter note: a source or time scope the model inferred can exclude
  the document. Then search for it in the admin document search. It runs one
  keyword query with the admin's ACL, no LLM step, and shows hidden documents. If it shows there, the cause is scope, selection or the user's
  ACL ([[access-control]]). If not, check that its pair indexed it
  ([[cc-pairs-and-creds]]).

---

## Verification

- Unit tests: `backend/tests/unit/onyx/tools/tool_implementations/search/` and
  the search tool tests in `backend/tests/unit/onyx/tools/`.
- Integration: `backend/tests/integration/tests/search/`.
- Load-test mock: `tools/loadtest/tests/` checks that the mock still
  recognizes the search prompts.
- By hand, ask a question that forces a search. Then ask for one source by
  name. The filter note must show that source, and no document from another
  source may appear.
