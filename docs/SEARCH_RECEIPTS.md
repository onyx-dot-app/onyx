# Search receipts (experimental)

Search receipts append a small block of retrieval metadata to each internal search
result before the chat model reads it. The model then sees which queries the search
ran, how many distinct documents each query returned, how many were new versus already
seen in the current turn, and the filters that applied. The feature is on by default and
can be turned off per tenant or user with a PostHog flag.

## Enable

Search receipts are on by default. They are controlled by the PostHog feature flag
`onyx-search-receipts`, evaluated once per chat message for the requesting user and
tenant through the standard `FeatureFlagProvider`.

- Flag not defined in PostHog, PostHog not configured (Community Edition), or an
  evaluation error: receipts stay on. The flag can only override the default.
- Flag defined and evaluating to false for the user: receipts are off for that message.
- Partial rollouts work as usual: users outside the rollout get false.

The main chat loop (`onyx.chat.llm_loop.run_llm_loop`) receives the result through its
`enable_search_receipts` argument. Other loops and callers do not request receipts.

When receipts are off, the search tool collects no receipt diagnostics and the model
sees the original search result string unchanged.

## What the model sees

The receipt is appended after the full, unchanged search result. This is a real
receipt from a dev-stack turn against three ingested test documents, where the model
asked for the Zephyr launch lead and date. The search tool ran seven lanes: the raw
user question, the rephrased semantic query, the three model-written queries, and two
keyword lanes at alpha 0.2. All three documents came back in every lane, and the model
cited one of them. The JSON is pretty-printed here for readability; the emitted and
persisted receipt is one compact line (`json.dumps` with no indent).

```text
{"results": [{"document": 1, "title": "Onyx Receipt Test: Zephyr Launch Plan", ...}]}

SEARCH RECEIPT (retrieval metadata, not source evidence):
{
  "executed_queries": [
    {
      "query": "Who is the launch lead for the Zephyr project and when does it launch?",
      "hybrid_alpha": null,
      "returned_documents": 3,
      "new_documents_this_task": 3
    },
    {
      "query": "Zephyr project launch lead internal document",
      "hybrid_alpha": null,
      "returned_documents": 3,
      "new_documents_this_task": 3
    },
    {
      "query": "Zephyr project launch date internal document",
      "hybrid_alpha": null,
      "returned_documents": 3,
      "new_documents_this_task": 3
    },
    {
      "query": "Zephyr project launch lead and launch date Zephyr internal",
      "hybrid_alpha": null,
      "returned_documents": 3,
      "new_documents_this_task": 3
    },
    {
      "query": "Who is the launch lead for the Zephyr project and when does it launch? Use internal documents.",
      "hybrid_alpha": null,
      "returned_documents": 3,
      "new_documents_this_task": 3
    },
    {
      "query": "Zephyr launch lead",
      "hybrid_alpha": 0.2,
      "returned_documents": 3,
      "new_documents_this_task": 3
    },
    {
      "query": "Zephyr launch date",
      "hybrid_alpha": 0.2,
      "returned_documents": 3,
      "new_documents_this_task": 3
    }
  ],
  "retrieved_documents": 3,
  "new_candidate_documents": 3,
  "repeated_candidate_documents": 0,
  "after_merge_cap": 3,
  "returned_evidence_documents": 1,
  "scope": {
    "user_filters": null,
    "persona_document_sets": [],
    "acl_enforced": true
  },
  "coverage": "Ranked, capped retrieval; not an exhaustive corpus scan.",
  "interpretation": "Overlap is not answer confidence. Repeated or empty results do not prove the information is absent. Use observed queries and missing facts to choose a complementary follow-up when needed."
}
```

Field meanings:

| Field | Meaning |
|---|---|
| `executed_queries` | Every retrieval lane that ran, in execution order. Lanes are not deduplicated: the same text can run with a different `hybrid_alpha`. |
| `returned_documents` | Distinct documents returned by that lane, before rank fusion. |
| `new_documents_this_task` | Lane documents not seen by an earlier search in this user turn. Two lanes of the same search can both count a document as new. |
| `retrieved_documents` | Distinct documents across all lanes of this search. |
| `new_candidate_documents` / `repeated_candidate_documents` | Split of `retrieved_documents` against documents seen by earlier searches in this turn. |
| `after_merge_cap` | Distinct documents left after fusion, adjacent-chunk merge and the result cap, before the model selects sections. |
| `returned_evidence_documents` | Distinct documents in the final citation mapping of this response. UI cards are not counted. |
| `scope` | User-selected filters, persona document sets and whether ACLs were enforced. |

