> Status: active · Task: 9a-citations

# Mobile Chat 9a — Citations & Cited Sources — Detailed Design

## Database design

**N/A — client-only feature.** No backend, schema, or API changes. All packet types already exist
on the wire; 9a only consumes them on the mobile client.

## Class / interface design

### `ProcessedMessageState` (new · FOUNDATION) — `mobile/src/chat/messageProcessor.ts`
The incremental processor state for one assistant message. 9a fields only; deliberately
grouping-free so 9b can add `groupedPacketsMap`/`toolGroups`/steps without reshaping what exists.

```ts
interface ProcessedMessageState {
  nodeId: number;
  nextPacketIndex: number;                     // cursor — process-only-new
  citationMap: Record<number, string>;         // { citation_number: document_id }
  citations: StreamingCitation[];              // deduped, first-cite order
  seenCitationDocIds: Set<string>;             // dedup guard
  documentMap: Map<string, SearchDoc>;         // document_id → doc
  isComplete: boolean;                         // saw MESSAGE_END or STOP
  stopReason?: StopReason;
}

function createInitialState(nodeId: number): ProcessedMessageState;
function processPackets(state: ProcessedMessageState, rawPackets: Packet[]): ProcessedMessageState;
```

- `processPackets`: if `nextPacketIndex > rawPackets.length` → `createInitialState(nodeId)`
  (array replaced by a *shorter* one); else loop `[nextPacketIndex, len)` and dispatch each, then set
  `nextPacketIndex = len`. Mutates `citationMap`/`documentMap`/`citations` in place (web pattern);
  returns the same object.
  - **Reset caveat:** this shrink check only catches a *shorter* replacement. A same-length or
    longer regenerate/history-load would reuse stale state under an incremental host. 9a sidesteps
    this entirely — `usePacketDisplay` passes a *fresh* `createInitialState` every render (useMemo),
    so nothing is reused. A future incremental host (9b) must reset on packet-array *identity*
    change, not just length.
- Per-packet dispatch (by `obj.type`):
  - `CITATION_INFO` → `citationMap[n] = document_id`; if `!seenCitationDocIds.has(document_id)` →
    add + push `{ citation_num, document_id }`.
  - `SEARCH_TOOL_DOCUMENTS_DELTA` / `OPEN_URL_DOCUMENTS` → for each doc with a `document_id`,
    `documentMap.set(document_id, doc)`.
  - `MESSAGE_START` → if `final_documents`, upsert each into `documentMap`.
  - `MESSAGE_END` / `STOP` → `isComplete = true`; `STOP` also captures `stopReason`.
  - anything else → ignored (text/section_end/error handled elsewhere).

### `SearchDoc` / `StreamingCitation` / `CitationMap` (new · FOUNDATION) — `mobile/src/chat/contracts/documents.ts`
Mobile-native port of the backend `SearchDoc` (full field set — 9b's search renderer needs the
extras). Types only.

```ts
interface SearchDoc {
  document_id: string;
  semantic_identifier: string;
  link: string | null;
  blurb: string;
  source_type: string;
  score: number | null;
  updated_at: string | null;          // ISO-8601
  match_highlights: string[];
  metadata: Record<string, string | string[]>;
  is_internet: boolean;
  chunk_ind: number;
  boost: number;
  hidden: boolean;
  primary_owners: string[] | null;
  secondary_owners: string[] | null;
  is_relevant: boolean | null;
  relevance_explanation: string | null;
  file_id: string | null;
}
interface StreamingCitation { citation_num: number; document_id: string; }
type CitationMap = Record<number, string>;
```

### `SourceTarget` + `openSource` (new · FOUNDATION) — `mobile/src/chat/openSource.ts`
Pure resolver + thin effectful executor. One router for inline taps and source rows.

```ts
type SourceTarget =
  | { kind: "browser"; url: string }
  | { kind: "file"; fileId: string }
  | { kind: "none" };

function documentTarget(doc: SearchDoc): SourceTarget;   // link → browser; file_id & !link → file; else none
function openUrl(url: string): void;                     // WebBrowser.openBrowserAsync (in-app)
function openSource(doc: SearchDoc): void;
```

- `openSource`: `documentTarget(doc)` → `browser` = `openUrl`; `file` = a heads-up toast via the
  global `toast` helper ("Preview isn't available on mobile yet") — no mobile doc viewer in 9a;
  `none` = no-op. (No caller callback — the toast is fired internally, so `SourceRow` just calls
  `openSource(doc)`.)

