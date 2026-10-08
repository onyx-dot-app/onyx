# Citations

> The thin-looking, long chain that turns a retrieved document into a numbered marker
> the model emits, and turns that marker back into a clickable source in the UI. It
> crosses the prompt, the search tools, the stream parser, the database, and the
> renderer, so it breaks silently at any single point.

**Verified against:** `268e4d5a3d` (2026-10-05)
**Domain:** core-loop
**Edition:** CE
**Owns:**
`backend/onyx/chat/citation_processor.py`, `citation_utils.py`
**Contributes to (owned by neighbours):**
`backend/onyx/chat/agent.py:ChatAgent`, `backend/onyx/chat/models.py`, `backend/onyx/db/chat_response.py` ([[core-chat-loop]]),
`backend/onyx/agents/tool_execution.py:ToolBatch`, `tool_implementations/utils.py` ([[tools-framework]]),
`backend/onyx/chat/prompt_utils.py`, `backend/onyx/prompts/chat_prompts.py`
([[context-assembly]]), `backend/onyx/server/query_and_chat/streaming_models.py`
([[streaming-protocol]]), `backend/onyx/server/query_and_chat/session_loading.py`
([[chat-persistence]]), `web/src/app/app/services/packetUtils.ts`,
`web/src/app/app/message/MemoizedTextComponents.tsx`,
`web/src/app/app/message/messageComponents/markdownUtils.tsx`,
`web/src/app/app/message/messageComponents/MessageToolbar.tsx` ([[chat-frontend]])

**Read first:** `backend/onyx/chat/README.md`, the paragraphs on the `document` JSON key
and on reminder placement (search "citations reliable"). This document maps that
rationale to the code and adds verification guidance.

---

## 1. What the user experiences

When the assistant searches and answers, numbers like `[1]` and `[2]` appear inline in
the streamed text. Each number is hoverable and clickable: hovering shows a small
source card (title, source icon, snippet), and clicking opens the document, either in
a preview or in the documents sidebar. A "Sources" tag in the message toolbar
(`MessageToolbar.tsx:SourcesTagWrapper`) also lists every cited document for the
message as a whole, independent of where in the text it was cited.

A working citation always resolves to a real, currently-displayed document. A broken
one does not show an error or a bare number: the marker resolves to nothing and the
surrounding text simply looks like it never had a citation there
(`MemoizedTextComponents.tsx:MemoizedAnchor`, the `<></>` branch). This is deliberate
during streaming, since the mapping may not have arrived yet, but it means a real bug
in the citation pipeline looks identical to a transient rendering gap: missing
decoration, not a visible failure.

---

## 2. Surfaces

Citations have no HTTP endpoints of their own. They ride the same turn described in
[[core-chat-loop]] and the same packet stream described in [[streaming-protocol]].

| Surface | Where | Notes |
|---|---|---|
| `include_citations` | `SendMessageRequest.include_citations` (`server/query_and_chat/models.py`), default `True` | Per-request switch. `backend/onyx/chat/agent.py:ChatAgent` maps it to `CitationMode.HYPERLINK` (default) or `CitationMode.REMOVE`. Callers that must not expose links to the end surface (for example a public bot) set it `False`. |
| `CitationMode` | `chat/citation_processor.py:CitationMode` | `HYPERLINK` (format and emit `CitationInfo`), `KEEP_MARKERS` (preserve `[1]` verbatim, emit no `CitationInfo`, used by intermediate-report rendering in `backend/onyx/chat/presentation.py`), `REMOVE` (strip markers entirely, emit no `CitationInfo`, driven by `include_citations=False`). All three track mapped citations via `get_seen_citations`. A marker with no mapping is skipped. |
| `CitationInfo` packet | `server/query_and_chat/streaming_models.py:CitationInfo` | The wire-visible surface for ordinary inline citations. Research-agent reports also produce `IntermediateReportCitedDocs` through `backend/onyx/chat/renderer.py:ToolRenderer`. Carries `citation_number` and `document_id`. See [[streaming-protocol]] §4.1. |

---

## 3. Data model

Citations add no tables of their own. They write into columns [[chat-persistence]] owns:

