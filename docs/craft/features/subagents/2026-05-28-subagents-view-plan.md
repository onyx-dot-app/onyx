# Subagents View — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make subagent activity visible in Craft — an agent strip above the input bar shows live subagent status, clicking a pill opens that subagent's transcript as a transient tab in the universal side panel.

**Architecture:** The frontend currently drops child-session SSE events via a strict parent-session filter; lift the filter and route events to per-subagent in-memory slots. Each `task` tool call card subscribes to its child subagent's slot for live status. Clicking a pill (or the task card) calls `openSubagentInPanel`, which adds a `kind: "subagent"` transient tab to the side panel. Persisted child-session messages already exist in the DB — the same router runs on session load to reconstruct subagent state.

**Tech Stack:** TypeScript, React, Zustand, Tailwind + Opal tokens, Playwright. No DB migration.

**Spec:** `docs/craft/features/subagents/2026-05-28-subagents-view-design.md`

**Prerequisites:** The universal-panel refactor (`docs/craft/features/universal-panel/2026-05-28-universal-panel-refactor-plan.md`) must land first. This plan assumes `PanelTab`, `panelTabId()`, `panelTabs`, `activePanelTabId`, and `setActivePanelTabId` already exist.

---

## File Structure

**Files to create:**
- `web/src/app/craft/components/AgentStrip.tsx` — strip above InputBar
- `web/src/app/craft/components/AgentPill.tsx` — single pill in the strip
- `web/src/app/craft/components/output-panel/SubagentTab.tsx` — panel body for `kind: "subagent"` tabs
- `web/tests/e2e/craft-subagents-view.spec.ts` — Playwright E2E

**Files to modify:**
- `web/src/app/craft/types/displayTypes.ts` — extend `PanelTab` union with `kind: "subagent"`; add `SubagentState` and `SubagentStatus` types
- `web/src/app/craft/utils/parsePacket.ts` — surface `parentSessionId` and `sessionId` from `state.metadata`
- `web/src/app/craft/utils/packetTypes.ts` — extend packet types to carry session-routing fields
- `web/src/app/craft/hooks/useBuildSessionStore.ts` — add `subagents` map, `openSubagentInPanel` action, selectors, extend `panelTabId()` for subagent kind
- `web/src/app/craft/hooks/useBuildStreaming.ts` — route by session ID at SSE-time AND historical-load time; create/update `SubagentState`
- `web/src/app/craft/components/OutputPanel.tsx` — render `kind: "subagent"` tab chrome and body
- `web/src/app/craft/components/ChatPanel.tsx` — mount `AgentStrip` above `InputBar`
- `web/src/app/craft/components/tool-cards/TaskBody.tsx` — slim down; clicking opens subagent in panel

**Files verified, not modified:**
- `backend/onyx/server/features/build/session/manager.py:1485-1604` — `_persist_sandbox_event` already dumps the entire event including `state.metadata`. Subagent child events are already persisted as chat-messages on the parent session, but with their own metadata identifying the child session. Frontend just needs to honor that metadata on load.

---

## Per-Task Verification Strategy

Per task: type-check + dev-server smoke. Full coverage via Playwright E2E in the final task.

---

## Task 1: Surface session metadata on parsed packets

**Files:**
- Modify: `web/src/app/craft/utils/parsePacket.ts`
- Modify: `web/src/app/craft/utils/packetTypes.ts`

Today `parsePacket` returns rich tool-call data but discards the `state.metadata` fields that identify which session each event belongs to. We need `parentSessionId` and `sessionId` on every parsed tool-call event so the streaming hook can route.

- [ ] **Step 1: Locate the existing tool-call packet shape**

```bash
grep -n "ParsedToolCallProgress\|ParsedToolCallStart\|subagentType" \
  web/src/app/craft/utils/packetTypes.ts \
  web/src/app/craft/utils/parsePacket.ts
```

- [ ] **Step 2: Add session-routing fields to packet types in `packetTypes.ts`**

Find each of `ParsedToolCallStart` and `ParsedToolCallProgress`. Add two fields:

```typescript
  /**
   * The opencode-serve session ID this event was emitted on. For the
   * parent Craft session, this is the parent's session ID. For a
   * subagent's child events, this is the child session's ID.
   */
  sessionId: string | null;
  /**
   * If non-null, this event is from a subagent dispatched from the
   * given parent session. Null for parent-session events.
   */
  parentSessionId: string | null;
```

- [ ] **Step 3: Populate the fields in `parsePacket.ts`**

In the same file, find `parseToolCallProgress` (and `parseToolCallStart` if applicable). Extract from the raw packet's `state.metadata`:

```typescript
// Near the top of parseToolCallProgress (and parseToolCallStart):
const stateObj = (p.state as Record<string, unknown> | undefined) ?? {};
const metadata = (stateObj.metadata as Record<string, unknown> | undefined) ?? {};
const sessionId = (metadata.sessionId as string | undefined) ?? null;
const parentSessionId =
  (metadata.parentSessionId as string | undefined) ?? null;
```

Add the fields to the returned object alongside the existing ones.

- [ ] **Step 4: Type-check**

```bash
cd web && bun run typecheck
```

Expected: PASS. Callers that don't yet use the new fields will silently ignore them; this is fine.

- [ ] **Step 5: Commit**

```bash
git add web/src/app/craft/utils/packetTypes.ts \
        web/src/app/craft/utils/parsePacket.ts
git commit -m "feat(craft): surface sessionId + parentSessionId from packet metadata"
```

---

## Task 2: Add `SubagentState` shape and `subagents` store slice

**Files:**
- Modify: `web/src/app/craft/types/displayTypes.ts`
- Modify: `web/src/app/craft/hooks/useBuildSessionStore.ts`

- [ ] **Step 1: Define types in `displayTypes.ts`**

Add at the bottom of the file:

```typescript
/** Lifecycle of a subagent dispatched via the `task` tool. */
export type SubagentStatus = "running" | "done" | "failed";

/**
 * In-memory state of a single subagent dispatched from the parent Craft
 * session. Keyed by the subagent's own opencode-serve session ID.
 */
export interface SubagentState {
  /** opencode-serve session ID of the subagent (child). */
  sessionId: string;
  /** Tool-call ID of the parent `task` call that launched this subagent. */
  parentToolCallId: string;
  /** Subagent type from the parent's `task` tool arguments (e.g., "explore"). */
  subagentType: string | null;
  /** Short label derived from the parent's task prompt. */
  name: string;
  status: SubagentStatus;
  /** Subagent's own tool calls, in chronological order. */
  toolCalls: ToolCallState[];
  startedAt: number;
  completedAt: number | null;
}
```

Then **extend the `PanelTab` discriminated union** with a subagent variant:

```typescript
export type PanelTab =
  | { kind: "file"; path: string; fileName: string }
  | { kind: "subagent"; subagentSessionId: string };
```

Update `panelTabId()`:

```typescript
export function panelTabId(tab: PanelTab): string {
  switch (tab.kind) {
    case "file":
      return `file:${tab.path}`;
    case "subagent":
      return `subagent:${tab.subagentSessionId}`;
  }
}
```

- [ ] **Step 2: Add `subagents` map to `BuildSessionData` in `useBuildSessionStore.ts`**

In the state shape (around line 290-325):

```typescript
  /** In-memory subagent state, keyed by the subagent's session ID. */
  subagents: Map<string, SubagentState>;
```

Initial value in the default block:

```typescript
  subagents: new Map(),
```

Import the new types:

```typescript
import type { SubagentState, SubagentStatus } from "@/app/craft/types/displayTypes";
```

- [ ] **Step 3: Add selector hooks**

```typescript
export const useSubagents = () =>
  useBuildSessionStore((state) => {
    const id = state.currentSessionId;
    if (!id) return new Map<string, SubagentState>();
    return state.sessions.get(id)?.subagents ?? new Map();
  });

export const useSubagent = (subagentSessionId: string | null) =>
  useBuildSessionStore((state) => {
    if (!subagentSessionId) return null;
    const id = state.currentSessionId;
    if (!id) return null;
    return state.sessions.get(id)?.subagents.get(subagentSessionId) ?? null;
  });
```

- [ ] **Step 4: Type-check**

```bash
cd web && bun run typecheck
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/app/craft/types/displayTypes.ts \
        web/src/app/craft/hooks/useBuildSessionStore.ts
git commit -m "feat(craft): add SubagentState store slice + extend PanelTab with subagent kind"
```

---

## Task 3: Add `openSubagentInPanel` action

**Files:**
- Modify: `web/src/app/craft/hooks/useBuildSessionStore.ts`

- [ ] **Step 1: Declare the action**

In the action interface section:

```typescript
openSubagentInPanel: (subagentSessionId: string) => void;
```

- [ ] **Step 2: Implement the action**

Add alongside the other panel-tab actions:

