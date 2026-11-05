# Withheld Sources

> Sources that Onyx indexes but keeps out of ordinary search, because the
> provider decides who may read each document and the answer can change after
> indexing. A lane of its own retrieves them and clears every chunk with the
> provider before any of it reaches a user.

**Verified against:** `62e32bb706` (2026-10-31)
**Edition:** CE

---

## User experience

- **An admin** sets a withheld source up like any other connector. Nothing in
  the admin UI marks it as withheld; the connector's own subtext has to say
  so.
- **A user** never sees its documents in a plain search of team knowledge. They
  appear as extra results alongside the indexed ones, and only those the
  provider says that user may read. The user cannot tell a withheld result from
  an indexed one.
- **An anonymous caller** gets none: the provider answers about a named user,
  and there is nobody to name.
- **When it fails**, the user sees no error and no results from that source.
  A provider that cannot be reached proves nothing, so the lane returns
  nothing rather than everything.

---

## Scope

This component owns which sources are withheld, the exclusion that keeps them
out of the default retrieval lane, the lane that serves them, and the contract
a per-source permission filter follows. No source uses it yet; the first will
be a connector whose provider owns read access ([[connectors]]).

Its neighbours own:
- [[internal-search]]: `SearchTool`, the lane fan-out, rank fusion, selection
  and expansion. The withheld lane is one more entry in that fan-out.
- [[federated-search]]: live search of a source's own API, with no indexing.
  A withheld source is the opposite: indexed as usual, filtered at read time.
- [[connectors]] and [[indexing-pipeline]]: how the documents got there.
- [[access-control]]: the index ACL, which still applies. The provider's
  answer narrows it; it never replaces it.

---

## Architecture

```
search_chunks  (context/search/retrieval/search_runner.py)
  -> enrichment_source_types()        from the registry, no DB call
  -> default lane: filters.excluded_source_type = those sources
  -> one lane per EnrichmentContext:
       same filters, source_type = [the source], excluded_source_type = None
       -> _retrieve                  keyword-only when the caller asked for it
       -> permission_filter(user_email, chunks, secrets)
  -> combine_retrieval_results
```

**Two halves, deliberately split.** `onyx/context/search/enrichment/registry.py` reads a source's
permission filter from the event source store and needs no database; `onyx/context/search/enrichment/retrieval.py:get_enrichment_contexts`
resolves which of them are live and with whose credentials, which does. The
chat path resolves ahead of time in `SearchTool.search` and hands the result
down, as it already does for federated search, because the lanes then run in
threads with no session. The Search UI path has a session and resolves inside
`search_chunks`.

**The exclusion is unconditional.** It is read from the registry unioned with
`configs/constants.py:WITHHELD_FROM_DEFAULT_SEARCH`, never from the resolved
contexts. So a source stays out of the default lane when nothing resolved its
credentials, and also when its implementation failed to import or is not
installed at all -- the loader swallows a failed import by design, and
documents an earlier run indexed are still in the index. A user then sees no
results from it, which is the safe half of the failure.

**The provider's answer is per search, not per index.** The permission filter
receives the retrieved chunks and returns the subset the user may read. A
search expands into several queries and each one runs the lane, so
`EnrichmentContext` remembers the verdict per document id and the provider is
asked once per search for each document. The lanes run in parallel threads and
share the context, so the memo is locked.

---

## Contracts and traps

1. `exclusion-covers-only-the-search-lane` **The exclusion is applied in
   `search_chunks`, so retrieval paths that do not go through it are not
   covered.** The documents are indexed with the pair's ordinary access type,
   so a path that reads the index directly returns them to anyone the index
   ACL allows. Known readers: context expansion
   (`tools/tool_implementations/search/search_utils.py` fetches the chunks
   above and below a cited one), the Open URL tool, the document chunk-info
   routes (`server/documents/document.py`) and the tabular rechunk job.
   Moving the clause into `_get_search_filters` as a default-deny would cover
   all of them at once, but context expansion legitimately needs withheld
   chunks, so each reader needs its own answer first. Treat a new retrieval
   entry point as a data-exposure review ([[access-control]]).

