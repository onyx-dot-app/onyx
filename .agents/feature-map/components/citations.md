# Citations

> The chain that turns a retrieved document into a numbered marker the model
> emits, and turns that marker back into a clickable source in the UI. A break at
> any point in the tools, prompt, stream parser, database or renderer fails
> without an error.

**Verified against:** `6bac4e012f` (2026-10-29)
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
- [[tools-framework]]: gives each tool call in a step its call index.
- [[context-assembly]]: places the citation guidance in the prompt.
- [[streaming-protocol]]: the `CitationInfo` packet.
- [[chat-persistence]]: `ChatMessage.citations` and the `SearchDoc` links.
- [[chat-frontend]]: the message view that hosts link resolution and the
  "Sources" toolbar tag.

---

## Architecture

```
search tool returns InferenceSections               [[internal-search]], [[web-search]]
  -> convert_inference_sections_to_llm_string       numbers each unique document_id from the
                                                    call's start number; returns the JSON
                                                    for the model + {number: document_id}
  -> ChatAgent._update_tool_context                 registers the numbers (chat/agent.py)
  -> reminder message teaches "[1]" syntax          chat/prompt_utils.py:build_chat_reminder
  -> model emits "[1]", "[1, 3]", "[[4]]", "【1】"
  -> MessageRenderer._content -> process_token      chat/renderer.py; maps number -> SearchDoc,
                                                    rewrites the marker as a link, emits CitationInfo
  -> project_response -> save_chat_turn             chat/presentation.py, db/chat_response.py;
                                                    stores {number: SearchDoc.id} for emitted numbers
  -> handleCitationPacket -> MemoizedAnchor (web)   {number: document_id} -> displayed doc
  -> replay_response                                rebuilds CitationInfo on reload
```

`backend/onyx/chat/README.md` gives the prompt-design reasons for the document
format and the reminder placement.

**Numbering.** `chat/agent.py:ChatAgent` owns the prompt's number space. It
seeds its processor with the sources of every earlier message in history, so
numbers stay unique across turns. Each step passes
`ToolContext.next_citation_num`, and each citeable tool starts at
`next_citation_num + CITATIONS_PER_TOOL_CALL * invocation.call_index`
(`tools/interface.py:CITATIONS_PER_TOOL_CALL`). The call index is the call's
position in the step (`agents/tool_execution.py:ToolBatch`), so parallel
searches never share a number. The numbered documents come from the expanded
queries that ran. Saved history keeps only the model's own arguments, not
those queries ([[chat-persistence]]).
Project files reuse the number they had earlier in the session, by file ID;
new files take unused numbers
(`chat/citation_utils.py:build_context_file_citation_mapping`). When project
files are inline or searched, `chat/prompt_utils.py:build_chat_prompt` turns
on citation guidance from the first step. `open_url` does not always take a
new number: `OpenURLTool` reuses the number that a URL already has in
`ToolContext.citation_mapping`.

**Web rendering.** Inline links resolve through
`web/src/app/app/message/messageComponents/timeline/hooks/packetProcessor.ts:handleCitationPacket`,
which builds `citationMap`.
`web/src/app/app/message/messageComponents/AgentMessage.tsx` merges it with
`chatState.citations` as `mergedCitations` and passes the map to
`MemoizedAnchor`. `app/app/services/packetUtils.ts:getCitations` feeds only the
documents sidebar.

**Two processors, two mappings.** The `ChatAgent` processor holds every number
the model could cite and copies it into each step's `ChatMessageMetadata.sources`.
`chat/renderer.py:MessageRenderer` builds a display processor from those sources
and records only the `CitationInfo` it emitted. At save,
`chat/presentation.py:project_response` rebuilds both from the run snapshot,
and `db/chat_response.py:save_chat_response_to_db` passes them to
`save_chat_turn`, which persists the emitted subset. A reload shows what the
user saw. On the next turn, `chat/response.py:restore_response_sources` puts
the saved numbers back on history messages before the agent reads them.

**Modes.** `CitationMode.HYPERLINK` is the default. `REMOVE` strips markers when
a request sets `include_citations=False`, for example a public bot.
`KEEP_MARKERS` keeps raw markers for the research agent's intermediate reports
(`deep_research/research_agent.py`, and `chat/presentation.py:message_presentation`
for their display). `chat/citation_utils.py:collapse_citations` renumbers those
markers when `deep_research/agent.py` merges the reports.

---

## Contracts and traps

1. `unresolved-citation-silent` **An unresolved citation renders as nothing,
   not as an error.**
   `web/src/app/app/message/MemoizedTextComponents.tsx:MemoizedAnchor` returns
   an empty fragment when a number has no document. During streaming this is
   correct, because the mapping can arrive late. It also hides real bugs. If
   citations disappear, suspect the pipeline before the model.
