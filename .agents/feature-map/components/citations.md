# Citations

> The chain that turns a retrieved document into a numbered marker the model
> emits, and turns that marker back into a clickable source in the UI. A break at
> any point in the tools, prompt, stream parser, database or renderer fails
> without an error.

**Verified against:** `a4e97fcea1` (2026-10-29)
**Edition:** CE

---

## User experience

When the assistant answers from search results, numbered markers such as `[1]`
appear in the text as it streams. Hovering a marker shows a source card with
the title, source and a snippet. Clicking it opens the document in a preview or
in the documents sidebar. The "Sources" tag under the message lists every
document the message cites. A reloaded chat shows the same numbers pointing to
the same documents.

A caller can turn citations off (`include_citations=False`), for example a
public bot. The answer then has no markers.

When the chain breaks, the user sees no error. The marker disappears, and the
answer looks as if it never cited that source
([[#unresolved-citation-silent]]).

---

## Scope

This component owns citation numbering, the stream parser that turns markers
into links, the helpers that register tool results with the parser, and the
rules that connect them. It has no endpoints or tables of its own.

Its neighbours own the parts it passes through:
- [[tools-framework]]: allocates number ranges per tool call.
- [[context-assembly]]: places the citation guidance in the prompt.
- [[streaming-protocol]]: the `CitationInfo` packet.
- [[chat-persistence]]: `ChatMessage.citations` and the `SearchDoc` links.
- [[chat-frontend]]: the message view that hosts link resolution and the
  "Sources" toolbar tag.

---

## Architecture

```
search tool returns InferenceSections               [[internal-search]], [[web-search]]
  -> convert_inference_sections_to_llm_string       numbers each unique document_id from
                                                    starting_citation_num; returns the JSON
                                                    for the model + {number: document_id}
  -> reminder message teaches "[1]" syntax          llm_loop.py:select_reminder_text
  -> model emits "[1]", "[1, 3]", "[[4]]", "【1】"
  -> DynamicCitationProcessor.process_token          maps number -> SearchDoc, rewrites the
                                                    marker as a link, yields CitationInfo
  -> save_chat_turn                                 stores {number: SearchDoc.id} for the
                                                    numbers that were emitted
  -> handleCitationPacket -> MemoizedAnchor (web)   {number: document_id} -> displayed doc
  -> translate_assistant_message_to_packets         rebuilds CitationInfo on reload
```

`backend/onyx/chat/README.md` gives the prompt-design reasons for the document
format and the reminder placement.

**Numbering.** `backend/onyx/tools/tool_runner.py:run_tool_calls` starts each
batch at the processor's next free number. It gives each citeable tool call in
the batch its own block of 100 numbers, so parallel searches never share a
number. The numbered documents come from the expanded queries that ran.
Saved history keeps only the model's own arguments, not those queries
([[chat-persistence]]).
Project files take the first numbers, before any tool runs
(`build_context_file_citation_mapping`, called from
`chat/llm_loop.py:run_llm_loop`). When project files are inline or searched,
`always_cite_documents` is true, so the reminder carries citation guidance from
the first cycle. `open_url` does not always take a new number: `run_tool_calls`
passes the turn's mapping as `url_to_citation`, and `OpenURLTool` reuses the
number that a document already has in this turn.

**Web rendering.** Inline links resolve through
`web/src/app/app/message/messageComponents/timeline/hooks/packetProcessor.ts:handleCitationPacket`,
which builds `citationMap`.
`web/src/app/app/message/messageComponents/AgentMessage.tsx` merges it with
`chatState.citations` as `mergedCitations` and passes the map to
`MemoizedAnchor`. `app/app/services/packetUtils.ts:getCitations` feeds only the
documents sidebar.

**Two mappings.** `ChatStateContainer` (`chat/chat_state.py`) holds
`citation_to_doc`, which has every number the model could cite, and the
emitted set, which has only the numbers that appeared in streamed text.
`chat/save_chat.py:save_chat_turn` persists the emitted subset, so a reload
shows what the user saw.

**Modes.** `CitationMode.HYPERLINK` is the default. `REMOVE` strips markers when
a request sets `include_citations=False`, for example a public bot.
`KEEP_MARKERS` keeps raw markers for the research agent's intermediate reports.
`chat/citation_utils.py:collapse_citations` renumbers those markers when the
reports merge.

---

## Contracts and traps

1. `unresolved-citation-silent` **An unresolved citation renders as nothing,
   not as an error.**
   `web/src/app/app/message/MemoizedTextComponents.tsx:MemoizedAnchor` returns
   an empty fragment when a number has no document. During streaming this is
   correct, because the mapping can arrive late. It also hides real bugs. If
   citations disappear, suspect the pipeline before the model.
2. `citation-info-before-text` **`CitationInfo` must come before the text that
   uses it.** In `HYPERLINK` mode,
   `chat/citation_processor.py:DynamicCitationProcessor.process_token` yields
   the packet before the rewritten marker, so the client has the mapping when
   it renders the link. The other modes yield no `CitationInfo`, so they save
   no citations. Replay sends
   all `CitationInfo` packets after the answer. That works only because
   `handleCitationPacket` and `getCitations` both fold packets into a map in
   any order
   (`app/app/message/messageComponents/timeline/hooks/packetProcessor.ts:handleCitationPacket`,
   `app/app/services/packetUtils.ts:getCitations`). Keep both properties.
3. `number-block-per-tool-call` **Do not share one number range across parallel
   tool calls.** If a new citeable tool skips the `starting_citation_num += 100`
   step in `tools/tool_runner.py:run_tool_calls`, two documents get the same number and one citation
   points at the wrong source.
4. `persist-emitted-subset` **Persist the emitted subset, with the full mapping
   to resolve it.** `chat/save_chat.py:save_chat_turn` needs both. With only the full mapping, it
   stores citations the user never saw. With only the emitted set, it cannot
   find the `SearchDoc` for each number. Each new save path must pass both.
5. `document-key-prompt-design` **The document JSON key and field order are
   prompt design.** The key is `document`, not `citation_id`, so the model does
   not write reasoning such as "I should reference citation_id: 5". The number
   comes first because models attend most to nearby text. A change to either
   needs a citation eval, not only a unit test. The body key differs by source:
   search results use `content` with `metadata` last
   (`tools/tool_implementations/utils.py:convert_inference_sections_to_llm_string`),
   and project files use `contents`
   (`chat/llm_loop.py:_create_context_files_message`).
   `backend/onyx/chat/README.md` shows both formats.
6. `guidance-in-reminder` **Citation guidance lives only in the reminder.**
   The reminder is the last message, where the model attends most, and the
   system prompt must stay byte-stable for the prompt cache.
   [[context-assembly#no-citation-guidance-in-system-prompt]] and
   [[context-assembly#reminder-last-head-stable]] own the rule and how the
   `{{CITATION_GUIDANCE}}` tag resolves.
7. `first-mapping-wins` **When two tools produce the same number, the first
   mapping wins.**
   `chat/citation_processor.py:DynamicCitationProcessor.update_citation_mapping`
   with `update_duplicate_keys=False` is
   the default in the loop. Do not change it without checking the call sites.
8. `not-every-bracket-is-a-citation` **Not every bracketed number is a document
   citation.** `app/app/message/MemoizedTextComponents.tsx:MemoizedAnchor`
   matches `[n]`, `[Dn]` and `[Qn]`. `[Qn]` is a
   deep-research sub-question link indexed by list position, not by the
   citation map.
9. `parser-regex-linear` **The parser regex must stay linear.**
   `citation_pattern` and `possible_citation_pattern`
   (`chat/citation_processor.py:DynamicCitationProcessor.__init__`) accept
   comma-separated
   digit runs and the `【】` and `［］` brackets. Do not nest unbounded
   quantifiers. The comment above `possible_citation_pattern` explains the
   exponential backtracking risk.
10. `partial-link-hidden` **`processContent` hides a partial link at the end of
    the text.**
    `web/src/app/app/message/messageComponents/markdownUtils.tsx:processContent`
    strips a trailing incomplete `[[n]](url`, so a broken link does not flash
    during streaming. A citation that never completes because of a backend bug
    looks the same as one that is still streaming.
11. `code-block-markers-skipped` **A marker inside a fenced code block is not a
    citation.** `process_token` asks its
    `chat/citation_processor.py:CodeFenceTracker` whether each match
    sits in a code block, and leaves such markers as text with no
    `CitationInfo`. A change to fence tracking can turn code such as `a[1]`
    into a citation, or drop real citations after an unclosed fence.

---

## Dependencies

- [[internal-search]]: produces the sections and
  `SearchDocsResponse.citation_mapping`.
- [[web-search]]: produces web sections and reuses numbers in `open_url`.
- [[tools-framework]]: allocates number ranges in `run_tool_calls`.
- [[context-assembly]]: places the citation reminder last.
- [[core-chat-loop]]: creates one processor per turn and holds the mappings
  until save.
- [[streaming-protocol]]: the `CitationInfo` packet.
- [[chat-persistence]]: stores the emitted mapping and replays it on reload.

---

## Recipes

- `citeable-tool` **A new citeable tool.** Copy how `WebSearchTool` is wired; list the
  current set in `tools/constants.py:CITEABLE_TOOLS_NAMES`. Add the tool name
  there. That also sets `should_cite_documents` in `run_llm_loop`, so the
  reminder tells the model to cite. Without it the tool gets numbers that the
  model is never asked to use. Give it a number block in `run_tool_calls`: add
  a `<Tool>OverrideKwargs` type to the `override_kwargs` union and step
  `starting_citation_num` by 100 ([[#number-block-per-tool-call]]). Return a
  `SearchDocsResponse` with `citation_mapping`, so that
  `chat/citation_utils.py:update_citation_processor_from_tool_response` can
  register it.
- `save-path` **A new save path.** Copy the call in
  `chat/process_message.py:llm_loop_completion_handle`; list the
  callers with `git grep -n 'save_chat_turn(' backend/onyx`. Pass both
  mappings ([[#persist-emitted-subset]]). Confirm that a reload through
  `server/query_and_chat/session_loading.py:translate_assistant_message_to_packets`
  shows the same citations as the live stream.
- `investigate-missing-citations` **Investigate "citations disappear" or "a
  citation opens the wrong source".** Capture the stream in the browser network tab. If no
  `citation_info` packet arrives for a number that the text shows, the
  processor had no mapping: check that the tool is in `CITEABLE_TOOLS_NAMES`
  and returns `citation_mapping`. If the packet arrives but the marker renders
  as nothing, the document is missing from the message's documents
  ([[#unresolved-citation-silent]]). If a number points at the wrong source,
  look for two tools that share a number block ([[#number-block-per-tool-call]],
  [[#first-mapping-wins]]). If the live answer is right and the reload is
  wrong, compare `ChatMessage.citations` with the emitted numbers
  ([[#persist-emitted-subset]]).

---

## Verification

- Unit tests in `backend/tests/unit/onyx/chat/` cover the processor and the
  citation helpers. The web renderer tests sit beside
  `web/src/app/app/message/MemoizedTextComponents.tsx`. Prompt or format
  changes also need a citation eval.
- By hand, ask a question that forces a search. Each marker must open a source
  card, and the toolbar "Sources" tag must list the same documents. Reload the
  session: the same numbers must resolve to the same documents.