```typescript
openSubagentInPanel: (subagentSessionId: string) => {
  set((state) => {
    const sessionId = state.currentSessionId;
    if (!sessionId) return state;
    const session = state.sessions.get(sessionId);
    if (!session) return state;
    const subagent = session.subagents.get(subagentSessionId);
    if (!subagent) return state;

    const tab: PanelTab = { kind: "subagent", subagentSessionId };
    const tabId = panelTabId(tab);

    const existing = session.panelTabs.find(
      (t) => panelTabId(t) === tabId
    );
    const panelTabs = existing ? session.panelTabs : [...session.panelTabs, tab];

    // Push to history
    const { tabHistory } = session;
    const newEntry: TabHistoryEntry = { type: "panel-tab", tabId };
    const newEntries = [
      ...tabHistory.entries.slice(0, tabHistory.currentIndex + 1),
      newEntry,
    ];

    const updated: BuildSessionData = {
      ...session,
      outputPanelOpen: true,
      panelTabs,
      activePanelTabId: tabId,
      tabHistory: { entries: newEntries, currentIndex: newEntries.length - 1 },
      lastAccessed: new Date(),
    };
    const newSessions = new Map(state.sessions);
    newSessions.set(sessionId, updated);
    return { sessions: newSessions };
  });
},
```

Note the mirror with `openFilePreview` — same shape, different tab kind. Stays consistent with the panel-refactor's API.

- [ ] **Step 3: Type-check**

- [ ] **Step 4: Commit**

```bash
git add web/src/app/craft/hooks/useBuildSessionStore.ts
git commit -m "feat(craft): add openSubagentInPanel action for side-panel drill-in"
```

---

## Task 4: Route SSE events by session ID; create / update SubagentState

**Files:**
- Modify: `web/src/app/craft/hooks/useBuildStreaming.ts`

This is the core data-flow change.

- [ ] **Step 1: Locate the current session-filter**

```bash
grep -nE "sessionId|currentSessionId|parsed\.|tool_call|filter" \
  web/src/app/craft/hooks/useBuildStreaming.ts | head -40
```

Find the spot where each parsed packet is dispatched into the store. Today the dispatch is keyed only on the parent session.

- [ ] **Step 2: Add a routing helper**

In `useBuildStreaming.ts`, define a small classification function:

```typescript
/**
 * Decide whether a packet belongs to the parent Craft session's main
 * transcript or to a specific subagent's slot.
 */
function classifyPacket(
  packet: ParsedToolCallProgress | ParsedToolCallStart,
  parentSessionId: string
): { kind: "parent" } | { kind: "subagent"; sessionId: string } {
  // Child events carry parentSessionId === our session, and a distinct
  // sessionId (the child's own).
  if (
    packet.parentSessionId &&
    packet.parentSessionId === parentSessionId &&
    packet.sessionId &&
    packet.sessionId !== parentSessionId
  ) {
    return { kind: "subagent", sessionId: packet.sessionId };
  }
  return { kind: "parent" };
}
```