2. `provider-latency-is-search-latency` **The permission call sits inside a
   retrieval lane, and `run_functions_tuples_in_parallel` waits for every
   lane with no timeout.** A slow provider therefore slows every search for
   that tenant, and a hung one would hold it for the client's whole timeout.
   A filter must use a budget measured in seconds, separate from whatever the
   connector's ingest path allows: a download timeout fit for a background
   worker would let a hung provider hold every search.

3. `filter-failure-returns-nothing` **A permission filter that raises drops its
   whole lane for the rest of the search, and the search succeeds without it.**
   `EnrichmentContext.allowed` catches, logs, and stops asking: the usual
   reason a provider breaks is a rate limit, and asking once per expanded
   query is what reaches one. Returning the chunks would publish content
   nobody cleared, and raising would fail a search because one provider is
   down. A filter must therefore raise rather than return its input when it
   cannot reach the provider.

4. `verdict-is-per-document` **A permission filter's verdict must depend on the
   document, not on the chunk.** `EnrichmentContext` keys its memo on
   `document_id`, so a filter that would clear one chunk of a document and
   refuse another gives whichever answer it returned first, for all of them.
   A source whose permissions are finer than a document cannot use this lane.

5. `chunk-metadata-is-the-only-handle` **A chunk the filter cannot identify is
   dropped, not returned.** The filter reads the provider's identifiers out of
   `InferenceChunk.metadata`, which comes from the document the connector built.
   Renaming a metadata key orphans every document already indexed: they keep the
   old key, so the filter can no longer ask about them and they stop appearing.
   Re-index after such a rename.

6. `access-filters-are-kept` **The withheld lane keeps the caller's
   `access_control_list` and `cc_pair_access`.** It replaces only
   `source_type` and clears `excluded_source_type`. The provider decides on top
   of Onyx's ACL, never instead of it.

7. `one-pair-per-source` **The lane reads the first active pair of the source.**
   A second account's credentials are never used, exactly as the event inbox
   resolves a delivery ([[connectors]]). Two pairs of one withheld source is a
   silent misconfiguration.

---

## Decisions

**Why not the federated connector framework.** `FederatedConnector`
([[federated-search]]) searches a provider's own API at query time with a
per-user OAuth token. A withheld source has no search API — its content
arrives by webhook — and no per-user token. The two share the idea of a
parallel lane and nothing else.

**Why not an ACL.** Writing the provider's answer into the index ACL would make
it as old as the last permission sync. The provider can revoke access to a
meeting between the indexing run and the search, and this lane is for the
sources where that matters.

---

## Known issues

- The documents are indexed with the pair's ordinary access type, usually
  public, so the exclusion is the only thing keeping them out of the default
  lane ([[#exclusion-covers-only-the-search-lane]]). Granting them a synthetic
  group that only the withheld lane presents would make the index itself hold
  the restriction. It is not done.

---

## Dependencies

- [[internal-search]]: the lane fan-out this joins, and the fusion that ranks
  its results with the indexed ones.
- [[connectors]]: a withheld source registers alongside its event source, and
  the pair whose credentials the lane reads.
- [[access-control]]: the index ACL the lane keeps.
- [[document-index]]: `excluded_source_type` is a filter clause in the
  OpenSearch query builder.

---

## Recipes

- `new-withheld-source` **A withheld source.** List the withheld ones with
  `git grep -l permission_filter= backend/onyx`.
  1. Write the permission filter: `(user_email, chunks, secrets) -> chunks`.
     Read the provider's identifiers from chunk metadata, ask the provider
     about the distinct resources, and raise if it cannot answer. Give it a
     budget of seconds, not whatever its ingest path allows
     ([[#provider-latency-is-search-latency]]).
  2. Pass it as `permission_filter` to the source's `register_event_source`
     call ([[connectors#new-event-source]]). The loader undoes the whole
     registration if the import then fails.
  3. Make the connector write those identifiers into `Document.metadata`.
     Without them the filter cannot ask ([[#chunk-metadata-is-the-only-handle]]).

## Verification

- `backend/tests/unit/onyx/context/search/test_enrichment_lane.py` drives the
  fan-out with the index stubbed: the exclusion, the scoped lane, and what a
  filter that refuses or breaks does to the results.
