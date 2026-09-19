> Status: active · Task: 9a-citations

# Mobile Chat 9a — Citations & Cited Sources — Implementation Plan

## Issues to Address

The mobile chat renders assistant answers as plain markdown with **no citation support**: inline
`[N]` markers are inert text and there is no cited-sources surface. Web shows inline citation chips
plus a "Sources" panel; mobile shows neither (confirmed clean slate — no citation packet types, no
processing, no sources UI). This change ports web's citation **behavior** to mobile:

1. Type + process the citation/document streaming packets already arriving in `node.packets`.
2. Make inline `[N]` markers (and ordinary answer links) **tappable**, opening the source in the
   in-app browser.
3. Render a **"Sources" button** under completed answers that opens a **bottom sheet** listing the
   cited/found source documents. Tapping a linked doc opens it in the in-app browser; a file /
   link-less doc has no mobile preview yet, so it shows a heads-up toast (files) or no-ops.
4. Establish the minimal, reusable packet-processing + source-UI **foundation** that PR 9b (agent
   timeline) extends — without building grouping now.

Out of scope (later phases): inline chip components / hover cards (platform-blocked — see Notes),
turn/tab packet grouping + timeline steps (9b), a per-connector source-logo set, an in-app document
preview for file sources.

## Important Notes

Pulled from `01-research.md` / `02-high-level-design.md` / `03-detailed-design.md`:

- **Native markdown renderer has no custom-node hook.** `react-native-streamdown` →
  `react-native-enriched-markdown` exposes only `markdownStyle` + `onLinkPress`/`onLinkLongPress`
  (`StreamdownText` inherits all `EnrichedMarkdownText` props + `remendConfig`). So inline citations
  are **styled tappable links**, not custom chips. Wire `onLinkPress` through
  `mobile/src/components/chat/StreamingMarkdown.tsx`.
- **The marker URL is pre-baked.** Backend emits `[[{num}]]({link})` with `link = search_doc.link
  or ""` (`backend/onyx/chat/citation_processor.py:496,506`). So `onLinkPress(event.url)` opens the
  doc directly — **no citation-state lookup for the tap**. Empty-URL `[[n]]()` = file source with no
  link (the edge case; reachable via the Sources sheet).
- **Only one citation packet exists:** `CitationInfo {citation_number, document_id}` (`citation_info`).
  Web's `citation_start`/`citation_end` are **never emitted** — do not add them. Document packets:
  `search_tool_documents_delta` + `open_url_documents`, each `{documents: SearchDoc[]}`.
  `message_start` carries `final_documents: SearchDoc[] | null`. Terminal is `stop` (no
  `message_end`). Docs arrive **before** the answer; `citation_info` arrives just before its marker
  text; dedup per `document_id`.
- **Nothing new is needed to receive packets.** `useChatController` stores every wrapped packet on
  `node.packets`; `processRawChatHistory` loads historical packets; `usePacketDisplay` already hands
  all packets to the one matched `MessageTextRenderer`. So the controller/history/stream/registry-
  list are untouched.
- **Reuse:** `FilePickerSheet.tsx` = the bottom-sheet Modal pattern to mirror; `Card`/`LineItemButton`/
  `Separator`/`Spinner`/`Text`/`Icon`/`Button` primitives; `timeAgo` from `mobile/src/lib/time.ts`;
  `expo-web-browser` `openBrowserAsync` (already a dep) for opening links; `expo-image` for
  **public** favicons (NOT `BearerImage`). **Gap:** no `SourceIcon`/`WebResultIcon`/source-logo set
  on mobile — build a minimal favicon-or-`file-text` version.