`parentSessionId` here is the *opencode-serve* session ID of the parent Craft session — get it from wherever the streaming hook already tracks it (likely from the session's `opencode_session_id` or equivalent). If not currently in scope, surface it as a hook argument.

- [ ] **Step 3: Add a store action to ingest a child tool-call event**

In `useBuildSessionStore.ts`, add:

```typescript
recordSubagentToolCall: (
  sessionId: string,
  subagentSessionId: string,
  parentToolCallId: string,
  toolCall: ToolCallState,
  subagentType: string | null,
  name: string,
) => void;
```

Implementation:

```typescript
recordSubagentToolCall: (
  sessionId, subagentSessionId, parentToolCallId, toolCall,
  subagentType, name,
) => {
  set((state) => {
    const session = state.sessions.get(sessionId);
    if (!session) return state;
    const existing = session.subagents.get(subagentSessionId);

    const updatedToolCalls = (() => {
      if (!existing) return [toolCall];
      const idx = existing.toolCalls.findIndex(
        (t) => t.toolCallId === toolCall.toolCallId
      );
      if (idx === -1) return [...existing.toolCalls, toolCall];
      const next = [...existing.toolCalls];
      next[idx] = toolCall;
      return next;
    })();

    const updatedSubagent: SubagentState = existing ?? {
      sessionId: subagentSessionId,
      parentToolCallId,
      subagentType,
      name,
      status: "running",
      toolCalls: [],
      startedAt: Date.now(),
      completedAt: null,
    };
    updatedSubagent.toolCalls = updatedToolCalls;

    const newSubagents = new Map(session.subagents);
    newSubagents.set(subagentSessionId, updatedSubagent);

    const newSessions = new Map(state.sessions);
    newSessions.set(sessionId, { ...session, subagents: newSubagents });
    return { sessions: newSessions };
  });
},

markSubagentComplete: (
  sessionId: string,
  subagentSessionId: string,
  status: SubagentStatus,
) => {
  set((state) => {
    const session = state.sessions.get(sessionId);
    if (!session) return state;
    const existing = session.subagents.get(subagentSessionId);
    if (!existing) return state;

    const newSubagents = new Map(session.subagents);
    newSubagents.set(subagentSessionId, {
      ...existing,
      status,
      completedAt: Date.now(),
    });
    const newSessions = new Map(state.sessions);
    newSessions.set(sessionId, { ...session, subagents: newSubagents });
    return { sessions: newSessions };
  });
},
```

- [ ] **Step 4: Wire the router into the streaming dispatch**

In `useBuildStreaming.ts`, at the point where each parsed packet is currently dispatched to the main transcript store, switch on `classifyPacket`:

```typescript
const cls = classifyPacket(parsed, parentOpencodeSessionId);
if (cls.kind === "subagent") {
  // Build the ToolCallState shape the store expects, the same way the
  // parent path does. Reuse the existing builder (likely in
  // useBuildSessionStore or a helper).
  recordSubagentToolCall(
    craftSessionId,
    cls.sessionId,
    /* parentToolCallId: from the parsed packet's task-tool context */,
    toolCallState,
    parsed.subagentType ?? null,
    deriveSubagentName(parsed),
  );

  // When the subagent's terminating event arrives (e.g., the `task` tool
  // status flips to "completed" on the parent side), also call
  // markSubagentComplete. Detection mirrors the existing task-completion
  // detection in the parent path.
} else {
  // Existing parent-transcript dispatch — unchanged.
  // ...
}
```

`parentToolCallId` for child events: the child event itself doesn't carry it directly, but the parent's `task` tool-call-start carries the child session ID in its metadata. Maintain a map `childSessionId → parentTaskToolCallId` in the streaming hook's local state, populated when the parent's `task` tool-start arrives. Look it up here.

- [ ] **Step 5: Apply the same routing on session-load**

The session-load path reads historical messages from the backend and replays them into the store. Find where load happens (grep for `loadSession` or similar in `useBuildSessionStore.ts` / `useBuildStreaming.ts`). The same `classifyPacket` logic applies — for each loaded message containing a tool-call event, decide parent vs subagent.

Re-use `recordSubagentToolCall` / `markSubagentComplete` for the historical events. The result is that subagents reconstruct correctly on reload.

- [ ] **Step 6: Smoke test**

Start the app, drive a conversation that dispatches a subagent (use the prompt from `backend/tests/external_dependency_unit/.../test_subagent_task_tool.py` as a reference). Confirm in browser devtools that the store's `subagents` map gets populated.

The UI doesn't yet render any of this — that lands in subsequent tasks. We're only verifying data flow.

- [ ] **Step 7: Type-check + Commit**

```bash
git add web/src/app/craft/hooks/useBuildStreaming.ts \
        web/src/app/craft/hooks/useBuildSessionStore.ts
git commit -m "feat(craft): route subagent SSE events to per-subagent store slots"
```

---

## Task 5: `SubagentTab` panel-body component

**Files:**
- Create: `web/src/app/craft/components/output-panel/SubagentTab.tsx`

Body rendered when the active panel tab is `kind: "subagent"`.

- [ ] **Step 1: Scaffold the component**

```tsx
"use client";

import { useSubagent } from "@/app/craft/hooks/useBuildSessionStore";
import CraftToolCard from "@/app/craft/components/tool-cards/CraftToolCard";
import { Text, Tag } from "@opal/components";
import { SvgBubbleText } from "@opal/icons";

interface SubagentTabProps {
  subagentSessionId: string;
}

export default function SubagentTab({ subagentSessionId }: SubagentTabProps) {
  const subagent = useSubagent(subagentSessionId);

  if (!subagent) {
    return (
      <div className="flex items-center justify-center h-full">
        <Text font="main-ui-muted" color="text-03">
          Subagent not found.
        </Text>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-2 px-3 py-2">
      <div className="flex items-center gap-2 px-1 py-1">
        {subagent.subagentType && (
          <Tag
            icon={SvgBubbleText}
            title={subagent.subagentType}
            color="purple"
          />
        )}
        <Text font="main-ui-body" color="text-02">
          {subagent.name}
        </Text>
        <Text
          font="main-ui-muted"
          color={subagent.status === "running" ? "action-link-04" : "text-03"}
          className="ml-auto"
        >
          {subagent.status === "running"
            ? `running · ${subagent.toolCalls.length} steps`
            : `${subagent.status} · ${subagent.toolCalls.length} steps`}
        </Text>
      </div>

      {subagent.toolCalls.map((toolCall, idx) => (
        <CraftToolCard
          key={toolCall.toolCallId}
          toolCall={toolCall}
          isFirstStep={idx === 0}
          isLastStep={idx === subagent.toolCalls.length - 1}
        />
      ))}
    </div>
  );
}
```

Verify the import paths match what's used elsewhere. Cross-check that `CraftToolCard` accepts these props (look at how `BuildMessageList` uses it today).

- [ ] **Step 2: Type-check + Commit**

```bash
git add web/src/app/craft/components/output-panel/SubagentTab.tsx
git commit -m "feat(craft): SubagentTab panel-body component"
```

---

## Task 6: Wire `kind: "subagent"` rendering into `OutputPanel.tsx`

**Files:**
- Modify: `web/src/app/craft/components/OutputPanel.tsx`

- [ ] **Step 1: Update tab-chrome rendering**

In the transient-tab map (introduced by the panel refactor), extend the `kind` switch:

```typescript
case "subagent": {
  const subagent = subagents.get(tab.subagentSessionId);
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
      {/* Subagent badge instead of file icon */}
      {subagent?.subagentType && (
        <Tag
          icon={SvgBubbleText}
          title={subagent.subagentType}
          color="purple"
          size="sm"
        />
      )}
      <Text className="truncate text-sm">{subagent?.name ?? "subagent"}</Text>
      {/* Close × — same pattern as the file case */}
      <button
        onClick={(e) => handlePanelTabClose(e, id, tab)}
        className={cn(
          "shrink-0 p-0.5 rounded-sm hover:bg-background-tint-03 transition-colors",
          isActive ? "opacity-100" : "opacity-0 group-hover:opacity-100",
        )}
        aria-label={`Close ${subagent?.name ?? "subagent"}`}
      >
        <SvgX size={12} className="stroke-text-03" />
      </button>
      {/* Curved joints when active — copy from the file case */}
    </button>
  );
}
```

Subscribe to `subagents` via `useSubagents()`.

- [ ] **Step 2: Update body rendering**

In the body switch:

```typescript
case "subagent":
  return <SubagentTab subagentSessionId={activeTab.subagentSessionId} />;
```

Import:

```typescript
import SubagentTab from "@/app/craft/components/output-panel/SubagentTab";
import { useSubagents } from "@/app/craft/hooks/useBuildSessionStore";
```

- [ ] **Step 3: Handle the close path for subagent tabs**

In `handlePanelTabClose`, extend the kind switch to call a future `closeSubagentTab` action — but the simplest implementation just generically removes the tab from `panelTabs`. Add a generic `closePanelTab(sessionId, tabId)` action in the store if not present from the refactor:

```typescript
closePanelTab: (sessionId: string, tabId: string) => void;
```

Implementation: mirror `closeFilePreview` but filter by tab ID instead of file path. Wire `handlePanelTabClose` to use this for any kind.

- [ ] **Step 4: Type-check + smoke test**

The subagent tab can't be opened from the UI yet (`AgentStrip` doesn't exist) — but if you manually call `openSubagentInPanel` from devtools, it should render.

