# Universal side panel — refactor design

## Issues to Address

The current `BuildOutputPanel` (`web/src/app/craft/components/OutputPanel.tsx`)
hosts three pinned tabs — Preview, Files, Artifacts — and a separate
pinned-vs-file-tabs system where opened files render as additional tabs at
the panel header level (the `filePreviewTabs` array, ~line 500). This is
already close to a universal tab system, but file-specific in shape.

A planned subagent-view feature wants to add another transient tab kind
("show me the live transcript of subagent X in the side panel"). Rather
than special-case the panel's tab system per kind, generalize it once so
future view kinds can plug in cleanly.

The goal: make the side panel a single surface that can render any
"viewable thing," with a small set of pinned tabs that are always present
and a stack of transient tabs that the user opens and closes per session.

This refactor is a prerequisite for the subagent-view feature
(`docs/craft/features/subagents/2026-05-28-subagents-view-design.md`) but
stands on its own value: it tightens the panel's typing, removes
file-specific assumptions, and lays groundwork for future view kinds.

## Important Notes

- **The dual-tier tab system already exists.** `OutputPanel.tsx:500-505`
  renders `filePreviewTabs` after a separator from the pinned trio. The
  refactor doesn't invent a new structure — it generalizes the existing
  one.
- **The panel toggle and slide animation already work.**
  `useOutputPanelOpen` / `useToggleOutputPanel` are wired in `ChatPanel.tsx`
  (the chat-header toggle) and `v1/page.tsx` (panel mount). There's a
  300ms slide-out animation already in place (`ChatPanel.tsx:90-95`).
- **The current store has file-specific tab state.**
  `useBuildSessionStore.ts` holds `filePreviewTabs`,
  `activeFilePreviewPath`, and `tabHistory` (the pinned-vs-file
  switcher). These become a single typed `panelTabs` list once
  generalized.
- **No new view kinds added in this PR.** Subagent view rendering and
  the agent strip are out of scope here. This PR only refactors plumbing
  so the subagent PR can add its kind cleanly.
- **Visual inspiration: Cursor + Lovable side panels.** Both lean compact
  and quiet — tight tab chrome, subtle active indicators, no heavy
  borders, native-feel close affordances on hover. Aim for that
  restraint in the Opal aesthetic. Worth studying the actual UIs (not
  just our mockups) when implementing tab styling and the slide-in
  animation.

## Design

### Tab kinds

Today the panel implicitly has two kinds of tabs:
- **Pinned** — Preview, Files, Artifacts. Always present. Can't close.
- **File** — opened files. Closeable. Tracked in `filePreviewTabs`.

After the refactor:
- **Pinned** — Preview, Files, Artifacts. Unchanged behavior; visual
  treatment gets a small pin indicator to distinguish from transient
  tabs.
- **Transient** — a polymorphic list. Each entry is a discriminated
  union by `kind`:
  - `{ kind: "file", path: string }` — replaces today's
    `filePreviewTabs` entries; no behavior change.
  - `{ kind: "subagent", subagentId: string }` — placeholder for the
    follow-up subagent PR. Not rendered or createable in this PR; the
    union just leaves the door open.

The rendering layer switches on `kind` to pick label, icon, and body
component. Future kinds (search results, diff viewer, log viewer, etc.)
add a new union member and a new body component; no other plumbing.

### State model changes (`useBuildSessionStore.ts`)

- `filePreviewTabs: FilePreviewTab[]` → `panelTabs: PanelTab[]` where
  `PanelTab = { kind: "file", path: string }` (subagent kind added in
  the subagent PR).
- `activeFilePreviewPath: string | null` → `activePanelTabId: string |
  null`. The ID is a derived key (e.g. `"file:<path>"`) so each kind
  has a unique namespace.
- `tabHistory` (the pinned-vs-file recency stack) generalizes the same
  way — it tracks pinned tabs and active transient tab IDs.
- The setter/action functions that today take a file path
  (`openFilePreview`, `closeFilePreview`,
  `setActiveFilePreviewPath`) generalize to take a `PanelTab` /
  `tabId`. The file-specific helpers can stay as thin wrappers
  internally if call sites are easier to migrate that way.

### Rendering (`OutputPanel.tsx`)

- The tab-row map at ~lines 500-560 walks `panelTabs` and switches on
  `kind` to render the tab chrome. For `kind: "file"`, behavior is
  unchanged (file icon + filename + close ×).
- The body switch (where today `<FilesTab>` / `<PreviewTab>` /
  `<ArtifactsTab>` render based on `activeOutputTab` and
  `<FilePreviewContent>` renders for an active file path) becomes a
  single switch on the active tab ID — if the active is a pinned tab,
  render the corresponding pinned component; if a transient
  `kind: "file"`, render `<FilePreviewContent>`.