### `PacketDisplay` (modified · FOUNDATION) — `mobile/src/hooks/usePacketDisplay.ts`
```ts
interface PacketDisplay {
  renderer: MessageRenderer | null;
  packets: Packet[];
  processed: ProcessedMessageState;   // replaces the old top-level `isComplete`
}
```
Hosts the processor and returns `processed`; `renderer` via `findRenderer(packets)`.

> **Implementation note (deviation from the ref design):** the mobile `react-hooks/refs` lint rule
> forbids reading/writing `ref.current` during render (web's `usePacketProcessor` does exactly
> that). So 9a hosts the processor via `useMemo(() => processPackets(createInitialState(nodeId),
> packets), [nodeId, packets])` — a full pass per flush (cheap at chat scale) instead of a
> render-mutated incremental ref. The `messageProcessor` module stays incremental-capable
> (cursor + reset-on-shrink) for 9b, which can host it via a lint-compatible incremental pattern.

### `MessageRendererProps` (modified · FOUNDATION) — `.../renderers/registry.ts`
```ts
interface MessageRendererProps {
  packets: Packet[];
  processed: ProcessedMessageState;   // was: isComplete: boolean → now processed.isComplete
}
```

## New files

| File | Responsibility |
|------|----------------|
| `mobile/src/chat/messageProcessor.ts` | Pure incremental packet→`ProcessedMessageState` processor (FOUNDATION). |
| `mobile/src/chat/contracts/documents.ts` | `SearchDoc` / `StreamingCitation` / `CitationMap` types (FOUNDATION). |
| `mobile/src/chat/openSource.ts` | `documentTarget` + `openSource`/`openUrl` (FOUNDATION). |
| `mobile/src/chat/citations.ts` | `selectSources(processed)` split + `domainOf`/`faviconUrl` (9a). |
| `mobile/src/components/chat/SourceIcon.tsx` | Favicon (public `expo-image`) or `file-text` fallback for a doc (FOUNDATION). |
| `mobile/src/components/chat/SourceRow.tsx` | Tappable source row: icon + title + meta + snippet (FOUNDATION). |
| `mobile/src/components/chat/CitedSources.tsx` | `CitedSourcesBar` (button) + `CitedSourcesSheet` (bottom sheet) (9a). |
| `mobile/src/chat/__tests__/messageProcessor.test.ts` | Processor unit tests. |
| `mobile/src/chat/__tests__/citations.test.ts` | `selectSources` + helpers. |
| `mobile/src/chat/__tests__/openSource.test.ts` | `documentTarget` branches. |
| `mobile/src/components/chat/__tests__/SourceRow.test.tsx` | Row render + onPress. |
| `mobile/src/components/chat/__tests__/CitedSources.test.tsx` | Sheet sections + bar visibility. |

## File structure (tree)

```
mobile/src/
├── chat/
│   ├── streamingModels.ts                      (modified: +3 packet types, +MessageStart.final_documents, +ObjTypes)
│   ├── messageProcessor.ts                     (new · FOUNDATION)
│   ├── openSource.ts                           (new · FOUNDATION)
│   ├── citations.ts                            (new · 9a)
│   ├── contracts/
│   │   └── documents.ts                        (new · FOUNDATION)
│   └── __tests__/
│       ├── fixtures.ts                         (modified: +makePacket/makeCitationPacket/makeSearchDoc)
│       ├── messageProcessor.test.ts            (new)
│       ├── citations.test.ts                   (new)
│       └── openSource.test.ts                  (new)
├── hooks/
│   └── usePacketDisplay.ts                     (modified: host processor, return `processed`)
└── components/chat/
    ├── renderers/
    │   ├── registry.ts                         (modified: MessageRendererProps → {packets, processed})
    │   └── MessageTextRenderer.tsx             (modified: processed.isComplete, onLinkPress)
    ├── StreamingMarkdown.tsx                   (modified: +onLinkPress passthrough)
    ├── MessageRow.tsx                          (modified: read processed, render Sources footer)
    ├── SourceIcon.tsx                          (new · FOUNDATION)
    ├── SourceRow.tsx                           (new · FOUNDATION)
    ├── CitedSources.tsx                        (new · 9a)
    └── __tests__/
        ├── SourceRow.test.tsx                  (new)
        └── CitedSources.test.tsx               (new)
```

