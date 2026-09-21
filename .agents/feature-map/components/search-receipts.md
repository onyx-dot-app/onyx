# Search Receipts

> A block of retrieval metadata appended to an `internal_search` tool response, so a
> later turn in the same conversation knows what was already searched and does not
> repeat itself. Experimental, on by default, receipt-only: no new model call, no new
> tool, no change to the search pipeline itself.

**Domain:** search
**Edition:** CE, gated by a PostHog flag that only Enterprise Edition can define
**Owns:**
`backend/onyx/chat/search_receipts.py`

**Read first:** `docs/SEARCH_RECEIPTS.md`. It is the design rationale and includes a
worked example of the receipt JSON. This document maps it to code and adds
verification guidance.

---

## 1. What the user experiences

Almost nothing directly. The receipt is appended to the LLM-facing string the model
reads, not to anything rendered in the UI (`rich_response` and the source cards are
unchanged, see [[internal-search]] §5.3). The only user-visible effect is indirect: in
a long conversation, the model is less likely to re-run a search it already ran,
because it can see which queries executed and which documents it already has. There
is no setting exposed to the end user; an admin only sees this if they inspect a
PostHog flag.

---

## 2. Surfaces

There is no HTTP endpoint, UI element, or LLM-visible tool schema change. The only
surface is a feature flag and a loop parameter.

| Surface | Value | Effect |
|---|---|---|
| PostHog flag `onyx-search-receipts` (`search_receipts.py:SEARCH_RECEIPTS_FLAG`) | `default=True` | Evaluated once per chat message via `search_receipts_enabled` (`search_receipts.py:search_receipts_enabled`). Can only turn receipts off; an undefined flag or no PostHog (Community Edition) always resolves to on. |
| `run_llm_loop(..., enable_search_receipts: bool = False)` (`llm_loop.py:run_llm_loop`) | set from `search_receipts_enabled(user)` in `process_message.py` | The only loop that requests receipts. Other callers of `run_llm_loop`, and the deep research loop, never set this to `True`. |

---

## 3. Data model

No tables. The only state is a `set[str]` of document IDs, `seen_search_document_ids`,
created fresh per model per turn in `llm_loop.py:run_llm_loop` (`llm_loop.py:916`) and
passed by reference into `maybe_append_search_receipt`. It is mutated in place:
`build_search_receipt` (`search_receipts.py:build_search_receipt`) reads it to compute
`new_documents_this_task` and `new_candidate_documents`, then updates it with the
current search's candidates before returning. Because it is mutable and shared across
every `internal_search` call in one loop invocation, an earlier sibling in the same
parallel tool-call batch counts as already seen by a later one, and a scope-gated
search (§5) still updates the set even though it produces no receipt
(`search_receipts.py:maybe_append_search_receipt`). The set does not survive past one
`run_llm_loop` call, so it resets on the next user turn.

---

## 4. How it works

```
process_message.py: search_receipts = False if deep_research else search_receipts_enabled(user)
  └─ run_llm_loop(..., enable_search_receipts=search_receipts)          llm_loop.py
       ├─ run_tool_calls(..., include_search_retrieval_candidates=enable_search_receipts)
       │     └─ SearchTool.run(): override_kwargs.include_retrieval_candidates       search_tool.py
       │           ├─ _build_retrieval_candidate_lanes(...)                          search_tool.py
       │           └─ _build_receipt_scope(...) -> SearchReceiptScope | None         search_tool.py
       │                 -> SearchDocsResponse.retrieval_diagnostics                 context/search/models.py
       └─ for each tool_response, if enable_search_receipts and tool is SearchTool:
             maybe_append_search_receipt(tool_response, seen_search_document_ids)    search_receipts.py
                 ├─ no-op + _log_unavailable(...) if diagnostics or scope missing
                 └─ else: append_search_receipt -> build_search_receipt -> mutates tool_response.llm_facing_response
```

1. `process_message.py` evaluates the flag once per message
   (`process_message.py:1209`) and skips it entirely for deep research
   (`deep_research = n_models == 1 and setup.new_msg_req.deep_research`), which never
   requests receipts.