- `ChatMessage.citations` (`db/models.py:ChatMessage`): `dict[int, int]`, citation
  number to `SearchDoc.id` (the DB primary key, not the connector document id).
  `None` when a turn cited nothing.
- `SearchDoc` (`db/models.py:SearchDoc`): one row per unique retrieved document
  version. A citation-only document (for example a project file cited but never
  shown as a tool-call result) still gets a row here, created on demand in
  `backend/onyx/db/chat_response.py:save_chat_turn`. Only project-file rows are also linked to the
  message. Other citation-only rows are not in the message's document list.
- `ChatMessage__SearchDoc` and `ToolCall__SearchDoc` (`db/models.py`): the join
  tables linking a message's full document set, and a specific tool call's result
  set, to `SearchDoc` rows. A citation can point at a `SearchDoc` that is linked to
  the message but to no tool call, if it came from a project file.

No citation state is cached in Redis. The only durable artifact between the live
turn and a later replay is `ChatMessage.citations` itself.

---

## 4. How it works

### 4.1 The full chain

```
retrieval (internal_search / web_search / open_url)          [[internal-search]], [[web-search]]
   │  InferenceSection[] per tool call
   ▼
convert_inference_sections_to_llm_string                     tools/tool_implementations/utils.py
   │  assigns citation numbers starting at starting_citation_num (per-tool-call range)
   │  returns (llm_facing_json_string, citation_mapping: dict[citation_num -> document_id])
   ▼
system prompt + citation reminder                             chat/prompt_utils.py, prompts/chat_prompts.py
   │  teaches the model to emit [1], [2], ... referencing the "document" field
   ▼
model emits answer text containing [1], [2], [1,3], [[4]], ...
   ▼
DynamicCitationProcessor.process_token (streaming, token by token)   chat/citation_processor.py
   │  matches citation_pattern / possible_citation_pattern
   │  looks up citation_to_doc[num] -> SearchDoc
   │  HYPERLINK mode: rewrites "[1]" to "[[1]](link)", yields CitationInfo(num, doc_id)
   ▼
MessageRenderer emits CitationInfo and records displayed citations             chat/renderer.py
   │  ResponsePresenter publishes packets; project_response prepares saved display
   ▼
save_chat_turn                                                 db/chat_response.py
   │  persists ChatMessage.citations = {citation_num: SearchDoc.id}, only for emitted citations
   │  links tool-call SearchDocs and citation-only project-file SearchDocs to the ChatMessage
   ▼
frontend: getCitations(packets) -> CitationMap                 services/packetUtils.ts, app/interfaces.ts
   │  {citation_num: document_id}, deduped by document_id
   ▼
MemoizedAnchor: markdown link "[1]" -> citations[1] -> docs.find(document_id) -> OnyxDocument   MemoizedTextComponents.tsx
   │  resolved -> SourceTag card; unresolved -> renders nothing
   ▼
replay: translate_assistant_message_to_packets reconstructs the same CitationInfo packets
         from ChatMessage.citations, in citation-order-of-first-appearance                     session_loading.py
```

### 4.2 Numbering: `convert_inference_sections_to_llm_string`

`tool_implementations/utils.py:convert_inference_sections_to_llm_string` assigns one
citation number per unique `document_id`, counting up from `citation_start`
(`SearchToolOverrideKwargs.starting_citation_num` / equivalent for web search and
open URL). It returns both the JSON string the model reads and the parallel
`citation_mapping: dict[int, str]` (citation number to document id), which is the
`SearchDocsResponse.citation_mapping` field described in [[internal-search]] §4.7.

Each document entry in the JSON is built as `{"document": citation_id, "title": ...,
..., "content": ..., "metadata": ...}` (`utils.py:convert_inference_sections_to_llm_string`,
the `result = {...}` block). The key is `document`, not `citation_id` or `id`. The
integer comes first, followed by short fields such as the title, then `content`. The
optional `metadata` field comes last. `backend/onyx/chat/README.md` states why: naming it `document` avoids
the model narrating "I should reference citation_id: 5"-style artifacts, and putting
the number first exploits models' stronger local attention even though they have
full context access.