- **Foundation seams (Approach C), each justified by a concrete 9b consumer:** the incremental
  `messageProcessor` (9b extends with grouping), the `processed` channel on `usePacketDisplay` +
  `MessageRendererProps` (9b's renderers read it), and `SearchDoc`/`SourceRow`/`SourceIcon`/
  `openSource` (9b's search/fetch sub-renderers reuse them). Grouping itself is deferred to 9b; 9a
  state stays flat.
- **Constraints:** mobile spacing classes are pixels; all text via `@/components/ui/text`; icons via
  `@/icons/*` + `Icon`; semantic color classes only; no `dark:`. Do not touch `/sources/[id]` (that
  route is the project-files screen) — the cited-sources surface is a Modal, no route.

## Implementation Strategy

Ordered so each step is a coherent, compilable change; the pure/foundation layers land before the UI
that consumes them.

1. **Packet contracts.** Add `mobile/src/chat/contracts/documents.ts` (`SearchDoc`,
   `StreamingCitation`, `CitationMap`). Extend `mobile/src/chat/streamingModels.ts`: `PacketType`
   members `CITATION_INFO` / `SEARCH_TOOL_DOCUMENTS_DELTA` / `OPEN_URL_DOCUMENTS`; interfaces
   `CitationInfo` / `SearchToolDocumentsDelta` / `OpenUrlDocuments`; `MessageStart.final_documents?`;
   add all three to the `ObjTypes` union.
2. **Processor (foundation).** Add `mobile/src/chat/messageProcessor.ts` — `ProcessedMessageState`,
   `createInitialState`, `processPackets` (incremental cursor, reset-on-shrink, in-place mutation;
   handlers for citation/document/message_start/stop). Pure, no React.
3. **Host the processor.** Rework `mobile/src/hooks/usePacketDisplay.ts` into the mobile analog of
   web's `usePacketProcessor`: ref-held state, reset on `nodeId` change + array shrink, process new
   packets each render, return `{ renderer, packets, processed }` (drop top-level `isComplete`).
4. **Renderer contract.** Change `MessageRendererProps` in
   `mobile/src/components/chat/renderers/registry.ts` to `{ packets, processed }`.
5. **Inline tap-routing.** Add `mobile/src/chat/openSource.ts` (`documentTarget`, `openUrl`,
   `openSource`). Add `onLinkPress` passthrough to `StreamingMarkdown.tsx`. In
   `MessageTextRenderer.tsx`, read `processed.isComplete` and pass an `onLinkPress` that opens the
   URL in-browser.
6. **Source presentation layer (foundation).** Add `SourceIcon.tsx` (favicon via `expo-image` +
   `file-text` fallback) and `SourceRow.tsx` (icon + title + domain·date + 2-line snippet, `onPress`
   → `openSource`). Add `mobile/src/chat/citations.ts` (`selectSources(processed)` split into
   Cited/More/User-Files + `iconDocs`; `domainOf`/`faviconUrl`).
7. **Sources surface (9a).** Add `CitedSources.tsx` — `CitedSourcesBar` (icon stack + "Sources · N")
   and `CitedSourcesSheet` (bottom-sheet Modal mirroring `FilePickerSheet`, three sections).
8. **Wire into the message.** In `MessageRow.tsx` `AssistantMessage`: consume `processed`, use
   `processed.isComplete` for the `AgentTimeline` loading + `hasContent`, and render the Sources bar
   + sheet (local `visible` state) after the renderer when `processed.isComplete && hasSources`.
9. **Fixtures + tests** (see Tests).

## Tests

Primary type: **unit tests (jest-expo, RN Testing Library)** — this is a client rendering feature
with pure processing logic; no backend/integration surface. Add `makePacket` / `makeCitationPacket`
/ `makeSearchDoc(+Packet)` to `mobile/src/chat/__tests__/fixtures.ts`, then:

- **`messageProcessor.test.ts`** — citation dedup + first-cite ordering; `citationMap` population;
  `documentMap` upsert from both document packet types + `message_start.final_documents`; `isComplete`
  on `stop`; incremental cursor (no double-count across flushes); reset-on-array-shrink.
- **`citations.test.ts`** — `selectSources` splits Cited (citation order) / More / User Files
  correctly and dedupes; `hasSources`/`iconDocs`; `domainOf`/`faviconUrl` edge cases (no host, no
  link).
- **`openSource.test.ts`** — `documentTarget` branches: link → browser, file_id+no-link → file,
  neither → none (mock `expo-web-browser`).
- **`SourceRow.test.tsx`** — renders title/domain/snippet; favicon vs fallback icon; `onPress` →
  `openSource`.
- **`CitedSources.test.tsx`** — bar visibility gate (`isComplete && hasSources`); sheet renders the
  three sections from a processed state; row tap routes to `openSource`.

Gate: `bun run typecheck`, `bun run lint`, `bunx jest`. Device-verify (owner, post-merge) the two
platform unknowns: the `onLinkPress` `event` payload shape and whether `[[n]]()` renders tappable.

## Plan Challenge Results

### 1. Extendability & Scalability: PASS
Foundation seams are sized to a named 9b consumer each (processor→grouping, `processed` channel→9b
renderers, `SearchDoc`/`SourceRow`/`SourceIcon`/`openSource`→9b search/fetch rows). The incremental
cursor (web-proven) scales to long answers/many citations without re-parse; a new packet type =
extend the union + one handler + optionally one renderer. 9a state is grouping-free, so 9b *adds*
fields rather than reshaping — no rewrite.

### 2. Fragility: CONCERN (isolated + mitigated)
The one real brittle point is the inline `onLinkPress` path — it depends on `StreamdownText`
forwarding `onLinkPress` and the `event.url` payload shape (documented, but device-unverified), plus
the empty-parens `[[n]]()` file marker possibly not rendering tappable. Both are **isolated** in
`StreamingMarkdown` + a one-line handler, have the **Sources sheet as a reliable fallback path** to
every source, and are flagged for device-verify (with a kept-out-of-default 1-line normalize
fallback). Secondary: in-place processor mutation + stable ref (documented: use primitive proxies,
never memoize on `processed` identity) and reset-before-process ordering on regenerate (called out).

### 3. Industry Standard: VERIFIED
Searched RN in-app-browser guidance and RAG streaming-citation patterns. `WebBrowser.openBrowserAsync`
(SFSafariViewController / Chrome Custom Tabs) is the **official Expo recommendation** for opening a
webpage in-app (`Linking.openURL` is for ejecting to the system browser) — matches the plan. The
citation flow (accumulate text, collect search results with rich metadata, map numbered markers to
sources, show the reference list on completion) is the standard pattern across Perplexity / Cohere /
OpenAI Agent API. Sources: https://docs.expo.dev/versions/latest/sdk/webbrowser/ ·
https://docs.perplexity.ai/docs/cookbook/articles/streaming-citations/README ·
https://docs.cohere.com/docs/rag-citations
- Conscious divergence: industry often shows a **live citation counter during** streaming; we gate
  the Sources bar on `isComplete` to avoid mid-stream layout shift (web-parity). Easy to revisit.

### 4. Fact Check: PASS
Every "standard/recommended" claim is verified: in-app browser via `openBrowserAsync` (Expo docs,
above); "no custom-node hook in enriched-markdown, only `markdownStyle` + `onLinkPress`" (published
API reference, Phase 1); "marker URL pre-baked as `[[n]](link)`, `link = search_doc.link or ""`"
(code-verified `backend/onyx/chat/citation_processor.py:496,506`); "only `citation_info` emitted, no
`citation_start/end`" (code-verified `streaming_models.py`). No unverified assertions remain.

### 5. Maintainability: PASS
Mirrors web's citation architecture (`packetProcessor → usePacketProcessor → renderer props`) so a
web-familiar dev recognizes it immediately; reuses existing mobile primitives (the `FilePickerSheet`
sheet pattern, `Card`, `LineItemButton`, `Text`/`Icon`/semantic colors); clear file boundaries
(contracts / processor / hook / source layer / sheet). The one ripple is `MessageRendererProps`
gaining `processed` (replacing bare `isComplete`) — a single, well-named contract change.

### 6. Patch vs. Fix: PROPER FIX
Greenfield feature, not a workaround: no timeout/retry bumps, no error suppression, no loading-state-
for-backend-perf. "Styled tappable links instead of inline chips" is the correct adaptation to a real
platform constraint (native renderer, no custom-node hook) with behavior parity preserved — the
segmentation alternative was evaluated and rejected as fragile, not ignored. The only patch-shaped
item (the `[[n]]()` normalize) is explicitly kept out of the default path. **No patch-vs-fix decision
needed.**

**Verdict:** all six pass; the sole CONCERN (device-unverified `onLinkPress`) is inherent to any RN
markdown-tap feature, isolated, and covered by the sheet fallback + a flagged device-verify. Proceed.