## What each file will contain

- **`streamingModels.ts`** — add `PacketType.CITATION_INFO="citation_info"`,
  `SEARCH_TOOL_DOCUMENTS_DELTA="search_tool_documents_delta"`, `OPEN_URL_DOCUMENTS="open_url_documents"`;
  interfaces `CitationInfo {citation_number:number; document_id:string}`,
  `SearchToolDocumentsDelta {documents: SearchDoc[]}`, `OpenUrlDocuments {documents: SearchDoc[]}`;
  add `final_documents?: SearchDoc[] | null` to `MessageStart`; add the three to the `ObjTypes`
  union. `import { SearchDoc } from "@/chat/contracts/documents"`. (Do NOT add `citation_start/end`
  — backend never emits them.)
- **`messageProcessor.ts`** — `createInitialState`, `processPackets`, the per-type handlers above.
  Pure; no React. Discriminates on `obj.type`.
- **`contracts/documents.ts`** — the three types above. No logic.
- **`openSource.ts`** — `documentTarget`, `openUrl` (`expo-web-browser`), `openSource`.
- **`citations.ts`** — `selectSources(processed): { cited: SearchDoc[]; more: SearchDoc[];
  files: SearchDoc[]; hasSources: boolean; iconDocs: SearchDoc[] }`:
  - `cited` = `citations` mapped through `documentMap` (skip missing), in citation order, deduped.
  - `files` = docs with `file_id` (pulled out of cited/more into their own section).
  - `more` = remaining `documentMap` values not in `cited` and not files.
  - `iconDocs` = first ≤3 of `cited` (fallback `more`) for the bar's icon stack.
  - `hasSources` = `citations.length > 0 || documentMap.size > 0`.
  - `domainOf(link)`, `faviconUrl(link)` (public favicon service URL; `null` if no host).
- **`SourceIcon.tsx`** — `SourceIcon({ doc, size=18 })`: if `doc.link` yields an http host →
  `<Image source={faviconUrl(link)}>` (`expo-image`, public, `onError` → `file-text`); else
  `<Icon as={SvgFileText}>`. (Minimal — full per-connector logo map is out of scope, flagged.)
- **`SourceRow.tsx`** — `SourceRow({ doc, onPress })`: `Card variant="secondary" onPress`; layout:
  `[<SourceIcon doc/> + <Text font="main-ui-action" color="text-05" numberOfLines={1}>{semantic_identifier}</Text>]`,
  `<Text font="secondary-body" color="text-02">{domainOf(link) ?? source_type} · {timeAgo(updated_at)}</Text>`,
  `<Text font="secondary-body" color="text-03" numberOfLines={2}>{(match_highlights[0] ?? blurb).slice(0,200)}</Text>`.
- **`CitedSources.tsx`** — two exports:
  - `CitedSourcesBar({ iconDocs, count, onPress })` — a `Pressable`/`Button`-style pill: a stack of
    ≤3 `SourceIcon`s (overlapping) + `Text` "Sources · {count}". `accessibilityRole="button"`.
  - `CitedSourcesSheet({ visible, onClose, processed })` — bottom-sheet `Modal` mirroring
    `FilePickerSheet` chrome (scrim `Pressable`, inner `rounded-t-24 … px-16 pt-16`, safe-area
    bottom, header "Sources" + close `SvgX`, `ScrollView max-h`). Body = `selectSources(processed)`
    → up to three labeled sections (`Cited Sources` / `More` / `User Files`) each a `Separator` +
    `Text` header + `SourceRow`s; a row's `onPress` = `openSource(doc)`.
- **`usePacketDisplay.ts`** — replace the `useMemo` body: `const stateRef =
  useRef(createInitialState(node.nodeId))`; if `stateRef.current.nodeId !== node.nodeId` or shrink →
  reseed; `stateRef.current = processPackets(stateRef.current, node.packets)`; `renderer =
  useMemo(() => findRenderer(node.packets), [node.packets])`; return `{ renderer, packets:
  node.packets, processed: stateRef.current }`.