- [ ] **Step 5: Commit**

```bash
git add web/src/app/craft/components/OutputPanel.tsx \
        web/src/app/craft/hooks/useBuildSessionStore.ts
git commit -m "feat(craft): render kind:subagent panel tabs in OutputPanel"
```

---

## Task 7: `AgentPill` component

**Files:**
- Create: `web/src/app/craft/components/AgentPill.tsx`

- [ ] **Step 1: Scaffold**

```tsx
"use client";

import { cn } from "@opal/utils";
import { Tag, Text } from "@opal/components";
import { SvgBubbleText } from "@opal/icons";
import {
  useActivePanelTabId,
  useBuildSessionStore,
} from "@/app/craft/hooks/useBuildSessionStore";
import { panelTabId } from "@/app/craft/types/displayTypes";
import type { SubagentState } from "@/app/craft/types/displayTypes";

interface AgentPillProps {
  subagent: SubagentState;
}

export default function AgentPill({ subagent }: AgentPillProps) {
  const activePanelTabId = useActivePanelTabId();
  const openSubagentInPanel = useBuildSessionStore(
    (s) => s.openSubagentInPanel,
  );

  const tabId = panelTabId({
    kind: "subagent",
    subagentSessionId: subagent.sessionId,
  });
  const isActive = activePanelTabId === tabId;
  const isRunning = subagent.status === "running";

  return (
    <button
      onClick={() => openSubagentInPanel(subagent.sessionId)}
      className={cn(
        "inline-flex items-center gap-1.5 px-2 py-1 rounded-md border transition-colors",
        "border-border-02 bg-background-neutral-00 hover:border-border-03",
        isActive && "border-action-link-04 bg-action-link-01",
      )}
    >
      {subagent.subagentType && (
        <Tag
          icon={SvgBubbleText}
          title={subagent.subagentType}
          color="purple"
          size="sm"
        />
      )}
      <Text font="secondary-body" color="text-02" nowrap>
        {subagent.name}
      </Text>
      {isRunning ? (
        <span
          className="size-1.5 rounded-full bg-action-link-04"
          aria-label="running"
        />
      ) : (
        <Text font="secondary-mono" color="text-03" nowrap>
          {subagent.status === "done" ? "✓" : "!"}
        </Text>
      )}
      <Text font="secondary-mono" color="text-03" nowrap>
        {subagent.toolCalls.length}
      </Text>
    </button>
  );
}
```

