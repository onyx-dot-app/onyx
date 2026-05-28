# Universal Side Panel Refactor — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generalize Craft's `BuildOutputPanel` from a file-specific transient-tab system into a polymorphic `PanelTab` system so future view kinds (e.g., subagent transcripts) plug in via a discriminated union.

**Architecture:** Replace `filePreviewTabs: FilePreviewTab[]` and `activeFilePreviewPath: string | null` in `useBuildSessionStore` with `panelTabs: PanelTab[]` and `activePanelTabId: string | null`. `PanelTab` is a discriminated union starting with only `kind: "file"`. The rendering layer in `OutputPanel.tsx` switches on `kind` to dispatch tab chrome and body. The chat-header gets a single panel toggle (audit + ensure no duplicates). Add auto-open-on-first-preview behavior gated by a "user-dismissed" flag.

**Tech Stack:** TypeScript, React, Zustand (the Craft session store), Tailwind + Opal design tokens, Playwright for E2E.

**Spec:** `docs/craft/features/universal-panel/2026-05-28-universal-panel-refactor-design.md`

---

## File Structure

**Files to create:**
- `web/tests/e2e/craft-side-panel.spec.ts` — Playwright E2E

**Files to modify:**
- `web/src/app/craft/types/displayTypes.ts` — add `PanelTab` union + `panelTabId()` helper
- `web/src/app/craft/hooks/useBuildSessionStore.ts` — rename state fields, rename actions, update selectors, update `TabHistoryEntry`
- `web/src/app/craft/components/OutputPanel.tsx` — switch rendering to `panelTabs` + `activePanelTabId`, add pin indicator on pinned tabs
- `web/src/app/craft/hooks/useBuildStreaming.ts` — update any callers of the renamed actions/selectors
- `web/src/app/craft/components/ChatPanel.tsx` — audit chat-header toggle, implement auto-open-on-first-preview

**Files unchanged (but verified):**
- `web/src/app/craft/v1/page.tsx` — `BuildOutputPanel` mount is fine as-is
- `web/src/app/craft/components/output-panel/FilesTab.tsx`, `PreviewTab.tsx`, `ArtifactsTab.tsx`, `FilePreviewContent.tsx` — their internals don't change; they're rendered the same way

---

## Per-Task Verification Strategy

This refactor is mostly type-driven. Per-task gate:
- `cd web && bun run typecheck` (or `pnpm typecheck`, whichever the project uses — check `web/package.json` scripts)
- Start dev server (per `web/package.json`), load Craft, click around to smoke-test the affected behavior
- Commit when both gates pass

Full behavioral coverage lives in the Playwright E2E added in Task 8. Run it locally before opening the PR.

---

## Task 1: Add the `PanelTab` discriminated union and `panelTabId()` helper

**Files:**
- Modify: `web/src/app/craft/types/displayTypes.ts`

- [ ] **Step 1: Read the existing `displayTypes.ts`** to understand its style and where to put the new types.

Run: `cat web/src/app/craft/types/displayTypes.ts`

- [ ] **Step 2: Append the new types at the bottom of `displayTypes.ts`**

```typescript
/**
 * Discriminated union of transient tabs that the side panel can render.
 *
 * Pinned tabs (Preview, Files, Artifacts) are handled separately via the
 * existing `OutputTabType` — they are not represented in `PanelTab`. Only
 * tabs that the user opens and closes dynamically (file viewers, subagent
 * transcripts, etc.) live here.
 *
 * Future view kinds: add a new variant here, render its chrome in
 * `OutputPanel.tsx`'s tab-row map, and its body in the panel body switch.
 */
export type PanelTab = { kind: "file"; path: string; fileName: string };

/**
 * Stable string ID for a `PanelTab`, namespaced by kind. Used as the value
 * of `activePanelTabId` in the store and as React keys for tab rendering.
 *
 * Format: "<kind>:<identifier>" — e.g. "file:web/src/app/page.tsx".
 */
export function panelTabId(tab: PanelTab): string {
  switch (tab.kind) {
    case "file":
      return `file:${tab.path}`;
  }
}
```

- [ ] **Step 3: Type-check**