### 4.3 Range allocation

`backend/onyx/agents/tool_execution.py:ToolBatch` supplies stable call indices.
SearchTool, WebSearchTool, and OpenURLTool calculate their range as
`context.next_citation_num + CITATIONS_PER_TOOL_CALL * invocation.call_index`.
`backend/onyx/tools/interface.py:CITATIONS_PER_TOOL_CALL` is 100. Parallel calls
therefore use distinct ranges without mutating a shared counter.

### 4.4 Teaching the format: prompt and reminder

Citation guidance lives only in the trailing reminder, never in the system
prompt: head prompts are built with `should_cite_documents=False` so the cached
message prefix stays byte-stable across loop iterations (a `{{CITATION_GUIDANCE}}`
tag in a system/agent prompt resolves to empty). `backend/onyx/chat/prompt_utils.py:build_chat_reminder`
appends `REQUIRE_CITATION_GUIDANCE`, `ANSWER_COVERAGE_GUIDANCE`, and
`ANSWER_COMPLETENESS_REMINDER` (`prompts/chat_prompts.py`, plus
`LAST_CYCLE_CITATION_REMINDER` on the final cycle) to the reminder message whenever `should_cite_documents or always_cite_documents` is
true, via `prompt_utils.py:build_reminder_message`. `REQUIRE_CITATION_GUIDANCE` is
skipped if the task prompt already carried it via `{{CITATION_GUIDANCE}}`. The citation reminder strings tell the
model to cite the `"document"` field using `[1]`, `[2]`, `[3]` syntax.

Per [[core-chat-loop]] §4.4, the reminder is always the **last** message in the
assembled context, because models attend hardest to the final tokens. A citation
reminder placed anywhere else degrades citation reliability; this is measured
behavior, not a style preference (`backend/onyx/chat/README.md`).

### 4.5 Parsing the stream: `DynamicCitationProcessor`

`backend/onyx/chat/agent.py:ChatAgent` creates a `DynamicCitationProcessor` for prompt sources (mode
`HYPERLINK` unless `include_citations=False`), seeds it with any project-file
citation mapping (`build_context_file_citation_mapping`), and updates it after every
tool response via `citation_utils.py:update_citation_processor_from_tool_result`,
which turns a `SearchDocsResponse.citation_mapping` (`dict[int, str]`, number to
document id) into a `dict[int, SearchDoc]` by matching against
`search_docs_response.search_docs`.