Verify token names against the codebase (`action-link-04`, `border-02`, etc. — these are the ones used in the panel mockups; cross-check actual tokens used elsewhere in the project).

- [ ] **Step 2: Type-check + Commit**

```bash
git add web/src/app/craft/components/AgentPill.tsx
git commit -m "feat(craft): AgentPill component for the agent strip"
```

---

## Task 8: `AgentStrip` component + mount in `ChatPanel.tsx`

**Files:**
- Create: `web/src/app/craft/components/AgentStrip.tsx`
- Modify: `web/src/app/craft/components/ChatPanel.tsx`

- [ ] **Step 1: Scaffold `AgentStrip.tsx`**

```tsx
"use client";

import { useMemo } from "react";
import { Text } from "@opal/components";
import { useSubagents } from "@/app/craft/hooks/useBuildSessionStore";
import AgentPill from "@/app/craft/components/AgentPill";

export default function AgentStrip() {
  const subagents = useSubagents();
  const list = useMemo(() => {
    return Array.from(subagents.values()).sort((a, b) => {
      // Running first, then by startedAt descending
      if (a.status === "running" && b.status !== "running") return -1;
      if (a.status !== "running" && b.status === "running") return 1;
      return b.startedAt - a.startedAt;
    });
  }, [subagents]);

  if (list.length === 0) return null;

  return (
    <div className="flex items-center gap-2 px-3 py-2 border border-border-02 bg-background-tint-01 rounded-md">
      <Text font="main-ui-muted" color="text-03">
        Agents
      </Text>
      <div className="flex flex-wrap items-center gap-1.5 min-w-0">
        {list.map((s) => (
          <AgentPill key={s.sessionId} subagent={s} />
        ))}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Mount in `ChatPanel.tsx`**

Find the slot above `InputBar` (the `ConnectorBannersRow` slot, vacated by the prep PR). Mount:

```tsx
import AgentStrip from "@/app/craft/components/AgentStrip";
// ...
<AgentStrip />
<InputBar ... />
```

`AgentStrip` returns `null` when there are no subagents, so no conditional is needed at the call site.

- [ ] **Step 3: Smoke test**

Drive a subagent-dispatching conversation. Confirm the strip appears with pills; clicking a pill opens the subagent tab in the panel.

- [ ] **Step 4: Type-check + Commit**

```bash
git add web/src/app/craft/components/AgentStrip.tsx \
        web/src/app/craft/components/ChatPanel.tsx
git commit -m "feat(craft): mount AgentStrip above InputBar"
```

---

## Task 9: Slim `TaskBody.tsx` and wire click → `openSubagentInPanel`

**Files:**
- Modify: `web/src/app/craft/components/tool-cards/TaskBody.tsx`

Currently `TaskBody` shows the prompt + final result. With the subagent tab in the panel doing the heavy lifting, the task card in chat becomes a compact summary card that can be clicked to drill in.

- [ ] **Step 1: Read the current `TaskBody.tsx`**

```bash
cat web/src/app/craft/components/tool-cards/TaskBody.tsx
```

- [ ] **Step 2: Rewrite**

```tsx
"use client";

import { Text, Tag } from "@opal/components";
import { SvgBubbleText } from "@opal/icons";
import {
  useBuildSessionStore,
  useSubagent,
} from "@/app/craft/hooks/useBuildSessionStore";
import type { ToolCardBodyProps } from "@/app/craft/components/tool-cards/interfaces";