2. The flag flows into `run_llm_loop` as `enable_search_receipts`
   (`process_message.py:1433`), which flows into `run_tool_calls` as
   `include_search_retrieval_candidates` (`llm_loop.py:1216`).
3. Inside `SearchTool.run`, that becomes `override_kwargs.include_retrieval_candidates`
   (`tools/models.py:SearchToolOverrideKwargs.include_retrieval_candidates`). Only when
   set does the tool build a `SearchRetrievalDiagnostics`
   (`search_tool.py:1146-1160`): the executed lanes
   (`search_tool.py:_build_retrieval_candidate_lanes`), the post-fusion/merge/cap
   document ids, and the scope, or `None` if the scope cannot be summarised honestly
   (`search_tool.py:_build_receipt_scope`).
4. Back in `run_llm_loop`, once every tool response is in hand and before it is
   persisted or added to history, `maybe_append_search_receipt` runs per search tool
   response in sequential order (`llm_loop.py:1267`). It no-ops with a logged reason
   when the response is not a `SearchDocsResponse`, when `retrieval_diagnostics` is
   `None`, or when `receipt_scope` is `None` (`search_receipts.py:_log_unavailable`).
5. Otherwise `append_search_receipt` builds the receipt and appends
   `RECEIPT_PREFIX` plus compact JSON to `tool_response.llm_facing_response`
   (`search_receipts.py:append_search_receipt`). This mutated string is what gets
   persisted, added to history, and counted against the context budget.

---

## 5. Contracts and invariants

1. **A receipt must never claim a scope it cannot honestly summarise.**
   `_build_receipt_scope` returns `None`, not an approximation, whenever any
   condition in §7's gating list holds. This is why `maybe_append_search_receipt`
   checks `diagnostics.receipt_scope is None` and refuses to append rather than
   guessing (`search_receipts.py:maybe_append_search_receipt`).
2. **The receipt is metadata, not evidence.** The exact prefix
   `"\n\nSEARCH RECEIPT (retrieval metadata, not source evidence):\n"`
   (`search_receipts.py:RECEIPT_PREFIX`) says so explicitly so the model does not cite
   the receipt block as a source. Changing the prefix text risks the model treating
   receipt content as citable.
3. **The receipt never touches `rich_response` or anything the UI reads.** Only
   `tool_response.llm_facing_response` is mutated
   (`search_receipts.py:append_search_receipt`). `SearchDocsResponse.search_docs`,
   `displayed_docs`, and `citation_mapping` are read, never written.
4. **`seen_document_ids` mutation happens even when no receipt is produced.** A
   scope-gated search still adds its candidates to the set
   (`search_receipts.py:maybe_append_search_receipt`, the `unrepresentable_scope`
   branch) so a later receipt in the same turn does not misreport those documents as
   new.
5. **Diagnostics are only computed when requested.** With the flag off,
   `override_kwargs.include_retrieval_candidates` is `False` and `SearchTool.run`
   never builds a `SearchRetrievalDiagnostics` at all (`search_tool.py:1147`); the
   flag-off path costs nothing beyond the boolean check.
6. **Adding a retrieval lane or a new filter requires deciding whether scope is still
   summarisable.** `_build_receipt_scope` enumerates the narrowing conditions
   explicitly; a new lane or filter that is not listed there will silently produce
   a receipt that overclaims scope.

---

## 6. Relationships

**Depends on**
- [[internal-search]]: `SearchTool._build_retrieval_candidate_lanes` and
  `_build_receipt_scope` live in and are owned by that component; this document
  covers only the receipt-building and appending step downstream of them.
- [[core-chat-loop]]: `run_llm_loop` is the only caller that ever sets
  `enable_search_receipts=True`; the hook point in the loop's tool-response
  processing (`llm_loop.py:1267`) is what makes this possible.
- [[editions-and-gating]]: the PostHog flag evaluation goes through
  `get_default_feature_flag_provider()`; Community Edition's `NoOpFeatureFlagProvider`
  cannot define the flag, so it always evaluates to the `default=True`.