- **`registry.ts`** — change `MessageRendererProps` to `{ packets; processed }`.
- **`MessageTextRenderer.tsx`** — read `processed.isComplete` (was `isComplete`); build
  `onLinkPress = useCallback((url) => { if (url) openUrl(url); }, [])`; pass to `StreamingMarkdown`.
  (`matches` unchanged.)
- **`StreamingMarkdown.tsx`** — add `onLinkPress?: (url: string) => void`; pass
  `onLinkPress={(e) => onLinkPress?.(e.url)}` to `<StreamdownText>`.
- **`MessageRow.tsx`** — `AssistantMessage`: destructure `processed` from `usePacketDisplay`; use
  `processed.isComplete` for `hasContent`/`AgentTimeline isLoading`; after `<Renderer>`, when
  `processed.isComplete && hasSources`, render `<CitedSourcesBar>` + `<CitedSourcesSheet>` with a
  local `sheetVisible` state. Update the `memo` comparator only if needed (still keyed on
  `packets.length`, which advances with new citation/doc packets).
- **`fixtures.ts`** — `makePacket(obj, placement?)`, `makeCitationPacket(n, docId)`,
  `makeSearchDoc(overrides)`, `makeSearchDocsPacket(docs, type?)`.

## Integration points

- **`useChatController.ts`** — unchanged; already stores every wrapped packet on `node.packets`.
- **`chatHistory.ts`** — unchanged; `processRawChatHistory` already loads historical `packets` per
  assistant turn → the processor rebuilds citation state on load.
- **`api/chat/stream.ts`** — unchanged; `isPacket` already routes wrapped citation/document packets.
- **`registry.ts` `RENDERERS`** — unchanged (still `[MessageTextRenderer]`); citation/doc packets
  ride the same array and `MessageTextRenderer.matches` still fires. 9b appends new renderer entries.
- **`expo-web-browser`** — already a dependency (used by auth SSO); new usage in `openSource`.
- **`timeAgo`** — reuse `mobile/src/lib/time.ts` (already used by project files) for the row date.

## Important notes before implementation

- **The empty-parens `[[n]]()` file marker is the key edge case.** For a file/internal source
  (`link == ""`), the marker may not render as a tappable link in enriched-markdown. 9a's behavior:
  the inline tap is best-effort (no-op if no URL); the file source is reliably reachable in the
  **Sources sheet** under "User Files." **Verify on a device build** whether `[[n]]()` renders as
  text or a link; if a tappable-but-empty link is desired, a 1-line normalize (`]]()` → a sentinel
  href) is the fallback — but keep it out of the default path.
- **`onLinkPress` fires for ALL links**, not just citations (ordinary markdown links in answers too).
  That's intended — open them in the in-app browser. Confirm the exact `event` payload shape
  (`{ url }`) on device.
- **Favicons are public** — use plain `expo-image`, NOT `BearerImage` (favicon URLs aren't
  auth-keyed). `onError` must fall back to the generic icon so a missing favicon never breaks a row.
- **Source-icon coverage is intentionally minimal** (favicon or `file-text`). Mobile has no
  per-connector logo set; porting the full ~40-source map is out of scope for 9a (flag as a
  follow-up; 9b may expand the map).
- **Bar visibility mirrors web**: show only when `processed.isComplete && hasSources` — avoids
  mid-stream layout shift; sources are populated by the time the answer completes.
- **In-place mutation + stable ref**: the processor mutates its state and `usePacketDisplay` returns
  the same ref each render. `MessageRow`/`AssistantMessage` re-render on each packet flush (memo on
  `packets.length`), so `processed` reads are fresh; do NOT `React.memo` a Sources child on
  `processed` identity — compare primitive proxies (`citations.length`, `documentMap.size`) if
  memoization is later needed (the 9b perf path).
- **Reset semantics**: reset the processor on `nodeId` change (new message) and on packet-array
  shrink (regenerate / history replace) — mirrors web; without it a regenerate would double-count.
- **Route collision**: do NOT touch `/sources/[id]` (project files). The cited-sources surface is a
  Modal, no route.
- **Testing**: processor + selector + `documentTarget` are pure → unit tests (dedup, ordering,
  `final_documents` seeding, reset-on-shrink, file/link/none targets). `SourceRow`/`CitedSourcesSheet`
  → RN Testing Library (render sections, onPress → openSource). Mock `expo-web-browser` +
  `expo-image`. Import jest globals from `@jest/globals`; use `@/components/ui/text` in test
  assertions.