Run: `cd web && bun run typecheck` (or the project's equivalent — check `web/package.json`)
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add web/src/app/craft/types/displayTypes.ts
git commit -m "feat(craft): add PanelTab discriminated union for side panel"
```

---

## Task 2: Rename store state fields — `filePreviewTabs` → `panelTabs`, `activeFilePreviewPath` → `activePanelTabId`

**Files:**
- Modify: `web/src/app/craft/hooks/useBuildSessionStore.ts`

This task only renames the state shape and updates the action implementations and selectors *within the store file*. Callers in other files (`OutputPanel.tsx`, `useBuildStreaming.ts`) are updated in Task 3.

- [ ] **Step 1: Import `PanelTab` and `panelTabId` at the top of `useBuildSessionStore.ts`**

Find the existing type imports near the top of the file (around the other display-type imports) and add:

```typescript
import type { PanelTab } from "@/app/craft/types/displayTypes";
import { panelTabId } from "@/app/craft/types/displayTypes";
```

- [ ] **Step 2: Delete the local `FilePreviewTab` interface (lines ~262-266)**

The shape is superseded by `PanelTab`'s `kind: "file"` variant. Remove:

```typescript
/** File preview tab data */
export interface FilePreviewTab {
  path: string;
  fileName: string;
}
```

- [ ] **Step 3: Update `TabHistoryEntry` to use a generic tab-ID instead of file-specific path**

Find (lines ~276-279):

```typescript
export type TabHistoryEntry =
  | { type: "pinned"; tab: OutputTabType }
  | { type: "file"; path: string };
```

Replace with:

```typescript
export type TabHistoryEntry =
  | { type: "pinned"; tab: OutputTabType }
  | { type: "panel-tab"; tabId: string };
```

- [ ] **Step 4: Rename the two state fields in `BuildSessionData` (lines ~315-320)**

Find:

```typescript
  /** File preview tabs open in this session */
  filePreviewTabs: FilePreviewTab[];
  /** Active pinned tab in output panel */
  activeOutputTab: OutputTabType;
  /** Active file preview path (when set, this is the active tab instead of pinned tab) */
  activeFilePreviewPath: string | null;
```

Replace with:

```typescript
  /** Transient panel tabs open in this session (files, subagents, etc.) */
  panelTabs: PanelTab[];
  /** Active pinned tab in output panel */
  activeOutputTab: OutputTabType;
  /** Active transient panel tab ID (when set, takes precedence over pinned tab) */
  activePanelTabId: string | null;
```

- [ ] **Step 5: Update initial state in `createSession` default block (lines ~493-495)**

Find:

```typescript
  filePreviewTabs: [],
  ...
  activeFilePreviewPath: null,
```

Replace each with:

```typescript
  panelTabs: [],
  ...
  activePanelTabId: null,
```

- [ ] **Step 6: Rewrite `openFilePreview` action (lines ~1609-1647)**

Replace the entire `openFilePreview` action body. The new version constructs a `PanelTab` and uses `panelTabId()`:

```typescript
  openFilePreview: (sessionId: string, path: string, fileName: string) => {
    set((state) => {
      const session = state.sessions.get(sessionId);
      if (!session) return state;

      const newTab: PanelTab = { kind: "file", path, fileName };
      const tabId = panelTabId(newTab);

      const existingTab = session.panelTabs.find(
        (t) => panelTabId(t) === tabId
      );

      const panelTabs = existingTab
        ? session.panelTabs
        : [...session.panelTabs, newTab];

      // Push to history (truncate forward history if navigating from middle)
      const { tabHistory } = session;
      const newEntry: TabHistoryEntry = { type: "panel-tab", tabId };
      const newEntries = [
        ...tabHistory.entries.slice(0, tabHistory.currentIndex + 1),
        newEntry,
      ];

      const updatedSession: BuildSessionData = {
        ...session,
        panelTabs,
        activePanelTabId: tabId, // Always switch to this tab
        tabHistory: {
          entries: newEntries,
          currentIndex: newEntries.length - 1,
        },
        lastAccessed: new Date(),
      };
      const newSessions = new Map(state.sessions);
      newSessions.set(sessionId, updatedSession);
      return { sessions: newSessions };
    });
  },
```

- [ ] **Step 7: Rewrite `openMarkdownPreview` action (lines ~1649-1689)**

Same pattern as Step 6. Replace its body:

```typescript
  openMarkdownPreview: (sessionId: string, filePath: string) => {
    const fileName = filePath.split("/").pop() || filePath;
    set((state) => {
      const session = state.sessions.get(sessionId);
      if (!session) return state;

      const newTab: PanelTab = { kind: "file", path: filePath, fileName };
      const tabId = panelTabId(newTab);

      const existingTab = session.panelTabs.find(
        (t) => panelTabId(t) === tabId
      );

      const panelTabs = existingTab
        ? session.panelTabs
        : [...session.panelTabs, newTab];

      const { tabHistory } = session;
      const newEntry: TabHistoryEntry = { type: "panel-tab", tabId };
      const newEntries = [
        ...tabHistory.entries.slice(0, tabHistory.currentIndex + 1),
        newEntry,
      ];

      const updatedSession: BuildSessionData = {
        ...session,
        outputPanelOpen: true,
        panelTabs,
        activePanelTabId: tabId,
        tabHistory: {
          entries: newEntries,
          currentIndex: newEntries.length - 1,
        },
        lastAccessed: new Date(),
      };
      const newSessions = new Map(state.sessions);
      newSessions.set(sessionId, updatedSession);
      return { sessions: newSessions };
    });
  },
```

- [ ] **Step 8: Rewrite `closeFilePreview` action (lines ~1691-1724)**

The new version closes a tab by tab ID, not by file path:

```typescript
  closeFilePreview: (sessionId: string, path: string) => {
    set((state) => {
      const session = state.sessions.get(sessionId);
      if (!session) return state;

      const closingTabId = panelTabId({ kind: "file", path, fileName: "" });

      const panelTabs = session.panelTabs.filter(
        (t) => panelTabId(t) !== closingTabId
      );

      const activePanelTabId =
        session.activePanelTabId === closingTabId
          ? null
          : session.activePanelTabId;

      const activeOutputTab =
        session.activePanelTabId === closingTabId
          ? "files"
          : session.activeOutputTab;

      const updatedSession: BuildSessionData = {
        ...session,
        panelTabs,
        activePanelTabId,
        activeOutputTab,
        lastAccessed: new Date(),
      };
      const newSessions = new Map(state.sessions);
      newSessions.set(sessionId, updatedSession);
      return { sessions: newSessions };
    });
  },
```

Note: `closeFilePreview(sessionId, path)` keeps its file-specific signature for caller compatibility. It internally constructs the file-kind tab ID. When subagent tabs are added in a follow-up PR, that PR can add a generic `closePanelTab(sessionId, tabId)` action — for now we leave the API surface minimal.

- [ ] **Step 9: Update any other places in `useBuildSessionStore.ts` that reference the renamed fields**

Grep within the store file:

```bash
grep -n "filePreviewTabs\|activeFilePreviewPath" web/src/app/craft/hooks/useBuildSessionStore.ts
```

Each remaining hit needs renaming. Expect hits in:
- The `TabHistoryEntry` "file" navigation logic (back/forward navigation) — rename the discriminator from `"file"` to `"panel-tab"` and the field from `path` to `tabId`
- The session-restore / merge paths (around `updateSessionData` and createSession overrides)

- [ ] **Step 10: Rename selector hooks**

Find:

```typescript
export const useFilePreviewTabs = () => ...
export const useActiveFilePreviewPath = () => ...
```

Rename and update to use new fields:

```typescript
export const usePanelTabs = () =>
  useBuildSessionStore((state) => {
    const currentSessionId = state.currentSessionId;
    if (!currentSessionId) return [];
    return state.sessions.get(currentSessionId)?.panelTabs ?? [];
  });

export const useActivePanelTabId = () =>
  useBuildSessionStore((state) => {
    const currentSessionId = state.currentSessionId;
    if (!currentSessionId) return null;
    return state.sessions.get(currentSessionId)?.activePanelTabId ?? null;
  });
```

Confirm shape matches the existing selector pattern in the file (check a working selector nearby and mirror its style).

- [ ] **Step 11: Rename the `setActiveFilePreviewPath` action**

The store has a `setActiveFilePreviewPath(sessionId, path)` action — rename it to `setActivePanelTabId(sessionId, tabId)` everywhere it's declared and implemented. Signature change: takes a `string | null` tab ID instead of a path.

Grep within the store file for `setActiveFilePreviewPath`. Update each hit:
- Interface declaration (~line 450 area)
- Implementation body (substitute `activeFilePreviewPath` → `activePanelTabId` and `path` parameter → `tabId`)

The action's body shape is unchanged otherwise — it just writes the renamed field.

- [ ] **Step 12: Type-check**

Run: `cd web && bun run typecheck`
Expected: FAIL — references in `OutputPanel.tsx` and `useBuildStreaming.ts` still use old names. (We fix those in Task 3.)

This is the expected intermediate state. Do not commit yet.

---

## Task 3: Update callers — `OutputPanel.tsx` and `useBuildStreaming.ts`

**Files:**
- Modify: `web/src/app/craft/components/OutputPanel.tsx`
- Modify: `web/src/app/craft/hooks/useBuildStreaming.ts`

- [ ] **Step 1: Grep for old references in callers**

```bash
grep -nE "useFilePreviewTabs|useActiveFilePreviewPath|filePreviewTabs|activeFilePreviewPath" \
  web/src/app/craft/components/OutputPanel.tsx \
  web/src/app/craft/hooks/useBuildStreaming.ts
```

- [ ] **Step 2: Update `OutputPanel.tsx` imports + selector usage**

Find the selector imports and usages at the top of `OutputPanel.tsx`:

```typescript
import {
  useFilePreviewTabs,
  useActiveFilePreviewPath,
  ...
} from "@/app/craft/hooks/useBuildSessionStore";
```

Change to:

```typescript
import {
  usePanelTabs,
  useActivePanelTabId,
  ...
} from "@/app/craft/hooks/useBuildSessionStore";
```

Update the local variable declarations:

```typescript
const panelTabs = usePanelTabs();
const activePanelTabId = useActivePanelTabId();
```

- [ ] **Step 3: Update the tab-row rendering in `OutputPanel.tsx`**

Find the file-preview-tab map block (the `filePreviewTabs.map(...)` around lines 500-560). Replace `filePreviewTabs` with `panelTabs`. For the per-tab rendering, dispatch on `kind`:

```typescript
{/* Separator between pinned and transient tabs */}
{panelTabs.length > 0 && (
  <div className="w-px h-5 bg-border-02 mx-2 mb-1 self-center" />
)}

{/* Transient panel tabs */}
{panelTabs.map((tab) => {
  const id = panelTabId(tab);
  const isActive = activePanelTabId === id;

  switch (tab.kind) {
    case "file": {
      const TabIcon = getFileIcon(tab.fileName);
      return (
        <button
          key={id}
          onClick={() => handlePanelTabClick(id, tab)}
          className={cn(
            "group relative inline-flex items-center justify-center gap-1.5 px-3 pr-2",
            "max-w-[150px] min-w-fit",
            isActive
              ? "bg-background-neutral-00 text-text-04 rounded-t-lg py-2"
              : "text-text-03 bg-transparent hover:bg-background-tint-02 rounded-full py-1 mb-1"
          )}
        >
          {/* Left curved joint, icon, label, close ×, right curved joint —
              copy the existing JSX from the prior filePreviewTabs.map body,
              substituting `tab.fileName` and the per-tab close handler
              `handlePanelTabClose(e, id)`. */}
          {/* ... */}
        </button>
      );
    }
  }
})}
```

Important: preserve the existing visual treatment (curved joints, sizing, icon, close ×). The only structural change is dispatch on `kind` — within `case "file":` the JSX is byte-equivalent to today's transient-tab JSX, with `previewTab.fileName` → `tab.fileName` and `previewTab.path` → `tab.path` (and the close × handler taking a tab ID instead of a path).

Import the `panelTabId` helper:

```typescript
import { panelTabId } from "@/app/craft/types/displayTypes";
```

- [ ] **Step 4: Update the tab click + close handlers in `OutputPanel.tsx`**

Find `handlePreviewTabClick` / `handlePreviewTabClose` (grep for them in the file). Rename and re-shape to take a tab ID:

```typescript
const handlePanelTabClick = useCallback(
  (tabId: string, tab: PanelTab) => {
    if (!session?.id) return;
    setActivePanelTabId(session.id, tabId);
    // mirror the existing handler's history-push logic, if any
  },
  [session?.id, setActivePanelTabId]
);

const handlePanelTabClose = useCallback(
  (e: React.MouseEvent, tabId: string, tab: PanelTab) => {
    e.stopPropagation();
    if (!session?.id) return;
    if (tab.kind === "file") {
      closeFilePreview(session.id, tab.path);
    }
  },
  [session?.id, closeFilePreview]
);
```

If `setActivePanelTabId` doesn't yet exist as an action: add it now in `useBuildSessionStore.ts`. Use the existing `setActiveFilePreviewPath` action as a template — it's the same pattern, just operating on the renamed field.

```typescript
// In useBuildSessionStore.ts, add (or rename setActiveFilePreviewPath to):
setActivePanelTabId: (sessionId: string, tabId: string | null) => void;

// Implementation: mirror setActiveFilePreviewPath's body, substituting field names.
```

- [ ] **Step 5: Update the body switch in `OutputPanel.tsx`**

The current body switch picks between `<PreviewTab>`, `<FilesTab>`, `<ArtifactsTab>`, and `<FilePreviewContent>` based on `activeOutputTab` and `activeFilePreviewPath`. Update it to use `activePanelTabId`. The active transient tab is determined by parsing the ID prefix:

```typescript
// In the body render section:
const activeTab: PanelTab | undefined = panelTabs.find(
  (t) => panelTabId(t) === activePanelTabId
);

if (activeTab) {
  switch (activeTab.kind) {
    case "file":
      return (
        <FilePreviewContent
          path={activeTab.path}
          fileName={activeTab.fileName}
          /* ...other existing props... */
        />
      );
  }
}

// Otherwise fall through to the pinned-tab render based on activeOutputTab.
```

Preserve the existing pinned-tab body switch exactly as-is.

- [ ] **Step 6: Update `useBuildStreaming.ts`**

```bash
grep -nE "useFilePreviewTabs|useActiveFilePreviewPath|filePreviewTabs|activeFilePreviewPath|openFilePreview|closeFilePreview" web/src/app/craft/hooks/useBuildStreaming.ts
```

For each hit, swap to the new name. The `openFilePreview` and `closeFilePreview` actions kept their signatures (path + fileName for open, path for close), so call sites that use those don't need to change. Only the selector hooks need renaming.

- [ ] **Step 7: Type-check**

Run: `cd web && bun run typecheck`
Expected: PASS — no remaining references to old names.

- [ ] **Step 8: Dev-server smoke test**

Start the Craft app per project conventions (`web/package.json` scripts). Log in (`a@example.com` / `a`). Confirm:
- Side panel still toggles open/closed via the chat-header toggle
- Preview / Files / Artifacts tabs still switch as expected
- Opening a file from the Files tab still creates a transient tab; closing it still works
- No console errors

- [ ] **Step 9: Commit**

```bash
git add web/src/app/craft/types/displayTypes.ts \
        web/src/app/craft/hooks/useBuildSessionStore.ts \
        web/src/app/craft/components/OutputPanel.tsx \
        web/src/app/craft/hooks/useBuildStreaming.ts
git commit -m "refactor(craft): generalize panel tabs to discriminated PanelTab union"
```

---

## Task 4: Add pin indicator on pinned tabs (Preview / Files / Artifacts)

**Files:**
- Modify: `web/src/app/craft/components/OutputPanel.tsx`

Goal: a small visual marker on Preview / Files / Artifacts tabs distinguishing them from transient tabs at a glance. Subtle, Opal-aesthetic — not a literal 📌 emoji.

- [ ] **Step 1: Choose the indicator**

The Opal icon set is at `web/src/icons/`. Pick a small icon that conveys "pinned" — candidates: an existing `SvgLock`, `SvgPin`, or a generic dot. If none fit, use a `SvgBookmark` or a small 4px circle rendered as a CSS pseudo-element.

```bash
ls web/src/icons/ | grep -iE "pin|lock|bookmark|dot"
```

Pick one available icon. If multiple options, prefer one already used elsewhere in the codebase.

- [ ] **Step 2: Render the indicator next to the tab label for pinned tabs only**

In `OutputPanel.tsx`, inside the pinned-tab map block (the one rendering Preview / Files / Artifacts buttons), add the indicator. Keep it tiny and color-muted (`stroke-text-04` or `text-text-04`):

```tsx
<PinIcon
  size={10}
  className="stroke-text-04 shrink-0 opacity-60"
  aria-hidden
/>
<Text className={cn("truncate", isDisabled && "text-text-02")}>
  {tab.label}
</Text>
```

Position the indicator before the label (or right of the existing tab icon — pick whichever reads cleaner; verify in browser).

- [ ] **Step 3: Type-check and smoke test**

Type-check should pass. Smoke test: open the panel, see the indicator on the three pinned tabs. Confirm transient tabs (opened files) do NOT show the indicator.

- [ ] **Step 4: Commit**

```bash
git add web/src/app/craft/components/OutputPanel.tsx
git commit -m "feat(craft): add pin indicator on pinned side-panel tabs"
```

---

## Task 5: Audit chat-header for redundant panel toggle buttons

**Files:**
- Modify (maybe): `web/src/app/craft/components/ChatPanel.tsx`

- [ ] **Step 1: Grep for any header-area buttons related to the panel**

```bash
grep -nE "toggleOutputPanel|outputPanelOpen|Preview|Files|Artifacts" \
  web/src/app/craft/components/ChatPanel.tsx
```

Inventory every button or clickable affordance in the chat header. Expectation: exactly one toggle button that calls `toggleOutputPanel`.

- [ ] **Step 2: Open the chat-header section of `ChatPanel.tsx` and visually verify**

Read the JSX of the chat header. Count the panel-related controls. If there are duplicates (e.g., separate "Preview" / "Files" / "Artifacts" launcher buttons that also open the panel), delete them.

- [ ] **Step 3: Ensure the single toggle has correct visual states**

The toggle should:
- Look neutral when the panel is closed (e.g., `text-text-03`, no background)
- Look accent-tinted when the panel is open (e.g., `text-action-link-04 bg-action-link-01`, or similar Opal tokens used elsewhere for active controls)

Check the existing toggle's implementation. If state-based styling is missing, add a `cn(... outputPanelOpen && "...")` clause using existing token classes.

- [ ] **Step 4: Type-check + smoke test**

Smoke test: toggle the panel open and closed. Confirm the toggle visually reflects the state.

- [ ] **Step 5: Commit (only if changes were made)**

```bash
git add web/src/app/craft/components/ChatPanel.tsx
git commit -m "refactor(craft): unify chat-header panel toggle (single button, stateful styling)"
```

If no changes were needed (the toggle is already singular and stateful), skip the commit. Move to Task 6.

---

## Task 6: Implement auto-open-on-first-preview behavior

**Files:**
- Modify: `web/src/app/craft/hooks/useBuildSessionStore.ts`
- Modify: `web/src/app/craft/components/ChatPanel.tsx`

Behavior: when a session's first webapp preview becomes available, set `outputPanelOpen = true` automatically — but only once per session, and never after the user has manually closed the panel.

- [ ] **Step 1: Add a session-scoped "user-dismissed-panel" flag**

In `useBuildSessionStore.ts`, add a new boolean field to `BuildSessionData`:

```typescript
  /** True if the user has manually closed the panel this session; suppresses auto-open-on-first-preview */
  panelManuallyDismissed: boolean;
```

Initial value in the default session block (alongside `outputPanelOpen: false`):

```typescript
  panelManuallyDismissed: false,
```

- [ ] **Step 2: Update the toggle action to set the flag when the user closes the panel**

Find the `toggleOutputPanel` action. When it's transitioning from open → closed, set `panelManuallyDismissed: true`. When transitioning closed → open, leave the flag alone (user explicitly chose to look at it; future auto-opens don't matter).

```typescript
toggleOutputPanel: () => {
  // ... existing logic ...
  const wasOpen = session.outputPanelOpen;
  const nextOpen = !wasOpen;
  return {
    sessions: newSessions.set(currentSessionId, {
      ...session,
      outputPanelOpen: nextOpen,
      panelManuallyDismissed: wasOpen ? true : session.panelManuallyDismissed,
    }),
  };
},
```

Use the existing action body as a base — only the additional flag-set is new.

- [ ] **Step 3: Add an auto-open action**

```typescript
// In the store actions:
maybeAutoOpenPanelForPreview: (sessionId: string) => void;

// Implementation:
maybeAutoOpenPanelForPreview: (sessionId: string) => {
  set((state) => {
    const session = state.sessions.get(sessionId);
    if (!session) return state;
    if (session.outputPanelOpen) return state; // already open
    if (session.panelManuallyDismissed) return state; // respect user dismissal

    const newSessions = new Map(state.sessions);
    newSessions.set(sessionId, {
      ...session,
      outputPanelOpen: true,
      activeOutputTab: "preview", // ensure Preview tab is shown
      activePanelTabId: null,
    });
    return { sessions: newSessions };
  });
},
```

- [ ] **Step 4: Trigger the auto-open from `ChatPanel.tsx` when `webappUrl` first becomes non-null**

In `ChatPanel.tsx`, find where `webappUrl` is consumed (grep for `webappUrl`). Add an effect that fires `maybeAutoOpenPanelForPreview` the first time `webappUrl` transitions from null → non-null:

```typescript
const webappUrl = useWebappUrl();
const maybeAutoOpenPanelForPreview = useBuildSessionStore(
  (s) => s.maybeAutoOpenPanelForPreview
);
const prevWebappUrlRef = useRef<string | null>(null);

useEffect(() => {
  const prev = prevWebappUrlRef.current;
  if (prev === null && webappUrl !== null && sessionId) {
    maybeAutoOpenPanelForPreview(sessionId);
  }
  prevWebappUrlRef.current = webappUrl;
}, [webappUrl, sessionId, maybeAutoOpenPanelForPreview]);
```

(Use the existing selectors/refs in `ChatPanel.tsx` — adapt names to match what's already imported. If `useWebappUrl` doesn't exist, derive from the existing session-data subscription.)

- [ ] **Step 5: Type-check + smoke test**

Start the app from scratch (no existing session). Send a message that triggers webapp build. Confirm: the panel auto-opens to Preview the first time the webapp URL appears. Close the panel manually. Trigger another build (`webappNeedsRefresh` increments). Confirm: panel does NOT re-open.

- [ ] **Step 6: Commit**

```bash
git add web/src/app/craft/hooks/useBuildSessionStore.ts \
        web/src/app/craft/components/ChatPanel.tsx
git commit -m "feat(craft): auto-open side panel on first webapp preview (once per session)"
```

---

## Task 7: Write the Playwright E2E test

**Files:**
- Create: `web/tests/e2e/craft-side-panel.spec.ts`

Reference: see other E2E files under `web/tests/e2e/` for the project's setup (auth, base URL, fixtures). Reuse the existing login helper (`a@example.com` / `a`) and any Craft-specific fixtures.

- [ ] **Step 1: Scaffold the test file**

```typescript
import { test, expect } from "@playwright/test";

test.describe("Craft side panel", () => {
  test.beforeEach(async ({ page }) => {
    // Use the project's existing auth helper. Example:
    // await loginAsUser(page, "a@example.com", "a");
    await page.goto("/craft");
  });

  test("opens via chat-header toggle and shows pinned tabs", async ({
    page,
  }) => {
    // Panel starts closed
    await expect(page.getByRole("region", { name: /side panel/i })).toHaveCount(
      0,
    );

    // Click the panel toggle in the chat header
    await page.getByRole("button", { name: /open panel/i }).click();

    // Three pinned tabs are visible
    await expect(page.getByRole("tab", { name: /preview/i })).toBeVisible();
    await expect(page.getByRole("tab", { name: /files/i })).toBeVisible();
    await expect(page.getByRole("tab", { name: /artifacts/i })).toBeVisible();
  });

  test("switching pinned tabs", async ({ page }) => {
    await page.getByRole("button", { name: /open panel/i }).click();
    await page.getByRole("tab", { name: /files/i }).click();
    await expect(page.getByRole("tab", { name: /files/i })).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });

  test("opening a file creates a transient tab; closing it returns to Files", async ({
    page,
  }) => {
    // Drive a Craft conversation that produces a file edit, then trigger
    // file open via an inline file link in the chat. The exact selectors
    // depend on the file-link component — discover them by inspecting
    // the live UI during test development.
  });

  test("panel state persists across close + reopen", async ({ page }) => {
    await page.getByRole("button", { name: /open panel/i }).click();
    await page.getByRole("tab", { name: /files/i }).click();

    // Close
    await page.getByRole("button", { name: /close panel/i }).click();
    await expect(page.getByRole("tab", { name: /files/i })).toHaveCount(0);

    // Reopen — should land on Files (last active), not Preview (default)
    await page.getByRole("button", { name: /open panel/i }).click();
    await expect(page.getByRole("tab", { name: /files/i })).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });

  test("auto-opens on first webapp preview, does not re-open after dismissal", async ({
    page,
  }) => {
    // Start a session that produces a webapp. The trigger conversation
    // depends on the test environment; use the same prompt other Craft
    // E2Es use to spin up a webapp build.
    // After webapp is ready: panel should be open on Preview.
    // Close it. Trigger a refresh. Panel should stay closed.
  });
});
```

Fill in the body of each `test()` per the exact selectors and helpers in the project's existing E2Es. The skeleton above shows the assertions to make.

- [ ] **Step 2: Run the test**

```bash
cd web && npx playwright test craft-side-panel.spec.ts
```

Expected: PASS.

If selectors fail, debug interactively:

```bash
cd web && npx playwright test craft-side-panel.spec.ts --headed --debug
```

- [ ] **Step 3: Commit**

```bash
git add web/tests/e2e/craft-side-panel.spec.ts
git commit -m "test(craft): Playwright E2E for universal side panel refactor"
```

---

## Task 8: Final verification + PR

- [ ] **Step 1: Full type-check + lint**

```bash
cd web && bun run typecheck
cd web && bun run lint
```

Both must pass.

- [ ] **Step 2: Run all relevant Playwright tests, not just the new one**

```bash
cd web && npx playwright test craft
```

Spot-check the broader Craft suite for regressions.

- [ ] **Step 3: Push the branch and open a PR**

Follow the project's PR template (`.github/pull_request_template.md`). Title:

```
refactor(craft): universal side panel — polymorphic PanelTab + auto-open on first preview
```

PR body sections per the template:
- **Description**: brief paragraph linking to the spec + summarizing the three deliverables (panel-tabs generalization, pin indicator, auto-open behavior)
- **How Has This Been Tested?**: `bun run typecheck`, `bun run lint`, the new Playwright E2E, manual smoke
- **Additional Options**: include the two template checkboxes verbatim:
  - `- [ ] [Optional] Please cherry-pick this PR to the latest release version.`
  - `- [ ] [Optional] Override Linear Check`

Base: `main`.

---

## Notes for the engineer

- **DRY:** `panelTabId()` is the single source of truth for transient tab IDs. Don't reinvent ID formats elsewhere.
- **YAGNI:** The discriminated union only has `kind: "file"` in this PR. Resist the urge to pre-add `kind: "subagent"` here — that lives in the follow-up subagents PR, which has its own tests and persistence path.
- **TDD spirit:** Per-task: type-check + smoke. End-of-feature: Playwright E2E. The refactor is structurally simple — type-check carries most of the verification weight.
- **Aesthetic:** Visual inspiration for tab chrome, slide animation, and active-state treatment: Cursor and Lovable's side panels. Lean compact and quiet; subtle active indicators; native-feel close × affordances on hover. The existing Opal tokens carry most of this — keep custom styling minimal.
- **Frequent commits:** each task ends in a commit. Don't bundle.
