> Status: active · Task: 9a-citations · Approach: C (Reusable Foundation) + A's inline simplification

# Mobile Chat 9a — Citations & Cited Sources — High-Level Design

## What it does

When the assistant answers using retrieved documents, the answer contains inline `[N]` citation
markers and the turn has a set of cited/found source documents. This feature makes the mobile chat
(1) render those `[N]` markers as tappable links that open the cited document, and (2) show a
"Sources" button under a completed answer that opens a bottom sheet listing the source documents
(title, source, snippet), each tappable to open. It also lays the small, reusable packet-processing
+ source-UI foundation that the next rich-chat phase (9b, the agent timeline) builds on.

## How it works (end-to-end walkthrough)

The backend already streams the pieces we need, mixed into the same NDJSON packet stream the chat
already consumes:
- **`citation_info`** packets — `{citation_number, document_id}` — one per first-cite, arriving just
  before the answer text that contains the marker.
- **document** packets — `search_tool_documents_delta` and `open_url_documents` — each carrying a
  list of `SearchDoc`s, emitted by the search/URL tools *before* the answer.
- **`message_start.final_documents`** — the authoritative cited-doc set for the turn.
- The inline marker itself is already baked into the answer text as a markdown link
  **`[[N]](link)`** where `link = search_doc.link or ""` — so for a normal web/document source the
  marker's URL *is* the document link.

The mobile chat controller already stores **every** packet on the assistant message
(`node.packets`) without inspecting its type, and `usePacketDisplay` already hands all of a node's
packets to the one matched renderer. So nothing new is needed to *receive* citation/document
packets — the work is to *process* and *render* them:

1. **Type the new packets.** Add the three packet shapes + a `SearchDoc` contract so the stream is
   strongly typed (purely additive to `streamingModels.ts`).
2. **Process them into state.** A new pure processor (`messageProcessor.ts`, a small mobile port of
   web's `packetProcessor`) folds the packets into a `ProcessedMessageState`: a `citationMap`
   (`{[N]: document_id}`), a deduped ordered `citations[]`, a `documentMap`
   (`document_id → SearchDoc`), and completion (`isComplete`/`stopReason`). The processor is
   incremental-capable (a cursor + reset when the packet array shrinks), but 9a drives it with a
   full pass per flush (see step 3), so the cursor isn't relied upon yet — 9b can host it
   incrementally.
3. **Host the processor.** `usePacketDisplay` is the mobile analog of web's `usePacketProcessor`:
   it recomputes `processed` with a `useMemo` (from a fresh `createInitialState`, a full pass over
   `node.packets`) whenever the packet array changes — cheap at chat scale, and lint-clean (the
   `react-hooks/refs` rule forbids the ref-during-render pattern web uses). It returns
   `{ renderer, packets, processed }`; this `processed` value is the **channel** that both this
   phase's Sources UI and 9b's timeline renderers read.
4. **Render inline markers.** The answer keeps flowing through the existing
   `MessageTextRenderer → useTypewriter → StreamingMarkdown` path. `StreamingMarkdown` gains an
   `onLinkPress` prop wired to the native markdown renderer's tap callback. When a `[N]` link (or
   any markdown link) is tapped, the handler opens its URL in the in-app browser
   (`expo-web-browser`); an empty-URL marker (a file source with no link) is a no-op (those sources
   are reachable via the Sources sheet). No custom inline component is needed — the marker is a
   styled, tappable link.
5. **Render the Sources surface.** Once the answer is complete and the turn has any
   citations/documents, `MessageRow` renders a **"Sources" button** (a small stack of ≤3 source
   icons + a count) under the answer. Tapping it opens a **bottom-sheet Modal** listing the sources
   in three sections — **Cited Sources** (in citation order), **More** (found-but-not-cited), and
   **User Files** — each a **source row** (icon/favicon + title + source/updated-at + snippet). A
   row tap opens that document (browser for linked docs; a graceful no-op/toast for file docs, which
   have no mobile preview yet).

## Component interaction

```
 NDJSON stream ─► useChatController (stores every packet on node.packets)   [UNCHANGED]
                        │
                        ▼
 MessageRow.AssistantMessage
   │  const { renderer, packets, processed } = usePacketDisplay(node)   [MODIFIED: hosts processor]
   │        └─ useMemo: processPackets(createInitialState(nodeId), packets)   [NEW · FOUNDATION]
   │              → processed { citationMap, citations[], documentMap, isComplete, stopReason }
   │
   ├─► <AgentTimeline isLoading={!hasContent && !processed.isComplete}/>          [shell, unchanged]
   │
   ├─► <Renderer packets={packets} processed={processed}/>              [contract +processed]
   │        └─ MessageTextRenderer                                      [MODIFIED]
   │             accumulateContent → useTypewriter → <StreamingMarkdown onLinkPress/>  [MODIFIED]
   │                                                     └─ onLinkPress(url) → openUrl(url)
   │
   └─► if processed.isComplete && hasSources(processed):                [NEW · 9a]
         <CitedSourcesBar docs count onPress={openSheet}/>
         <CitedSourcesSheet visible processed onClose/>
              └─ sections Cited / More / User Files
                   └─ <SourceRow doc onPress={() => openSource(doc)}/>  [NEW · FOUNDATION]
                        └─ <SourceIcon doc/>  (favicon | file-text)     [NEW · FOUNDATION]
                        └─ openSource(doc): link→browser | file→toast/no-op | none→no-op  [NEW · FOUNDATION]
```

## Key components

- **`messageProcessor.ts`** — pure incremental packet→state processor (NEW · FOUNDATION; 9b extends
  it with grouping/steps).