export default function TaskBody({ toolCall }: ToolCardBodyProps) {
  const subagentSessionId =
    typeof toolCall.rawInput === "object" && toolCall.rawInput
      ? (toolCall.rawInput.session_id as string | undefined) ?? null
      : null;
  const subagent = useSubagent(subagentSessionId);
  const openSubagentInPanel = useBuildSessionStore(
    (s) => s.openSubagentInPanel,
  );

  const subagentType = toolCall.subagentType;
  const prompt = toolCall.command || toolCall.rawOutput;
  const output = toolCall.taskOutput;

  const handleClick = () => {
    if (subagentSessionId) openSubagentInPanel(subagentSessionId);
  };

  return (
    <button
      onClick={handleClick}
      className="text-left w-full border-l border-border-02 pl-3 flex flex-col gap-2 hover:bg-background-tint-01 rounded-r-md p-1 transition-colors"
    >
      {subagentType && (
        <div className="flex items-center gap-2">
          <Tag icon={SvgBubbleText} title={subagentType} color="purple" />
          <Text font="main-ui-muted" color="text-02">
            subagent
          </Text>
          {subagent && (
            <Text font="main-ui-muted" color="text-03" className="ml-auto">
              {subagent.status === "running"
                ? `running · ${subagent.toolCalls.length} steps`
                : `${subagent.status} · ${subagent.toolCalls.length} steps`}
            </Text>
          )}
        </div>
      )}

      {prompt && (
        <div>
          <Text font="main-ui-muted" color="text-02">
            Prompt
          </Text>
          <div className="mt-1 overflow-auto max-h-[14rem] whitespace-pre-wrap wrap-break-word">
            <Text as="p" font="secondary-body" color="text-04">
              {prompt}
            </Text>
          </div>
        </div>
      )}

      {output && (
        <div>
          <Text font="main-ui-muted" color="text-02">
            Result
          </Text>
          <div className="mt-1 overflow-auto max-h-[20rem] whitespace-pre-wrap wrap-break-word">
            <Text as="p" font="main-content-body" color="text-04">
              {output}
            </Text>
          </div>
        </div>
      )}

      <Text font="main-ui-muted" color="action-link-04">
        View transcript →
      </Text>
    </button>
  );
}
```

Important: extracting `subagentSessionId` from `toolCall.rawInput` is the load-bearing assumption — verify the field name against an actual `task` tool's raw input (might be `session_id`, `child_session_id`, or `task_id`). Adjust accordingly.

- [ ] **Step 3: Type-check + smoke test**

Click on a task card → panel opens to that subagent.

- [ ] **Step 4: Commit**

```bash
git add web/src/app/craft/components/tool-cards/TaskBody.tsx
git commit -m "refactor(craft): slim TaskBody; clicking opens subagent in panel"
```

---

## Task 10: Backend verification — child events carry session metadata

**Files:**
- Read: `backend/onyx/server/features/build/session/manager.py` (especially `_persist_sandbox_event`)
- Possibly modify: same file, or `backend/onyx/server/features/build/sandbox/event_schema.py`

The frontend relies on each persisted `chat_message`'s `message_metadata` containing `state.metadata.sessionId` and `state.metadata.parentSessionId`. Per the existing code (`manager.py:1537-1541`), the entire `sandbox_event` is dumped with `model_dump(mode="json", by_alias=True, exclude_none=False)`. The ACP `ToolCallProgress` schema includes `state.metadata`. Verify:

- [ ] **Step 1: Dump a sample event during a subagent run**

Add temporary logging in `_persist_sandbox_event` for any `ToolCallProgress` whose `state.metadata.parentSessionId` is set. Confirm the persisted `event_data` includes both `sessionId` and `parentSessionId`.

Drive a subagent conversation; inspect the resulting `chat_message.message_metadata` in the DB:

```bash
docker exec -it onyx-relational_db-1 psql -U postgres -c \
  "SELECT message_metadata FROM chat_message WHERE message_metadata->'state'->'metadata'->>'parentSessionId' IS NOT NULL ORDER BY id DESC LIMIT 3;"
```

Expected: rows exist with `state.metadata.sessionId` and `state.metadata.parentSessionId` populated.

- [ ] **Step 2: If metadata is missing**

If `state.metadata` is being stripped somewhere upstream (rare — ACP schema preserves it), trace `event_data` through the dump path and ensure `state` is included. If not, augment the persistence to include the routing fields explicitly. Concretely: when building `event_data`, if `state.metadata` is missing but the event carries those fields elsewhere, copy them in.

- [ ] **Step 3: Remove the temporary logging**

- [ ] **Step 4: Commit (only if any change was needed)**

```bash
git add backend/onyx/server/features/build/session/manager.py
git commit -m "fix(craft): ensure subagent session metadata persists in chat_message"
```

If no changes were needed (metadata is already there), skip the commit.

---

## Task 11: Playwright E2E

**Files:**
- Create: `web/tests/e2e/craft-subagents-view.spec.ts`

Reference: see other E2Es under `web/tests/e2e/` for fixtures and auth.

- [ ] **Step 1: Scaffold the test**

```typescript
import { test, expect } from "@playwright/test";