**Depended on by**
- Nothing in the codebase reads the receipt back out. It exists purely for the LLM
  to read in a later turn of the same conversation, inside the same context window.

---

## 7. Blast radius

| If your change... | Also check |
|---|---|
| adds a retrieval lane or a new filter to [[internal-search]] | whether `_build_receipt_scope` must now return `None` for that condition; an unlisted narrowing filter makes the receipt overclaim scope |
| changes the LLM-facing string format (`RECEIPT_PREFIX`, the JSON schema, key order) | `docs/SEARCH_RECEIPTS.md`'s worked example goes stale; the schema is described there as "the evaluated one" and must not drift without a new evaluation |
| changes the flag (`SEARCH_RECEIPTS_FLAG`, its default) | `backend/tests/unit/onyx/chat/test_search_receipts_flag.py`; the default-on behavior is deliberate and documented in `docs/SEARCH_RECEIPTS.md` |
| changes `run_llm_loop`'s tool-response processing order | the "earlier sibling in the same batch counts as seen" guarantee, which depends on receipts being built in the order responses are enumerated |

---

## 8. How to verify a change

### Tests

```bash
cd backend && uv run pytest tests/unit/onyx/chat/test_search_receipts.py
cd backend && uv run pytest tests/unit/onyx/chat/test_search_receipts_flag.py
```

No integration or playwright test targets this component specifically as of this
writing.

### Manual reproduction

1. Confirm services are up: `tail -f backend/log/api_server_debug.log`.
2. Open `http://localhost:3000`, sign in as `admin_user@example.com` /
   `TestPassword123!`.
3. Send a message that forces a search, then a follow-up in the same session that
   would plausibly repeat it (for example, ask the same question a different way).
4. Grep `backend/log/api_server_debug.log` for `search_receipt_unavailable` to see
   whether a receipt was skipped and why (`reason=...`).
5. To see the raw receipt, enable `INTEGRATION_TESTS_MODE` or inspect the persisted
   `llm_facing_response` for the tool call; it is not rendered in the UI.

### What "working" looks like

- With the flag on and no scope-gating condition active, every `internal_search`
  tool response has a `SEARCH RECEIPT` block appended to its LLM-facing string.
- With the flag off, `SearchDocsResponse.retrieval_diagnostics` is `None` and no
  receipt appears.
- `rich_response` and the UI are byte-identical whether the flag is on or off.

---

## 9. Footguns

- **The flag is default-on and can only disable, never enable, beyond that
  default.** An undefined flag, or Community Edition with no PostHog configured,
  always resolves to on. Do not assume "no flag defined" means "off."
- **Absence of a receipt is usually correct, not a bug.** `_build_receipt_scope`
  returns `None` under many common conditions: an auto-detected source or time
  filter, any federated retrieval (including the Slack lane), a project or persona
  filter, a persona `search_start_date`, or attached documents/hierarchy nodes. A
  real-world search with any of these active will never carry a receipt, by design.
- **Deep research never gets receipts.** `process_message.py` hardcodes
  `search_receipts = False` for that path; the flag is never even evaluated.
- **The prefix text is load-bearing.** It exists specifically so the model does not
  treat the receipt as a citable source. Changing the wording without re-running the
  evaluation in `docs/SEARCH_RECEIPTS.md` risks a model that starts citing retrieval
  metadata as if it were a document.
- **Feature is explicitly experimental.** `docs/SEARCH_RECEIPTS.md` reports a
  promising but not statistically conclusive result (95% CI crosses zero) and asks
  that the feature stay experimental until a broader evaluation confirms the effect.
- **Later measurement did not reproduce the gain.** A follow-up run against the
  chat API measured no improvement (point estimate around -0.58, confidence
  interval crossing zero) and about one second of added median latency. The
  original +2.19 result never cleared significance. This finding is not
  derivable from the repository; it comes from the team's benchmark runs. Treat
  the feature as unproven, and re-measure before you build on it or remove it.

---

Cross-links: [[internal-search]], [[core-chat-loop]], [[context-assembly]],
[[tools-framework]], [[editions-and-gating]]