2. `citation-info-any-order` **A client must accept `CitationInfo` before or
   after the text that uses it.** `chat/citation_processor.py:DynamicCitationProcessor.process_token`
   yields the packet before the rewritten marker, but
   `chat/renderer.py:MessageRenderer._content` sends each batch's text first
   and its `CitationInfo` after. Replay of an older message sends all
   `CitationInfo` after the answer. This works only because
   `handleCitationPacket` and `getCitations` fold packets into a map in any
   order
   (`app/app/message/messageComponents/timeline/hooks/packetProcessor.ts:handleCitationPacket`,
   `app/app/services/packetUtils.ts:getCitations`) and the link renders as
   nothing until its number arrives ([[#unresolved-citation-silent]]). Keep
   both properties. Only `HYPERLINK` mode yields `CitationInfo`; the other
   modes save no citations.
3. `number-block-per-tool-call` **Do not share one number range across parallel
   tool calls.** Each citeable tool adds the
   `CITATIONS_PER_TOOL_CALL * invocation.call_index` offset to
   `context.next_citation_num`, as
   `tools/tool_implementations/web_search/web_search_tool.py` does. A tool
   that skips the offset gives two documents the same number, and one
   citation points at the wrong source.
4. `persist-emitted-subset` **Persist the emitted subset, with the full mapping
   to resolve it.** `db/chat_response.py:save_chat_turn` needs both. With only
   the full mapping, it stores citations the user never saw. With only the
   emitted set, it cannot find the `SearchDoc` for each number. Each new save
   path must pass both, from `chat/presentation.py:project_response`.
5. `document-key-prompt-design` **The document JSON key and field order are
   prompt design.** The key is `document`, not `citation_id`, so the model does
   not write reasoning such as "I should reference citation_id: 5". The number
   comes first because models attend most to nearby text. A change to either
   needs a citation eval, not only a unit test. The body key differs by source:
   search results use `content` with `metadata` last
   (`tools/tool_implementations/utils.py:convert_inference_sections_to_llm_string`),
   and project files use `contents`
   (`chat/prompt_utils.py:_create_context_files_message`).
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
   with `update_duplicate_keys=False` is the default for tool results in
   `chat/agent.py:ChatAgent._update_tool_context`. History answers and project
   files pass `True`, so their saved numbers win. Do not change either without
   checking the call sites.
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
12. `history-owns-numbers` **Saved history must bring its citation numbers
    back.** `chat/agent.py:ChatAgent` starts new numbers after the highest
    number in history. Saved tool results keep `citation_mapping` but no
    documents; `chat/response.py:restore_response_sources` refills them, and
    the answer's sources come from its saved `MessageRendering.citation_documents`.
    A source that a history path drops lets a later search reuse its number,
    and an old marker then points at a new document. Chat and deep research
    both read these saved sources, so a mode switch keeps the links.

---

## Dependencies

- [[internal-search]]: produces the sections and
  `SearchDocsResponse.citation_mapping`.
- [[web-search]]: produces web sections and reuses numbers in `open_url`.
- [[tools-framework]]: the call index that offsets each tool's number range.
- [[context-assembly]]: places the citation reminder last.
- [[core-chat-loop]]: `ChatAgent` holds the prompt mapping, and the renderer
  and `project_response` produce the emitted set for save.
- [[streaming-protocol]]: the `CitationInfo` packet.
- [[chat-persistence]]: stores the emitted mapping and replays it on reload.

---

## Recipes

- `citeable-tool` **A new citeable tool.** Copy how `WebSearchTool` is wired; list the
  current set in `tools/constants.py:CITEABLE_TOOLS_NAMES`. Add the tool name
  there. That turns on the citation reminder in `build_chat_reminder`, so the
  model is asked to cite. Without it the tool gets numbers that the model is
  never asked to use. Start its numbers at the offset in
  [[#number-block-per-tool-call]]. Return a `SearchDocsResponse` with
  `citation_mapping`, so that
  `chat/citation_utils.py:message_citation_sources` can register it.
- `save-path` **A new save path.** Copy the call in
  `db/chat_response.py:save_chat_response_to_db`; list the
  callers with `git grep -n 'save_chat_turn(' backend/onyx`. Pass both
  mappings ([[#persist-emitted-subset]]). Confirm that a reload through
  `server/query_and_chat/session_loading.py:translate_assistant_message_to_packets`
  shows the same citations as the live stream, and that the next turn does not
  reuse a number ([[#history-owns-numbers]]).
- `investigate-missing-citations` **Investigate "citations disappear" or "a
  citation opens the wrong source".** Capture the stream in the browser network tab. If no
  `citation_info` packet arrives for a number that the text shows, the
  processor had no mapping: check that the tool is in `CITEABLE_TOOLS_NAMES`
  and returns `citation_mapping`. If the packet arrives but the marker renders
  as nothing, the document is missing from the message's documents
  ([[#unresolved-citation-silent]]). If a number points at the wrong source,
  look for two tools that share a number block ([[#number-block-per-tool-call]],
  [[#first-mapping-wins]]), or a number reused from an earlier turn
  ([[#history-owns-numbers]]). If the live answer is right and the reload is
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
