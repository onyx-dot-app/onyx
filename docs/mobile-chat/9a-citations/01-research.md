> Status: draft · Task: 9a-citations

# Mobile Chat 9a — Citations & Cited Sources — Research

## Requirement

Port Onyx **web's chat citations + cited-sources experience** to the mobile React Native app
(`mobile/`): type + process the citation/document streaming packets, render inline `[N]`
citation markers in the streamed answer, and render a cited-sources surface (a "Sources"
affordance + a list of source rows), matching web's behaviour and — where the platform allows —
its structure. This is sub-phase **9a** of the deferred rich-chat work in
`docs/mobile-chat/05-pr-roadmap.md` (PR 9a–9e). Web is the design source of truth.

## Clarifications (Q&A)

**Q1 — Which PR 9 sub-phase?** → **9a (citations/sources).** (Roadmap's recommended-first; the
agent-timeline work we analysed is 9b, deferred.)

**Q2 — Kick-off process?** → Full feature-flow (research → approaches → HLD → detailed → plan),
gated docs under `docs/mobile-chat/`, grilled before any code.

**Q3 (the load-bearing one) — Inline `[N]` marker treatment, given the RN markdown renderer has
NO custom-node hook?** → **Styled, tappable `[N]` links** (tap → open the source via
`onLinkPress`); the rich, web-faithful UI goes in the **Sources button + cited-sources sheet**
(which have no renderer constraint). Superscript styling of the marker is optional. Real inline
`SourceTag`-style chips (web's look) would require heavy text-segmentation that fights the
streaming markdown renderer — **rejected** as too fragile for the value. Hiding markers entirely —
**rejected** (loses the claim→source bond).

### Why the constraint exists (recorded so it isn't re-litigated)
- **Web** renders the answer with `react-markdown` (a JS element tree); Onyx overrides the `a`
  node (`MemoizedAnchor`) to swap each `[[N]](url)` link for a custom `SourceTag` chip + hover
  card. Every node is a React element it can replace.
- **Mobile** uses `react-native-streamdown` → `react-native-enriched-markdown`, a **native**
  renderer (md4c + native text primitives, chosen to avoid the WebView tax + streaming jank). Its
  entire public customization surface is `markdownStyle` (per-node colour/weight/underline) +
  `onLinkPress`/`onLinkLongPress` tap callbacks. **No custom node renderers / render overrides**
  (confirmed against the published API reference). So a `[N]` link cannot be replaced by a custom
  component inline; it can only be styled + made tappable. The **hover card** can't port literally
  regardless (no hover on touch → tap-to-open is the equivalent).

## Current status & reuse (codebase scan — exact paths)

### Render path & the dispatch seam
- `mobile/src/components/chat/MessageList.tsx` → `MessageRow` per item; no per-packet logic.
- `mobile/src/components/chat/MessageRow.tsx` — `AssistantMessage` calls `usePacketDisplay(node)`
  → `{renderer, packets, isComplete}`, renders `<AgentTimeline>` (shell) then
  `<Renderer packets isComplete/>` in a `px-12` inset. Memoized on `node.packets.length`.
- `mobile/src/hooks/usePacketDisplay.ts` — **the "one group" stub**; header comment: "Core = one
  group; PR 9 adds real grouping." Passes ALL `node.packets` to the single matched renderer.
- `mobile/src/components/chat/renderers/registry.ts` — dispatch seam:
  `MessageRenderer { matches(packets):boolean; Component }`,
  `MessageRendererProps { packets: Packet[]; isComplete: boolean }`, `findRenderer` first-match.
  Only `MessageTextRenderer` registered ("PR 9 adds rich renderers").
- `mobile/src/components/chat/renderers/MessageTextRenderer.tsx` —
  `matches: packets.some(isChatPacket)`; Component: `accumulateContent(packets)` (concat
  `content` of `message_start`/`message_delta`) → `useTypewriter` → `<StreamingMarkdown>`.

### Markdown renderer
- `mobile/src/components/chat/StreamingMarkdown.tsx` — wraps
  `<StreamdownText markdown markdownStyle flavor="github" selectable>`. Today passes NO tap
  callback. `StreamdownText` **inherits all `EnrichedMarkdownText` props** (incl.
  `onLinkPress`/`onLinkLongPress` → `event.url`) **plus** `remendConfig`. `markdownStyle.link` =
  `--action-link-05` + underline (global; no per-link styling).
- `mobile/src/hooks/useTypewriter.ts` — reveals `target` by growing char-prefix slice
  (~180cps mid-stream). Markers pass through as chars → a partial `[1` can momentarily show;
  citation parsing must run on the **full accumulated content**, not `displayed`.

### Packet contracts & ingestion
- `mobile/src/chat/streamingModels.ts` — `PacketType` enum (`message_start/delta/end`, `stop`,
  `section_end`, `error`), `Packet {placement, obj}`, `Placement {turn_index, tab_index?,
  sub_turn_index?, model_index?}`, `ObjTypes` union. **Extension point** for new packet types.
  Two-tier discrimination convention (wrapped `obj.type` vs root-by-field) enforced in
  `mobile/src/api/chat/stream.ts` (`isPacket = "obj" in e && "placement" in e`).
- `mobile/src/chat/contracts/projects.ts` — project read-models; candidate home for a
  `SearchDoc`/document contract (`mobile/src/chat/contracts/`).
- `mobile/src/hooks/useChatController.ts` — appends **every** wrapped packet to `node.packets`
  via a debounced flush (`{...node, packets:[...node.packets, ...pending]}`); **no `obj.type`
  inspection** → new citation/document packet types reach the renderer with zero controller change.
- `mobile/src/chat/chatHistory.ts` — `processRawChatHistory` aligns `packets[agentIdx]` per
  assistant turn → historical citations load through here.

### Reuse primitives
- `mobile/src/components/ui/card.tsx` — `Card` (`variant`: primary/secondary/tertiary/borderless;
  `rounded-12 p-16`; optional `onPress`).
- `mobile/src/components/ui/line-item-button.tsx` — `LineItemButton` (full-width tappable row:
  icon + title + description + `rightChildren`; no snippet slot).
- `mobile/src/components/chat/FilePickerSheet.tsx` — **the bottom-sheet Modal pattern**
  (RN `Modal` transparent slide, scrim `Pressable`, inner `rounded-t-24`, safe-area bottom inset).
- `mobile/src/components/chat/{ProjectFileList,FileCard}.tsx` — row/card shapes.
- `mobile/src/components/ui/BearerImage.tsx` — auth'd `expo-image` (for API images). **Note:**
  public web favicons are NOT auth'd → use plain `expo-image`, not `BearerImage`.
- `mobile/src/components/ui/{spinner,text,icon,button,separator,content}.tsx` — `Spinner`, `Text`
  (all text must use this), `Icon`, `Button`, `Separator`, `Content`/`ContentAction`.
- `mobile/src/hooks/useToast.ts` — `useToasts()` toast host (for "preview unavailable" etc.).
- Opening links: **`expo-web-browser`** `WebBrowser.openBrowserAsync(url)` (already a dep;
  nothing opens content links today — only auth SSO uses the browser).

### Confirmed gaps / collisions
- **Source-icon gap:** mobile has **no** `SourceIcon` / `WebResultIcon` / favicon anywhere
  (grep-confirmed). Web uses `SourceIcon` (source_type→icon) + `WebResultIcon` (favicon from URL).
  9a must add a minimal version; a full ~40-connector logo set is out of scope.
- **No document-preview surface** on mobile (web opens File/UserFile docs in a `PreviewModal`).
- **Route `/sources/[id]` is taken** — it's the PROJECT-FILES screen
  (`mobile/src/app/(app)/sources/[id].tsx`, reads `id` as projectId, reuses `useProjectFiles`).
  `deriveFocus` (`mobile/src/chat/chatFocus.ts`) only matches `/`, `/chat/…`, `/projects/…`. A
  chat-citations surface must be a **bottom sheet** (or a new, distinct route), not `/sources`.
- **No renderer / `usePacketDisplay` tests** exist. `mobile/src/chat/__tests__/fixtures.ts` has
  only `makeProjectFile`; the de-facto packet fixture is inline in `ndjson.test.ts`. Add
  `makePacket` / `makeCitationPacket` / `makeSearchDoc(Packet)` helpers.

## Backend packet spec (authoritative wire shapes)

NDJSON, one `Packet` per line: `{ placement:{turn_index, tab_index?, sub_turn_index?,
model_index?}, obj:{ type, ... } }`. No `data:` SSE prefix.

- **Citation — the ONLY citation packet:** `CitationInfo`
  `{ type:"citation_info", citation_number:int, document_id:str }`
  (`backend/onyx/server/query_and_chat/streaming_models.py:144`). Web's enum also declares
  `citation_start`/`citation_end` — **the backend never emits them; ignore.**
- **Document packets** (each `{ type, documents: SearchDoc[] }`):
  - `SearchToolDocumentsDelta` — `type:"search_tool_documents_delta"` (internal + web search).
  - `OpenUrlDocuments` — `type:"open_url_documents"` (URL-fetch tool; web calls it
    `FetchToolDocuments` — same wire string).
- **`message_start`** carries `final_documents: SearchDoc[] | null` (authoritative cited-doc set)
  + `pre_answer_processing_seconds`. (Backend `AgentResponseStart` does NOT send web's `id`/
  `content` on this packet.)
- **`SearchDoc`** (`backend/onyx/context/search/models.py:283`): `document_id:str`,
  `semantic_identifier:str`, `link:str|null`, `blurb:str`, `source_type:str`, `score:number|null`,
  `updated_at:str(ISO)|null`, `match_highlights:str[]`, `metadata:Record<string,string|string[]>`,
  `is_internet:bool`, `chunk_ind:int`, `boost:int`, `hidden:bool`, plus nullable
  `primary_owners/secondary_owners/is_relevant/relevance_explanation/file_id`. (No `db_doc_id` on
  the wire — it's `SearchDoc`, not `SavedSearchDoc`.)
- **Terminal packet is `stop`** (`{type:"stop", stop_reason}`) — there is **no `message_end`**.
  Mobile's `isComplete` already keys on `STOP`.

### The pivotal inline-marker fact
`backend/onyx/chat/citation_processor.py:496,506`: the inline marker is emitted as
`[[{num}]]({link})` where **`link = search_doc.link or ""`**. So:
- **Web/linked docs** → the marker URL **is** the document link → `onLinkPress(event.url)` can open
  it directly, **no citation-state resolution needed for the tap**.
- **File/internal docs (no link)** → the marker is **`[[n]]()`** (empty parens) → may not render as
  a tappable link at all (the real edge case).

Ordering per answer turn: document packets precede the answer (in the search tool's turn) →
`message_start` (`final_documents`) → repeating(`citation_info` immediately **before** the
`message_delta` carrying its `[[n]](url)` text) → `section_end` → `stop`. Dedup: a `document_id`
emits `citation_info` only on first cite.

## Web structure to mirror (parity target)

`packetProcessor.ts` (`handleCitationPacket`/`handleDocumentPacket`) builds three pieces of state,
mutated in place, incrementally (process-only-new via `nextPacketIndex`, reset-on-shrink):
`citationMap` (`{[n]: document_id}`), `citations[]` (deduped `{citation_num, document_id}` via a
seen-set, first-cite order), `documentMap` (`Map<document_id, doc>`). Three surfaces, all fed from
this state:
- **(A) inline marker** in the answer markdown → `MemoizedAnchor` resolves `[N]` → `citationMap` →
  doc → `SourceTag` chip + hover card. (Mobile: styled tappable link instead.)
- **(B) "Sources" toolbar button** (`MessageToolbar` → `SourceTag variant="button"`): an IconStack
  of ≤3 source icons + "Sources" label, shown when `citations.length>0 || documentMap.size>0`,
  tap → opens (C).
- **(C) cited-sources list** (`DocumentsSidebar`): **on mobile web already renders a bottom
  `Modal` titled "Sources"**. Sections: **Cited Sources** (sorted by citation order) / **More**
  (or "Found Sources") / **User Files**. Each row = `ChatDocumentDisplay`: [source-type icon or
  favicon + title(`semantic_identifier`) truncated] / [metadata: updated-at badge + ≤3 metadata
  chips] / [snippet from `match_highlights || blurb`]. Row tap → `openDocument`.
- **`openDocument`** (`web/src/lib/search/utils.ts`): `link` → open in browser; File/UserFile (no
  link) → preview modal; else no-op.

## Industry best practices (mobile citation UX)

- **Keep numeric `[N]` markers** (the RAG-grade pattern; Perplexity/Claude use them) — the work is
  styling + tap-target, not switching to inline hyperlinks. —
  https://medium.com/@shuimuzhisou/how-ai-engines-cite-sources-patterns-across-chatgpt-claude-perplexity-and-sge-8c317777c71d
- **Markers must be real focusable/tappable elements** with a tap-to-open behaviour (no hover
  fallback on touch). — https://www.aydesign.ai/blog/ai-citation-source-ui-patterns-2026
- **Tap target ≥ 44×44 pt** (Apple HIG) / WCAG 2.5.8 24px floor → expand the hit area
  (`hitSlop`/padding) beyond the tiny glyph. — https://www.designmonks.co/blog/perfect-mobile-button-size
- **Sources = a "Sources (N)" collapsible / bottom sheet / horizontal card scroller**, NOT a
  desktop side rail; card shows favicon + title + domain + ≤200-char snippet. —
  https://www.aydesign.ai/blog/ai-citation-source-ui-patterns-2026
- **Tap-to-open default = in-app browser** (`expo-web-browser` `openBrowserAsync` →
  SFSafariViewController / Chrome Custom Tabs), not external Safari/Chrome; a preview sheet for
  internal docs with no URL. — https://docs.expo.dev/versions/latest/sdk/webbrowser/
- **Streaming:** parse markers off the **cumulative** answer text (a `[12]` can split across
  deltas); tolerate forward-references (marker before its source) — render inert until resolved. —
  https://docs.perplexity.ai/docs/cookbook/articles/streaming-citations/README
- **Accessibility:** each marker needs a descriptive `accessibilityLabel` ("Source N: {title}"),
  not the bare number; `accessibilityRole="link"`. — https://www.deque.com/blog/text-links-practices-screen-readers/
- **NN/g:** users rarely click citations but their presence drives (over)trust — lead source cards
  with title + domain (meaningful labels), place markers adjacent to the claim. —
  https://www.nngroup.com/articles/explainable-ai/

## Approaches

### Approach A — Simplicity-First: extend `MessageTextRenderer`, no new framework
Citations ride the existing `node.packets`; `usePacketDisplay` already hands all packets to the one
matched `MessageTextRenderer`, so **no registry / `usePacketDisplay` / controller / history
change**. Extend `MessageTextRenderer` to (a) pass `onLinkPress` through `StreamingMarkdown` and
(b) fold packets via one pure `deriveCitations(packets)` (re-run each flush via `useMemo`, like
`accumulateContent`) that drives a Sources bar + bottom-sheet Modal. **Inline routing needs no
citation state** — the marker URL is pre-baked, so `onLinkPress(event.url)` opens it directly;
empty-URL file markers route to opening the Sources sheet. New: `contracts/search.ts` (`SearchDoc`),
`chat/citations.ts` (`deriveCitations` + `faviconUrlForLink`/`domainOf`), `SourceIcon.tsx`,
`CitedSources.tsx` (bar + sheet + row). ~4 new files, 4 small edits.
- **Trade-offs:** fewest moving parts, ships fast, lowest risk; but citation logic is trapped in
  `MessageTextRenderer` (9b's grouping will have to re-home it), `deriveCitations` re-scans the full
  array each flush (fine at chat scale), and it builds no shared source layer for 9b to reuse.
- **Risks:** empty-parens `[[n]]()` file markers may not parse as a link (mitigation: 1-line
  normalize `]]()` → `]](#cited)`); source-icon gap filled by a public-favicon `expo-image` +
  generic fallback.

### Approach B — Streaming-Robustness / Performance-First: incremental processor + marker transform
Center on a pure, incremental `citationProcessor.ts` (ref-based `useCitationProcessor`, process-only-
new via `nextPacketIndex`, in-place mutation, primitive change-proxies `citationCount`/`docCount`/
`resolveVersion`) so a 2000-token / 30-citation answer never re-parses; the Sources bar/sheet are
memoized siblings that re-render only when counts change, never per token. A pure
`transformCitationMarkers(displayed, resolve)` rewrites `[[n]](url)` → a controlled `onyxcite://n`
href when resolved, elides the partial trailing marker, and downgrades forward-refs to inert plain
text; tap routing resolves `n → doc → openDocument`.
- **Trade-offs:** deterministic streaming edges + O(new-packets) processing + memoized UI; but the
  robustness machinery is **largely undercut by the pre-baked-URL fact** (doc packets precede the
  answer and the marker carries its own URL, so forward-ref gating buys little), and the
  `onyxcite://` rewrite adds a fragile per-frame transform.
- **Risks:** renderer may filter a custom `onyxcite://` scheme in `onLinkPress`; partial-marker
  regex edge cases (`[not a cite]`, real `[[x]](y)` links); superscript may not be expressible.

### Approach C — Flexibility / Reusable-Foundation: one processor + a `processed` channel + shared source layer
Introduce the minimal durable seams 9b–9e will reuse: (a) a pure incremental `messageProcessor.ts`
(mobile port of web's single `packetProcessor`: cursor + reset-on-shrink) that 9a fills with
`citationMap`/`citations[]`/`documentMap` and **9b extends** with grouping/steps; (b) extend
`usePacketDisplay` to host the processor and `MessageRendererProps` to carry `processed` state (not
just raw packets) — the channel 9b's timeline/search/tool renderers read; (c) a shared source layer
— `SearchDoc` contract, `SourceIcon`/`WebResultIcon`, `SourceRow`, `openSource` router — reused by
9a's sheet **and** 9b's search/fetch sub-renderers. Grouping itself is **not** built now (that's 9b);
9a state stays flat/grouping-free so 9b's grouping design stays unconstrained. Inline uses the same
`onLinkPress` → `resolveCitationHref` → `openSource`.
- **Trade-offs:** 9b plugs in with zero renderer-plumbing rewrite (web proves the one-processor
  path) and `SourceRow`/`SourceIcon`/`SearchDoc`/`openSource` are each reused 3–4× across 9a–9b;
  upfront cost is one small pure module + a hook change + a prop addition + a few components. Each
  seam is justified by a concrete, imminent 9b consumer (not speculative).
- **Risks:** a wrong guess about 9b's grouping shape (minimized — 9a commits nothing about
  turn/tab grouping); `SearchDoc` under-modelling (mitigation: port the full shape now);
  `resolveCitationHref` is the single fragile mapping (isolated + unit-tested).

## Cross-comparison

- **Inline tap-path:** A's insight (pre-baked marker URL + doc-packets-precede-answer) makes the
  common web-doc case trivial and **undercuts B's forward-ref/`onyxcite://` machinery** — B's
  genuinely useful core (an incremental cursor) is already present in C (and in web). So B's extras
  mostly don't pay for themselves at chat scale.
- **Alignment with the roadmap:** 9b is **next** and explicitly needs a packet processor to extend
  with grouping + search/fetch renderers that render source rows of `SearchDoc`s — i.e. exactly C's
  shared layer + `processed` channel. A ports citations ad-hoc into `MessageTextRenderer`,
  diverging from web's one-processor structure and forcing a re-home when 9b lands.
- **Extraction policy tension:** the mobile policy is "extract-on-proven-reuse, not upfront." C's
  reuses are **named and imminent** (9b), not speculative — so C is not over-engineering; but if 9b
  were far off, A would be the honest call.
- **Failure modes:** all three share the empty-parens `[[n]]()` file-marker risk and the
  source-icon gap; C additionally carries a (minimized) grouping-shape guess; B additionally
  carries the custom-scheme + regex risks.

## Chosen approach

**Approach C (Reusable Foundation), adopting Approach A's inline simplification.** Selected at
GATE 1.

Rationale: C matches web's actual structure — one incremental packet processor + a `processed`
state channel to renderers — and **9b (agentic timeline) is the very next phase** and needs
exactly this: a processor to extend with turn/tab grouping, and a shared source layer
(`SearchDoc` + `SourceIcon`/`WebResultIcon`/`SourceRow`/`openSource`) that 9b's search/fetch
sub-renderers reuse. A would force a re-home of the citation logic when 9b lands; B builds
streaming-robustness machinery that the pre-baked-marker-URL fact largely renders unnecessary.

**Grafted from A (the inline simplification):** the inline tap-path does **not** resolve citation
state — since the marker URL is pre-baked (`[[n]](link)`, `link = search_doc.link or ""`),
`onLinkPress(event.url)` opens web/linked docs directly, and empty-URL file markers degrade to
opening the Sources sheet. We therefore **drop B's forward-reference gating and the
`onyxcite://` marker-rewrite transform** entirely.

Net shape: C's reusable seams (processor + `processed` channel + shared source layer) + A's lean
inline path + none of B's rewrite/gating complexity.

**Deferred to 9b (explicitly NOT built now):** turn/tab packet **grouping**, timeline steps, and
the reasoning/search/tool sub-renderers. 9a's processor state stays flat (`citationMap`,
`citations[]`, `documentMap`, completion) so 9b's grouping design remains unconstrained.