test.describe("Craft subagents view", () => {
  test.beforeEach(async ({ page }) => {
    // Reuse project login helper
    await page.goto("/craft");
  });

  test("subagent dispatch surfaces strip + panel tab", async ({ page }) => {
    // Send a prompt that dispatches a subagent. The exact wording can
    // mirror the integration test backend/tests/external_dependency_unit/
    // ...test_subagent_task_tool.py uses.
    await page
      .getByPlaceholder(/continue the conversation/i)
      .fill("Use a subagent to explore the auth code.");
    await page.keyboard.press("Enter");

    // Wait for the task card to appear in the main transcript
    await expect(page.getByText(/subagent/i)).toBeVisible({ timeout: 30_000 });

    // AgentStrip pill appears above the input
    const agentStrip = page.getByRole("region", { name: /agents/i });
    await expect(agentStrip).toBeVisible();
    const pill = agentStrip.getByRole("button").first();
    await expect(pill).toBeVisible();

    // Click the pill — panel opens, transient subagent tab activates
    await pill.click();
    await expect(
      page.getByRole("tab", { name: /explore/i }),
    ).toHaveAttribute("aria-selected", "true");

    // The main chat is still visible (one-stream-at-a-time DESIGN says no
    // chat swap)
    await expect(
      page.getByText("Use a subagent to explore the auth code."),
    ).toBeVisible();

    // The subagent's tool calls populate the panel
    await expect(
      page.getByRole("tabpanel").getByText(/grep|read|search/i).first(),
    ).toBeVisible({ timeout: 30_000 });
  });

  test("closing the subagent tab keeps the strip pill", async ({ page }) => {
    // Reach the same state as above, then close the panel tab × button
    // Assert: panel tab gone; strip pill still present
  });

  test("reload restores the strip from persisted state", async ({ page }) => {
    // Drive a subagent dispatch, wait for it to complete, reload the page.
    // Assert: pill is back; clicking it reopens the transcript.
  });

  test("completion: pill shows done state with step count", async ({
    page,
  }) => {
    // Wait for the subagent to finish; assert pill shows ✓ and the step count
  });
});
```

- [ ] **Step 2: Run**

```bash
cd web && npx playwright test craft-subagents-view.spec.ts
```

If selectors fail, iterate with `--headed --debug`.

- [ ] **Step 3: Commit**

```bash
git add web/tests/e2e/craft-subagents-view.spec.ts
git commit -m "test(craft): Playwright E2E for subagents view"
```

---

## Task 12: Final verification + PR

- [ ] **Step 1: Full type-check + lint**

```bash
cd web && bun run typecheck && bun run lint
```

- [ ] **Step 2: Spot-check related E2Es**

```bash
cd web && npx playwright test craft
```

- [ ] **Step 3: Open PR**

Title:

```
feat(craft): subagents view — agent strip + side-panel transient tabs
```

PR body per `.github/pull_request_template.md`:
- **Description**: brief, link to the spec, note the dependency on the panel-refactor PR
- **How Has This Been Tested?**: typecheck, lint, new Playwright E2E, manual smoke
- **Additional Options**: include the two template checkboxes verbatim:
  - `- [ ] [Optional] Please cherry-pick this PR to the latest release version.`
  - `- [ ] [Optional] Override Linear Check`

Base: `main`. The panel-refactor PR must be merged first.

---

## Notes for the engineer

- **DRY:** Reuse the `PanelTab` discriminated union pattern. The subagent kind plugs into the same machinery as the file kind.
- **YAGNI:** Don't add a "back to main" affordance (no chat swap is happening — main is already visible). Don't add nested-subagent support (subagents-of-subagents) — the spec is one level deep.
- **TDD spirit:** Type-check + smoke per task; Playwright at the end.
- **Aesthetic:** Strip and pills should look like AgentStrip in our mockups — compact, Opal-token colors, no heavy chrome. Subagent badge uses `purple` Tag color (same as existing TaskBody).
- **Watch out for:** the `subagentSessionId` extraction in `TaskBody.tsx` — verify the actual field name in the task tool's raw input before relying on it. If it's not where I guessed, adjust the extraction.
- **Frequent commits:** each task ends in a commit.