`backend/onyx/chat/renderer.py:MessageRenderer._content` feeds answer text to
`citation_processor.process_token`. The processor holds
back text that might be a partial citation (`possible_citation_pattern`). It skips
markers inside fenced code blocks, which `CodeFenceTracker` tracks line by line.
Once a
complete match is found (`citation_pattern`, which also accepts `[1, 2]`, `[[1]]`,
and the unicode bracket variants `【1】`/`［1］`), it looks up each number in
`citation_to_doc`, rewrites the marker to `[[n]](link)`, and yields a `CitationInfo`
**before** the rewritten text so the frontend has the mapping in hand before it
needs to render the link (`citation_processor.py:_process_citation`, the "Yield
CitationInfo objects BEFORE the citation text" comment).

`backend/onyx/chat/renderer.py:MessageRenderer` collects each emitted `CitationInfo`
in its `citations` list.

### 4.6 Known sources and displayed citations

`backend/onyx/chat/agent.py:ChatAgent` maintains the known source mapping for prompts.
The renderer records only citations that appear in displayed text.
`backend/onyx/chat/presentation.py:project_response` rebuilds the saved display from
recorded messages with the same renderer. It carries source documents and emitted
citation information into persistence.

This distinction prevents unused source numbers from appearing in saved citations.
It also preserves citations when an answer stops before completion.

### 4.7 Persistence: `save_chat_turn`

`backend/onyx/db/chat_response.py:save_chat_turn` (see also [[chat-persistence]]):

1. Creates a `SearchDoc` DB row for every document in `all_search_docs` (the
   pre-deduplicated set gathered from tool calls).
2. Builds `tool_call_to_search_doc_ids` so each `ToolCall` links to the `SearchDoc`
   rows it displayed.
3. For each `(citation_num, SearchDoc)` in `citation_to_doc`, skips it if
   `emitted_citations` is provided and the number is not in it, otherwise resolves
   or creates the matching DB `SearchDoc` row and records
   `citation_number_to_search_doc_id[citation_num] = db_search_doc_id`. A citation
   doc missing from `all_search_docs` is expected for project files
   (`source_type == FILE`) and logged as a warning otherwise, since it can indicate
   an upstream bug.
4. Links every tool-call `SearchDoc` and every citation-only project-file `SearchDoc` to the
   `ChatMessage` via `add_search_docs_to_chat_message`.
5. Sets `assistant_message.citations = citation_number_to_search_doc_id or None`.

An incognito, content-free turn (`persist_content=False`) blanks
`citation_to_doc`, `all_search_docs`, and `emitted_citations` before any of this
runs, so no citation state survives for an incognito turn.

### 4.8 Frontend resolution

`web/src/app/app/services/packetUtils.ts:getCitations` folds every `CitationInfo`
packet in a message's packet list into a `StreamingCitation[]`, deduped by
`document_id` (a document cited twice keeps only its first citation number).
`usePacketProcessor.ts` turns that into a `CitationMap` (`{citation_num:
document_id}`, `app/interfaces.ts:CitationMap`) stored on the packet-processing
state.

`markdownUtils.tsx:useMarkdownComponents` wires every markdown anchor to
`MemoizedTextComponents.tsx:MemoizedAnchor`, passing `citations` (the `CitationMap`)
and `docs` (the turn's `OnyxDocument[]`). `MemoizedAnchor` matches link text against
`/\[(D|Q)?(\d+)\]/`: a bare number resolves through `citations[n] -> document_id ->
docs.find(document_id)`; a `D`-prefixed number is also a document citation and resolves the same way. Only a
`Q`-prefixed number is a sub-question link: it indexes `subQuestions[n - 1]` (used by
deep research). If neither an `associatedDoc` nor an `associatedSubQuestion` is found, it
returns `<></>`: nothing is rendered, by design, because during streaming the
`CitationInfo` packet may simply not have arrived yet.

`markdownUtils.tsx:processContent` strips a trailing incomplete `[[n]](url...` or a
bare `[[`/`[[n]`/`[[n]]` at the very end of the accumulated content before handing it
to the markdown parser, so a half-typed citation link never flashes as broken
markdown mid-stream.

`MessageToolbar.tsx:SourcesTagWrapper` is a second, independent consumer of the same
citation data: it converts the message's citations plus its document map into a flat
`SourceInfo[]` (`citationsToSourceInfoArray`) for the toolbar's "Sources" button,
which toggles the documents sidebar rather than resolving an inline link.

### 4.9 Replay

`session_loading.py:translate_assistant_message_to_packets` reconstructs a saved
turn's packet stream without re-running it. For citations specifically: it reads
`chat_message.citations` (`dict[citation_num, search_doc_id]`), looks up each
`SearchDoc` by id (`get_db_search_doc_by_id`), and builds one `CitationInfo` per
entry. It then sorts them by first appearance in the saved text
(`citation_utils.py:extract_citation_order_from_text`), and appends them, via
`create_citation_packets`, **after** the full `AgentResponseStart`/`AgentResponseDelta`
block for the message, not interleaved with it the way the live stream interleaves
`CitationInfo` with token deltas. The frontend does not care about this difference:
`getCitations` folds all `CitationInfo` packets into the map regardless of position,
and by the time a replayed message's full text is available, its citation map is too.

---

## 5. Contracts and invariants

1. **Citation numbering ranges must not collide across parallel tool calls.**
   `ToolBatch` supplies a stable `call_index`; each search tool offsets its
   base citation number by `CITATIONS_PER_TOOL_CALL * call_index`. Sharing one counter, or reusing a range across
   calls, silently merges two documents' citations.
2. **The number in the LLM-facing document JSON is the number the model is asked to
   emit.** `convert_inference_sections_to_llm_string`'s `citation_id` and the prompt
   guidance's `[1], [2], [3]` instructions must refer to the same numbering scheme;
   they are produced from the same `citation_start` / `starting_citation_num`
   value passed down the same call.
3. **A `CitationInfo` packet must precede or accompany the text that references
   it, or the frontend renders nothing.** `_process_citation` yields `CitationInfo`
   objects before the rewritten citation text specifically so the client has the
   mapping before it needs to resolve the link. A change that reorders this breaks
   live rendering, though not replay (§4.9).
4. **The persisted mapping must reproduce the live rendering on replay.**
   `ChatMessage.citations` plus `SearchDoc` rows must be sufficient for
   `translate_assistant_message_to_packets` to regenerate the same `CitationInfo`
   set a live turn would have emitted. Only `emitted_citations` are persisted
   (§4.6); a change to what counts as "emitted" changes what a reload shows.
5. **The citation reminder must stay last** in the assembled context
   (`backend/onyx/chat/prompt_utils.py:build_chat_reminder`, `prompt_utils.py:build_reminder_message`).
   See [[core-chat-loop]] §5.9.
6. **The document JSON key name and field order are deliberate and must not be
   "tidied".** The key is `document`, not `citation_id` or `id`
   (`convert_inference_sections_to_llm_string`), specifically to avoid the model
   producing reasoning artifacts about "citation_id". The integer field comes
   before title/metadata/content specifically for local-attention reasons
   (`backend/onyx/chat/README.md`). Renaming the key or moving the field requires
   re-validating citation accuracy with an eval, not just a unit test.
7. **`citation_to_doc` and `_emitted_citations` are not interchangeable.**
   `save_chat_turn` must receive both; using only the full mapping persists
   citations the user never actually saw, using only the emitted set without the
   mapping loses the `SearchDoc` to attach them to.
8. **Duplicate citation numbers across tools favor the first-registered mapping.**
   `DynamicCitationProcessor.update_citation_mapping(update_duplicate_keys=False)`
   is the default used in the loop; if `OpenURLTool` and `WebSearchTool` ever
   produce the same number, the existing (web search) mapping wins. Do not flip
   this default without checking that call site's comment.

---

## 6. Relationships

**Depends on**
- [[internal-search]] and [[web-search]]: produce the `InferenceSection`s and
  `SearchDocsResponse.citation_mapping` that citations are built from.
- [[tools-framework]]: `backend/onyx/agents/tool_execution.py:ToolBatch` allocates the citation-number range per
  tool call as part of running the tool batch.
- [[context-assembly]]: places the system prompt's citation guidance and the
  reminder message that teaches the format.
- [[streaming-protocol]]: `CitationInfo` is one packet type in that vocabulary,
  subject to the same `Placement`/`Emitter` rules as every other packet.
- [[core-chat-loop]]: `backend/onyx/chat/agent.py:ChatAgent` tracks prompt sources;
  `backend/onyx/chat/presentation.py:project_response` prepares display citations for saving.

**Depended on by**
- [[chat-persistence]]: `save_chat_turn` writes `ChatMessage.citations` and the
  `SearchDoc` links this component computes.
- [[chat-frontend]]: `MemoizedAnchor`, `processContent`, and `SourcesTagWrapper` are
  the sole consumers of `CitationInfo` on web; there is no dedicated citation
  renderer, only markdown-link resolution.
- Intermediate-report rendering uses `KEEP_MARKERS` in `backend/onyx/chat/presentation.py`.
  `backend/onyx/deep_research/agent.py` uses `citation_utils.collapse_citations`
  to renumber citations when merging child reports.

---

## 7. Blast radius

| If your change… | Also check |
|---|---|
| changes the LLM-facing document JSON format (`convert_inference_sections_to_llm_string`) | the citation guidance text in `prompts/chat_prompts.py`; every citeable tool (`SearchTool`, `WebSearchTool`, `OpenURLTool`); run a citation eval, not just a unit test, since this is a behavior-sensitive prompt surface |
| adds a new citing tool | `backend/onyx/tools/interface.py:CITATIONS_PER_TOOL_CALL` and each tool's call-index offset; `citation_utils.py:update_citation_processor_from_tool_result`'s `CITEABLE_TOOLS_NAMES` check (`tools/built_in_tools.py`); [[tools-framework]] |
| changes `CitationInfo` or adds a citation-adjacent packet type | [[streaming-protocol]] §5 and §7 in full: `StreamingType`, both hand-mirrored frontend enums, `findRenderer` |
| changes markdown or link rendering (`MemoizedAnchor`, `processContent`, `useMarkdownComponents`) | the `[Q]` sub-question link path shares the same anchor component; verify ordinary numeric citations are unaffected |
| changes what `save_chat` persists for citations | `session_loading.py:translate_assistant_message_to_packets`; a saved-session reload must still reproduce the live citation set |
| reorders the assembled prompt (system prompt, reminder, tool responses) | citation quality is the most common casualty; see [[core-chat-loop]] §7 |
| changes citation regex patterns (`citation_pattern`, `possible_citation_pattern`) | the ReDoS-safety comment in `citation_processor.py` above `possible_citation_pattern`; keep the comma-separated digit-run form, do not reintroduce nested unbounded quantifiers |

---

## 8. How to verify a change

### Tests

```bash
cd backend && uv run pytest tests/unit/onyx/chat/test_citation_processor.py -v
cd backend && uv run pytest tests/unit/onyx/chat/test_citation_utils.py -v
cd backend && uv run pytest tests/unit/onyx/chat/test_prompt_caching.py -v
cd backend && uv run pytest tests/unit/onyx/chat/test_response_projection.py -v
cd backend && uv run pytest tests/unit/onyx/prompts/test_prompt_utils.py -v
cd backend && uv run pytest tests/unit/onyx/tools/test_search_llm_json.py -v
```

See `backend/AGENTS.md` for the authoritative commands and required env.

### Manual reproduction

1. Confirm services are up: `tail -f backend/log/api_server_debug.log`.
2. Open `http://localhost:3000`, sign in as `admin_user@example.com` /
   `TestPassword123!`.
3. Ask a question that forces a search, for example "what does our onboarding doc
   say".
4. As the answer streams, confirm every numbered marker resolves to a hoverable
   source card, and that the "Sources" tag in the message toolbar lists the same
   documents.
5. Reload the session from the sidebar (`GET /chat/get-chat-session/{id}`).
   Confirm every citation in the replayed view resolves exactly as it did live,
   same numbers, same documents.

### What "working" looks like

- Every citation number in the rendered answer resolves to a real, displayed
  document. None resolve to documents outside `displayed_docs` for that turn.
- Two concurrent search-like tool calls never produce colliding citation numbers.
- The replayed view of a saved session is visually identical to the live stream.

---

## 9. Footguns

- **An unresolved citation renders as nothing, not an error.** A broken mapping
  looks exactly like missing text. If citations silently vanish from an answer,
  suspect the pipeline before suspecting the model.
- **Citation numbers use turn-wide, ascending ranges.** Each citeable tool call
  reserves 100 numbers, starting at the next free number (§4.3). Later batches start
  after the highest existing number. Do not assume one call owns the whole turn.
- **History keeps the model's original query arguments**, but the documents it
  cites come from whatever actually ran after expansion (see [[internal-search]]
  §9). The citation numbering is tied to that expanded, executed search, not to
  the user's literal question.
- **`processContent` hides partial citation markup during streaming.** This is
  correct for the typewriter effect, but it can also mask a real parsing bug: a
  citation that never completes because of a backend regex or mapping error looks
  identical, on screen, to one that is simply still streaming.
- **`citation_to_doc` (full mapping) and `_emitted_citations` (streamed subset)
  answer different questions.** Reading the wrong one when adding a new save path
  either persists citations nobody saw or drops citations that were shown.
- **`[Q#]` is not an internal-search citation.** `MemoizedAnchor` treats it as a
  deep-research sub-question link, keyed by list index rather than by the citation
  map. `[D#]` still resolves through the citation map like a bare `[#]`. Do not assume every bracket-number pattern in the text goes
  through the citation pipeline described here.
