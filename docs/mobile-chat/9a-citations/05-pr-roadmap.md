> Status: active · Task: 9a-citations · Source plan: 04-implementation-plan.md

# Mobile Chat 9a — Citations & Cited Sources — PR Roadmap

## Overview

**Single PR** (owner decision at GATE 3 — ship 9a as one chunk rather than splitting the ~1150 LOC
into two). It exceeds the ~500-700 target band but is one coherent vertical feature; the owner
opted to review it together.

| PR | Title | Est. LOC | Depends on | Key deliverable |
|----|-------|----------|------------|-----------------|
| 1 | `feat(mobile): chat citations + cited sources` | ~1050-1250 | — | Type + process citation/document packets; inline `[N]` (and answer links) open in the in-app browser; a "Sources" button + bottom sheet lists cited/found documents. Establishes the reusable processing + source-UI foundation for 9b. |

## Sequence (internal build order within the one PR)

```
1. contracts/documents.ts + streamingModels.ts   (types)
2. messageProcessor.ts                            (pure processor · FOUNDATION)
3. usePacketDisplay.ts + registry.ts              (host processor, `processed` channel · FOUNDATION)
4. openSource.ts + StreamingMarkdown + MessageTextRenderer   (inline tap-routing)
5. citations.ts + SourceIcon + SourceRow          (source layer · FOUNDATION)
6. CitedSources.tsx + MessageRow wiring           (Sources bar & sheet · 9a UI)
7. fixtures + tests
```

Build the pure/foundation layers before the UI that consumes them. 9b (agent timeline) later extends
`messageProcessor` with grouping and reuses `SearchDoc`/`SourceRow`/`SourceIcon`/`openSource`.

---

## PR 1 — `feat(mobile): chat citations + cited sources`

- **Goal:** Ship the full 9a slice — process the citation/document packets already arriving on
  `node.packets`, make inline `[N]` markers (and answer links) tappable → in-app browser, and render
  a "Sources" button under completed answers that opens a bottom sheet listing the source documents.
- **Scope (in):**
  - Packet contracts + types (`SearchDoc`, `CitationInfo`, document packets,
    `MessageStart.final_documents`).
  - The incremental `messageProcessor` (`citationMap` / `citations[]` / `documentMap` / completion),
    hosted in `usePacketDisplay` → `processed`; `MessageRendererProps` carries `processed`.
  - `openSource`/`openUrl` + `onLinkPress` passthrough in `StreamingMarkdown`, wired in
    `MessageTextRenderer`.
  - `selectSources` selector; `SourceIcon` / `SourceRow`; `CitedSourcesBar` + `CitedSourcesSheet`;
    footer wiring in `MessageRow`.
  - Fixtures + unit/component tests.
- **Out of scope (deferred):** inline chip components / hover cards (platform-blocked); turn/tab
  packet **grouping** + timeline steps (9b); a per-connector source-logo set; an in-app document
  preview for file sources (they degrade to a toast/no-op); a live mid-stream citation counter.
- **Files:**
  | File | New/Modified | Slice |
  |------|--------------|-------|
  | `mobile/src/chat/contracts/documents.ts` | new | `SearchDoc` / `StreamingCitation` / `CitationMap` |
  | `mobile/src/chat/streamingModels.ts` | modified | 3 packet types + `MessageStart.final_documents` + `ObjTypes` |
  | `mobile/src/chat/messageProcessor.ts` | new | `ProcessedMessageState`, `createInitialState`, `processPackets` |
  | `mobile/src/chat/openSource.ts` | new | `documentTarget` / `openUrl` / `openSource` |
  | `mobile/src/chat/citations.ts` | new | `selectSources` + `domainOf` / `faviconUrl` |
  | `mobile/src/hooks/usePacketDisplay.ts` | modified | host processor; return `{ renderer, packets, processed }` |
  | `mobile/src/components/chat/renderers/registry.ts` | modified | `MessageRendererProps → { packets, processed }` |
  | `mobile/src/components/chat/renderers/MessageTextRenderer.tsx` | modified | `processed.isComplete`; `onLinkPress` |
  | `mobile/src/components/chat/StreamingMarkdown.tsx` | modified | `onLinkPress` passthrough |
  | `mobile/src/components/chat/SourceIcon.tsx` | new | favicon / `file-text` fallback |
  | `mobile/src/components/chat/SourceRow.tsx` | new | tappable source row |
  | `mobile/src/components/chat/CitedSources.tsx` | new | `CitedSourcesBar` + `CitedSourcesSheet` |
  | `mobile/src/components/chat/MessageRow.tsx` | modified | read `processed`; render Sources footer + sheet |
  | `mobile/src/chat/__tests__/fixtures.ts` | modified | `makePacket` / `makeCitationPacket` / `makeSearchDoc(+Packet)` |
  | `mobile/src/chat/__tests__/messageProcessor.test.ts` | new | dedup/order, documentMap, final_documents, reset, cursor, isComplete |
  | `mobile/src/chat/__tests__/citations.test.ts` | new | `selectSources` split/order/dedup + helpers |
  | `mobile/src/chat/__tests__/openSource.test.ts` | new | `documentTarget` branches |
  | `mobile/src/components/chat/__tests__/SourceRow.test.tsx` | new | render + `onPress` → `openSource` |
  | `mobile/src/components/chat/__tests__/CitedSources.test.tsx` | new | sheet sections + bar visibility |
- **Est. size:** ~1050-1250 LOC (production + tests).
- **Depends on:** —
- **Feature-flag state:** N/A — additive; `main` stays releasable.
- **Tests on merge:** unit (jest) + RN Testing Library. Directly covered: citation/document state
  building from a mocked packet stream (`messageProcessor`), the `selectSources` split, `documentTarget`
  routing, a `SourceRow` tap → `openSource`, and the sheet's section rendering. **Not** exercised by
  the unit suite (pending on-device verification): the native `onLinkPress` event shape and the
  inline-marker → `openUrl` plumbing through `StreamdownText`, and the `MessageRow` completed-answer
  footer gating. Gate: `bun run typecheck`, `bun run lint`, `bunx jest`.
- **Drift checkpoint:** Before/at implementation, **device-verify the `react-native-enriched-markdown`
  `onLinkPress` `event` shape** (expected `{ url }`) — the one platform unknown the inline path rests
  on (unit tests mock it; a dev build confirms it). Also confirm whether `[[n]]()` file markers render
  tappable (the sheet is the reliable fallback regardless).