- **`contracts/documents.ts`** — `SearchDoc`, `StreamingCitation`, `CitationMap` types (NEW ·
  FOUNDATION; 9b's search/fetch renderers reuse `SearchDoc`).
- **`usePacketDisplay.ts`** — hosts the processor, returns `processed` (MODIFIED · FOUNDATION — the
  channel 9b renderers read).
- **`registry.ts`** — `MessageRendererProps` carries `processed` instead of bare `isComplete`
  (MODIFIED · FOUNDATION).
- **`openSource.ts`** — resolve a `SearchDoc` to an action + execute it (NEW · FOUNDATION; 9b result
  rows + 9c "view source" reuse).
- **`SourceIcon.tsx` / `SourceRow.tsx`** — a source's icon and list row (NEW · FOUNDATION; 9b renders
  the same rows inline).
- **`citations.ts`** — pure `selectSources(processed)` (Cited/More/Files split) + `domainOf`/
  `faviconUrl` helpers (NEW · 9a).
- **`CitedSources.tsx`** — the "Sources" bar + the bottom-sheet list (NEW · 9a).
- **`MessageTextRenderer.tsx` / `StreamingMarkdown.tsx`** — inline `onLinkPress` wiring (MODIFIED · 9a).
- **`MessageRow.tsx`** — reads `processed`; renders the Sources footer (MODIFIED · 9a).
- **`streamingModels.ts`** — the three new packet types + `MessageStart.final_documents` (MODIFIED).

## End-to-end scenario

1. User asks a question that triggers a search. The search tool emits `search_tool_documents_delta`
   with 6 `SearchDoc`s → the processor fills `documentMap` with all 6.
2. `message_start` arrives with `final_documents` (the cited subset) → processor upserts them
   (already present) and marks the answer as coming.
3. The answer streams: `citation_info {citation_number:1, document_id:"d1"}` then the delta text
   `… as reported [[1]](https://acme.com/report) …`. The processor sets `citationMap[1]="d1"` and
   pushes `{citation_num:1, document_id:"d1"}` to `citations[]`. The typewriter reveals the text;
   `[1]` shows as a styled link.
4. User taps `[1]` → `onLinkPress("https://acme.com/report")` → opens the in-app browser on that
   page. (No citation-state lookup needed — the URL was baked into the marker.)
5. `stop` arrives → `processed.isComplete = true`. `MessageRow` now renders the **Sources** button
   showing 2 stacked favicons + "Sources · 6".
6. User taps **Sources** → the bottom sheet opens: **Cited Sources** lists the 1–2 docs referenced
   in the answer (citation order); **More** lists the other found docs; each row shows a favicon,
   the document title, its domain + updated date, and a 2-line snippet. Tapping a row opens that
   document in the in-app browser.

## Sequence of key operations

1. Controller appends each streamed packet to `node.packets` (unchanged).
2. `MessageRow.AssistantMessage` calls `usePacketDisplay(node)`.
3. `usePacketDisplay` recomputes `processed` via `useMemo` — a full pass of `messageProcessor` over
   `node.packets` (citationMap, citations, documentMap, isComplete) whenever the array changes.
4. The text renderer renders the answer markdown with an `onLinkPress` handler.
5. On marker/link tap → open the URL in the in-app browser (or no-op for empty-URL file markers).
6. On `stop`/complete → `MessageRow` shows the Sources button when `hasSources(processed)`.
7. On Sources tap → open the sheet; `selectSources(processed)` splits docs into Cited/More/Files.
8. On a source-row tap → `openSource(doc)` opens the doc (browser / toast).

## Key decisions & why

- **Mobile builds its own small processor (not shared with web).** Web's `usePacketProcessor`/
  `packetProcessor` stays web-only (per roadmap); the mobile chat layer is native by decision. We
  port only the incremental-cursor + reset-on-shrink shape — the part 9b needs to extend. (Ref:
  `01-research.md` web-structure + roadmap PR 2 decision.)
- **Inline markers are styled tappable links, not custom chips.** The native markdown renderer
  (`react-native-enriched-markdown`) exposes only `markdownStyle` + `onLinkPress` — no custom node
  hook — so inline chip components are impossible without heavy, fragile text-segmentation. The
  backend bakes the doc URL into the marker, so a plain `onLinkPress(url)` gives full behavior
  parity. (Ref: `01-research.md` Q3 + the `citation_processor.py:496,506` fact.)
- **The rich UI lives in the Sources sheet.** Custom components (icons, rows, sections) have no
  renderer constraint there, so that's where web-faithful structure goes — mirroring web's own
  *mobile* DocumentsSidebar, which is already a bottom Modal titled "Sources."
- **Establish the `processed` channel + shared source layer now (Approach C).** 9b (the very next
  phase) needs a processor to extend with grouping and needs `SearchDoc`/`SourceRow`/`SourceIcon`/
  `openSource` for its search/fetch sub-renderers. Building these minimal seams now (each justified
  by a concrete 9b consumer) avoids a rewrite; grouping itself is deliberately **not** built yet.
- **Drop the streaming-robustness machinery (reject B).** Because document packets precede the
  answer and the marker carries its own URL, forward-reference gating and a marker-rewrite transform
  buy almost nothing at chat scale — so they're omitted.

## What existing behavior changes

- Inline `[N]` markers (and any markdown links) in assistant answers become **tappable** and open in
  the in-app browser; today nothing opens content links. No change to how text/markdown looks
  otherwise.
- A **"Sources" button + sheet** appears under completed answers that have citations/documents.
- No change to user messages, errors, the timeline shell, streaming, or any non-answer surface.
- No backend, DB, or API changes.