- Pinned tabs get a small 📌 (or equivalent Opal icon) indicator and
  no close ×. Transient tabs get a close × on hover/active.

### Chat-header toggle (`ChatPanel.tsx`)

- Verify exactly one panel toggle exists in the chat header — a single
  icon button that calls `toggleOutputPanel`. Visual: accent-tinted
  when panel is open, neutral when closed.
- No other launcher buttons for Preview / Files / Artifacts in the
  chat header. (If any have crept in, remove them.)

### Auto-open-on-first-preview

When the session's first webapp artifact lands (the moment the Preview
tab becomes meaningful), set `outputPanelOpen = true` if it isn't
already. This teaches users where the panel lives without needing a
permanent header button.

Trigger detection: piggyback on the existing `webappNeedsRefresh` /
artifact-creation signal. Only fire once per session — if the user has
manually closed the panel, don't re-open it on later refreshes.

### Inline file links as panel openers

Existing inline file references in chat (e.g., the file paths shown in
tool-call cards) become click targets that open the panel to that
file. Most of this already works — the file is opened in
`filePreviewTabs` and the panel surfaces it — but verify the path is
clean and the panel auto-opens if currently closed.

### Components

New / changed:

- **`useBuildSessionStore.ts`** (changed) — generalize
  `filePreviewTabs` → `panelTabs`, rename associated action and
  selector hooks. Add migration shims if any consumer outside the
  panel reads the old field names.
- **`OutputPanel.tsx`** (changed) — switch the tab-row map and body
  switch onto the generalized model. Add pin indicator on pinned
  tabs.
- **`ChatPanel.tsx`** (changed) — audit chat-header for any
  redundant launcher buttons; ensure single panel toggle. Implement
  auto-open-on-first-preview behavior.
- **Existing `PanelTab` interfaces / types** (new or moved) — define
  the discriminated-union type in `web/src/app/craft/types/` next
  to the existing display types.

### Edge cases

- **A consumer of the old `filePreviewTabs` field outside the panel.**
  Likely candidates: the file-preview modal, the chat panel itself if
  it surfaces "X files open" anywhere. Grep for `filePreviewTabs`,
  `activeFilePreviewPath`, `openFilePreview` — update each call site.
- **Panel was open on a specific file → user reloads.** Restore both
  the open transient tab list and the active tab ID from persisted
  state if it's persisted today; otherwise return to Preview pinned
  on reload (no regression from current behavior).
- **First-time webapp preview arrives while panel is already open on
  Files.** Do not switch the active tab. Auto-open only fires when
  the panel is closed.
- **User dismisses the panel after auto-open.** Set a session-scoped
  "user dismissed" flag so the auto-open doesn't fire again on
  subsequent preview refreshes.
- **No webapp ever arrives this session (e.g., the agent doesn't
  build a webapp).** Panel stays closed unless the user clicks the
  toggle. No empty auto-open.

## Tests

Single layer: **Playwright E2E**. This is fundamentally a UI plumbing
refactor; the meaningful behavior is the integration between store,
tab rendering, and chat-header toggle.

`web/tests/e2e/craft-side-panel.spec.ts` — drive a Craft conversation
through these gates:

1. **Closed state on first load.** Panel is closed, chat takes full
   width, chat-header toggle is visible and in the inactive state.
2. **Toggle opens the panel.** Click the toggle → panel slides in,
   Preview / Files / Artifacts pinned tabs visible with pin
   indicators, no transient tabs yet.
3. **Pinned-to-pinned switching.** Click Files tab → tab activates,
   file browser renders. Click Preview → switches back.
4. **Open a file as transient tab.** Trigger a file open (via an
   inline file link or the file browser). Tab appears after a
   separator from the pinned trio, file viewer renders, close × is
   visible on hover.
5. **Close a transient tab.** Click ×, tab vanishes; active falls
   back to the previous tab (pinned or transient, per existing
   behavior).
6. **Toggle closes the panel; reopening preserves state.** Close
   panel via toggle → chat full-width again. Re-open → same active
   tab, same scroll position in the file viewer.
7. **Auto-open on first preview.** Start a session that produces a
   webapp; assert that on the first preview-ready signal, the panel
   opens to Preview (if it was closed). Manually closing it
   afterward and triggering another preview refresh does NOT
   re-open.

No unit tests proposed: the refactor is largely structural —
type-check and the E2E catch the regressions worth catching. No
external-dependency unit tests proposed: nothing in this refactor
touches the DB or backend services.