All counts are distinct documents, never chunks. The receipt is computed once per
search response, in the order the loop processes responses. An earlier sibling in the
same parallel batch counts as already seen. The seen set lives inside one
`run_llm_loop` call, so it resets on the next user turn.

## Scope gating

The `scope` object can only express three facts. When retrieval was narrowed by
something else, the receipt is not appended and the loop logs
`search_receipt_unavailable reason=unrepresentable_scope`. Gated paths:

- auto-detected source scope or time window (`auto_detect_filters`)
- federated sources, including the Slack lane
- project scope (`project_id_filter`) or `persona_id_filter`
- persona `search_start_date`, attached documents or hierarchy nodes

Search results on those paths are unchanged, but their candidate documents still count
as seen for later receipts in the same turn. This is a deliberate limitation: a receipt
must not claim a scope it does not fully describe. The evaluated experiment ran with
none of these active (`user_filters: null`, `persona_document_sets: []`,
`acl_enforced: true`).

A search that ran but returned nothing produces a receipt with honest zeros. A response
that carries no diagnostics at all is left untouched and logged with
`reason=missing_retrieval_diagnostics`.

## Implementation

- `backend/onyx/chat/search_receipts.py` builds and appends the receipt.
- `SearchToolOverrideKwargs.include_retrieval_candidates` asks the search tool to
  record lanes and post-cap ids into `SearchDocsResponse.retrieval_diagnostics`.
  `run_tool_calls` sets it from `include_search_retrieval_candidates`.
- `run_llm_loop` appends the receipt before the response is persisted, added to
  history or token counted. The augmented string is what the context budget counts.

Nothing else changes: query expansion, fusion, selection, expansion, citations,
prompts, tool schema, tool scheduling and loop limits are as before. No extra model or
retrieval call is made.

## Measured results

A paired experiment ran the same 107 benchmark questions in each arm, 214 attempts
total, on the native v1 loop and native `SearchTool` with GPT-5.6-Luna and explicit
provider reasoning `none`. The experiment harness, not this flag, requested retrieval
diagnostics in both arms so that the only difference the model saw was the receipt
text; the control arm never exposed the receipt. In production the flag-off path collects
no diagnostics at all. Setup: persona-less single-turn internal search, no memory, no
files, no user-selected filters, automatic search filters disabled.

| Metric | Native v1 | Native v1 + receipts |
|---|---:|---:|
| Correct answers | 77/107 | 82/107 |
| Correctness | 71.96% | 76.64% |
| Mean completeness | 67.58% | 68.61% |
| Combined score | 61.41% | 66.33% |
| Median native loop latency | 14.64 s | 14.72 s |
| Median complete worker latency | 31.40 s | 31.67 s |
| Total searches | 119 | 120 |
| Questions with follow-up searches | 11 | 13 |
| Estimated answering/search model cost, all 107 | $0.6818 + 2 unpriced calls | $0.7652 |

Combined is `mean(100 * correctness_i * completeness_fraction_i)`, not the product of
the aggregate correctness and completeness.

How to read this:

- Combined improved by 4.92 points. The paired bootstrap 95% interval is
  [-0.42, +10.29]. This is promising, not statistically conclusive.
- Nine correctness recoveries and four regressions. One recovery was a control
  600-second timeout. Excluding that question (`qst_0481`) from both arms gives
  61.99 versus 66.02 over 106 pairs, a +4.03 point difference.
- The lower treatment mean latency is not a speedup. The control timeout dominates it.
- Observed model cost rose about 12.2%, subject to two unpriced control calls. Cache
  usage differed between arms; with no cache discount the estimate is about +4.8%.
  These are usage-based estimates, not invoices, and exclude grading, smoke tests and
  infrastructure.
- The unchanged official grader used GPT-5.4/GPT-5-mini with no correction and zero
  evaluator failures. No agent-level reruns; native retry behavior was kept. All 214
  trace roots exist in Braintrust; 213 flushed, the timeout root did not.
- Most recoveries did not add searches. Better complementary searching is not the
  proven mechanism: first retrieval varies between runs and the receipt also changes
  the context the answer is written from. Semantic correctness moved only 10/25 to
  11/25.

Keep the feature experimental until a broader evaluation confirms the effect.
