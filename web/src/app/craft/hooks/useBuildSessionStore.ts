"use client";

import { create } from "zustand";

import {
  ApiSessionResponse,
  Artifact,
  ArtifactType,
  BuildMessage,
  BuildMessageAttachment,
  SessionHistoryItem,
  SessionOrigin,
  SessionStatus,
  SandboxRuntimeState,
  type OutputFile,
  type OutputInventory,
} from "@/app/craft/types/streamingTypes";

import {
  StreamItem,
  ToolCallState,
  TodoListState,
  type ContextUsage,
  type PanelTab,
  panelTabId,
  type SubagentState,
  type SubagentStatus,
  type SubagentTurn,
} from "@/app/craft/types/displayTypes";

import { MAX_QUEUED_MESSAGES } from "@/app/app/interfaces";

import {
  createSession as apiCreateSession,
  fetchSession,
  fetchSessionHistory,
  generateSessionName,
  updateSessionName,
  deleteSession as apiDeleteSession,
  fetchMessages,
  fetchActiveTurn,
  fetchArtifacts,
  fetchOutputInventory,
  fetchWebappInfo,
  restoreSession,
} from "@/app/craft/services/apiServices";

import { genId } from "@/app/craft/utils/streamItemHelpers";
import { parsePacket } from "@/app/craft/utils/parsePacket";
import {
  classifySubagentEvent,
  toolCallStateFromProgress,
  subagentNameFromTask,
  cleanTaskOutput,
} from "@/app/craft/utils/subagentRouting";

/**
 * Convert loaded messages (with message_metadata) to StreamItem[] format.
 *
 * The backend stores messages with these packet types in message_metadata:
 * - user_message: {type: "user_message", content: {type: "text", text: "..."}}
 * - agent_message: {type: "agent_message", content: {type: "text", text: "..."}}
 * - agent_thought: DB-stored thinking rows restored as collapsed stream items
 * - tool_call_progress: Full tool call data with status="completed"
 * - agent_plan_update: Plan entries (not rendered as stream items)
 *
 * This function converts agent messages to StreamItem[] for rendering.
 */
function convertMessagesToStreamItems(messages: BuildMessage[]): StreamItem[] {
  const items: StreamItem[] = [];

  for (const message of messages) {
    if (message.type === "user") continue;

    const metadata = message.message_metadata;
    if (!metadata || typeof metadata !== "object") continue;

    // The synthetic task-output message duplicates the subagent's final
    // response; it lives in the subagent panel, never the main transcript.
    if ((metadata as Record<string, unknown>).source === "task_output") {
      continue;
    }

    // SAME parsePacket — identical classification for both code paths
    const packet = parsePacket(metadata);

    switch (packet.type) {
      case "text_chunk":
        if (packet.sessionId && packet.parentSessionId) {
          break;
        }
        if (packet.text) {
          items.push({
            type: "text",
            id: message.id || genId("text"),
            content: packet.text,
            isStreaming: false,
          });
        }
        break;

      case "thinking_chunk":
        if (packet.sessionId && packet.parentSessionId) {
          break;
        }
        if (packet.text) {
          items.push({
            type: "thinking",
            id: message.id || genId("thinking"),
            content: packet.text,
            isStreaming: false,
          });
        }
        break;

      case "tool_call_progress":
        // Child (subagent-internal) tool events do NOT belong in the main
        // transcript — they are reconstructed into session.subagents instead.
        if (classifySubagentEvent(packet).kind === "child") {
          break;
        }
        if (packet.isTodo) {
          // Upsert: update existing todo_list or create new one
          const existingIdx = items.findIndex(
            (item) =>
              item.type === "todo_list" &&
              item.todoList.id === packet.toolCallId
          );
          if (existingIdx >= 0) {
            const existing = items[existingIdx];
            if (existing && existing.type === "todo_list") {
              items[existingIdx] = {
                ...existing,
                todoList: { ...existing.todoList, todos: packet.todos },
              };
            }
          } else {
            items.push({
              type: "todo_list",
              id: packet.toolCallId,
              todoList: {
                id: packet.toolCallId,
                todos: packet.todos,
                isOpen: false,
              },
            });
          }
        } else {
          items.push({
            type: "tool_call",
            id: packet.toolCallId,
            toolCall: {
              id: packet.toolCallId,
              kind: packet.kind,
              // toolName/skillName/taskOutput must be carried through here too
              // (not just the live-stream path) or reloaded sessions lose them:
              // e.g. a skill card would fall back to "Running skill" and
              // websearch/webfetch would render as GenericBody.
              toolName: packet.toolName,
              title: packet.title,
              description: packet.description,
              command: packet.command,
              status: packet.status,
              rawOutput: packet.rawOutput,
              subagentType: packet.subagentType ?? undefined,
              skillName: packet.skillName ?? undefined,
              taskOutput: packet.taskOutput ?? undefined,
              isNewFile: packet.isNewFile,
              oldContent: packet.oldContent,
              newContent: packet.newContent,
            },
          });
        }
        break;

      case "compaction":
        items.push({
          type: "compaction",
          id: message.id || genId("compaction"),
          summary: packet.summary,
        });
        break;

      case "error":
        // Persisted terminal-failure rows (e.g. turn hard-cap).
        if (packet.message) {
          items.push({
            type: "error",
            id: message.id || genId("error"),
            content: packet.message,
          });
        }
        break;

      default:
        break;
    }
  }

  return items;
}

function deriveContextUsage(messages: BuildMessage[]): ContextUsage | null {
  for (let i = messages.length - 1; i >= 0; i--) {
    const metadata = messages[i]?.message_metadata;
    if (!metadata || typeof metadata !== "object") continue;
    const packet = parsePacket(metadata);
    if (packet.type === "context_usage") {
      return { usedTokens: packet.usedTokens };
    }
  }
  return null;
}

/**
 * Reconstruct the subagents Map from persisted messages.
 *
 * Applies the SAME classification as the live SSE path:
 * - child events  → append toolCalls keyed by the child session id
 * - parent task   → seed meta (parentToolCallId, subagentType, name) and set
 *                   status from the task event's terminal status
 *
 * Child events may arrive before OR after the parent task event that names
 * them, so identifying fields are backfilled without clobbering known values.
 */
function emptyTurn(prompt = ""): SubagentTurn {
  return {
    prompt,
    toolCalls: [],
    thinking: null,
    response: null,
    streamItems: [],
  };
}

function isPlaceholderSubagentLabel(value: string): boolean {
  return value.trim() === "Spawning subagent";
}

function settleStreamItems(items: StreamItem[]): StreamItem[] {
  return items.map((item) =>
    item.type === "text" || item.type === "thinking"
      ? { ...item, isStreaming: false }
      : item
  );
}

function upsertToolStreamItem(
  items: StreamItem[],
  toolCall: ToolCallState
): StreamItem[] {
  const idx = items.findIndex(
    (item) => item.type === "tool_call" && item.id === toolCall.id
  );
  if (idx >= 0) {
    return items.map((item, i) =>
      i === idx ? { type: "tool_call", id: toolCall.id, toolCall } : item
    );
  }
  return [...items, { type: "tool_call", id: toolCall.id, toolCall }];
}

function appendStreamingSubagentChunk(
  items: StreamItem[],
  type: "text" | "thinking",
  text: string
): StreamItem[] {
  const last = items[items.length - 1];
  if (last?.type === type) {
    return items.map((item, i) =>
      i === items.length - 1
        ? { ...last, content: last.content + text, isStreaming: true }
        : item.type === "text" || item.type === "thinking"
          ? { ...item, isStreaming: false }
          : item
    );
  }
  return [
    ...settleStreamItems(items),
    {
      type,
      id: genId(type),
      content: text,
      isStreaming: true,
    },
  ];
}

function replaceOrAppendSettledTextItem(
  items: StreamItem[],
  text: string | null
): StreamItem[] {
  const settled = settleStreamItems(items);
  if (!text) {
    return settled;
  }

  let lastTextIndex = -1;
  settled.forEach((item, index) => {
    if (item.type === "text") {
      lastTextIndex = index;
    }
  });

  if (lastTextIndex === -1) {
    return settleStreamItems(
      appendStreamingSubagentChunk(settled, "text", text)
    );
  }

  return settled.map((item, index) =>
    index === lastTextIndex && item.type === "text"
      ? { ...item, content: text, isStreaming: false }
      : item
  );
}

function buildSubagentsFromMessages(
  messages: BuildMessage[]
): Map<string, SubagentState> {
  const subagents = new Map<string, SubagentState>();

  function ensure(subagentSessionId: string): SubagentState {
    const existing = subagents.get(subagentSessionId);
    if (existing) return existing;
    const created: SubagentState = {
      sessionId: subagentSessionId,
      parentToolCallId: "",
      subagentType: null,
      name: "",
      status: "running",
      turns: [emptyTurn()],
      startedAt: Date.now(),
      completedAt: null,
    };
    subagents.set(subagentSessionId, created);
    return created;
  }

  /** Upsert a tool call into the last turn (best-effort for follow-ups). */
  function appendToolCallToLastTurn(
    sa: SubagentState,
    toolCall: ToolCallState
  ): SubagentTurn[] {
    const turns = sa.turns.length > 0 ? [...sa.turns] : [emptyTurn()];
    const last = turns[turns.length - 1] ?? emptyTurn();
    const idx = last.toolCalls.findIndex((tc) => tc.id === toolCall.id);
    const toolCalls =
      idx >= 0
        ? last.toolCalls.map((tc, i) => (i === idx ? toolCall : tc))
        : [...last.toolCalls, toolCall];
    turns[turns.length - 1] = {
      ...last,
      toolCalls,
      streamItems: upsertToolStreamItem(last.streamItems, toolCall),
    };
    return turns;
  }

  for (const message of messages) {
    if (message.type === "user") continue;
    const metadata = message.message_metadata;
    if (!metadata || typeof metadata !== "object") continue;

    const packet = parsePacket(metadata);

    // Best-effort follow-up response reconstruction: a child agent_message
    // (tagged with _meta.parentSessionId) carries a follow-up turn's response.
    // Follow-up turns do not persist their prompt, so this is the only signal.
    if (packet.type === "text_chunk" || packet.type === "thinking_chunk") {
      if (packet.sessionId && packet.parentSessionId && packet.text) {
        const sa = ensure(packet.sessionId);
        const turns = sa.turns.length > 0 ? [...sa.turns] : [emptyTurn()];
        const last = turns[turns.length - 1] ?? emptyTurn();
        if (packet.type === "text_chunk") {
          turns[turns.length - 1] = {
            ...last,
            response: (last.response ?? "") + packet.text,
            streamItems: settleStreamItems(
              appendStreamingSubagentChunk(
                last.streamItems,
                "text",
                packet.text
              )
            ),
          };
        } else {
          turns[turns.length - 1] = {
            ...last,
            thinking: (last.thinking ?? "") + packet.text,
            streamItems: settleStreamItems(
              appendStreamingSubagentChunk(
                last.streamItems,
                "thinking",
                packet.text
              )
            ),
          };
        }
        subagents.set(packet.sessionId, { ...sa, turns });
      }
      continue;
    }

    if (packet.type !== "tool_call_progress") continue;

    const cls = classifySubagentEvent(packet);

    if (cls.kind === "child") {
      const sa = ensure(cls.subagentSessionId);
      const toolCall = toolCallStateFromProgress(packet);
      subagents.set(cls.subagentSessionId, {
        ...sa,
        turns: appendToolCallToLastTurn(sa, toolCall),
      });
    } else if (cls.kind === "parentTask") {
      const sa = ensure(cls.subagentSessionId);
      const status: SubagentStatus =
        packet.status === "completed"
          ? "done"
          : packet.status === "failed" || packet.status === "cancelled"
            ? "failed"
            : "running";
      // The parent task event drives the INITIAL turn's prompt + response.
      const turns = sa.turns.length > 0 ? [...sa.turns] : [emptyTurn()];
      const firstTurn = turns[0] ?? emptyTurn();
      const response =
        status === "running"
          ? firstTurn.response
          : (firstTurn.response ?? cleanTaskOutput(packet.taskOutput));
      turns[0] = {
        ...firstTurn,
        prompt: firstTurn.prompt || packet.command,
        response,
        streamItems: replaceOrAppendSettledTextItem(
          firstTurn.streamItems,
          response
        ),
      };
      subagents.set(cls.subagentSessionId, {
        ...sa,
        parentToolCallId: sa.parentToolCallId || packet.toolCallId,
        subagentType: sa.subagentType ?? packet.subagentType,
        name: sa.name || subagentNameFromTask(packet),
        status,
        turns,
        completedAt: status === "running" ? sa.completedAt : Date.now(),
      });
    }
  }

  return subagents;
}

/** Persisted turn-failure rows are only relevant while they're the latest
 * thing in the transcript — once any later activity exists, a stale
 * "turn stopped" banner mid-history is just noise. */
function stripSupersededErrors(messages: BuildMessage[]): BuildMessage[] {
  const isErrorRow = (message: BuildMessage) =>
    message.type === "assistant" && message.message_metadata?.type === "error";
  const lastActivityIdx = messages.findLastIndex(
    (message) => !isErrorRow(message)
  );
  return messages.filter(
    (message, idx) => idx > lastActivityIdx || !isErrorRow(message)
  );
}

/**
 * Consolidate raw backend messages into proper conversation turns.
 *
 * The backend stores each streaming packet as a separate message. This function:
 * 1. Groups consecutive agent messages (between user messages) into turns
 * 2. Converts each group's packets to streamItems
 * 3. Creates consolidated messages with streamItems in message_metadata
 *
 * Returns: Array of consolidated messages (user messages + one agent message per turn)
 */
function consolidateMessagesIntoTurns(
  rawMessages: BuildMessage[]
): BuildMessage[] {
  rawMessages = stripSupersededErrors(rawMessages);
  const consolidated: BuildMessage[] = [];
  let currentAgentPackets: BuildMessage[] = [];

  function flushCurrentAgentPackets() {
    if (currentAgentPackets.length === 0) return;

    const streamItems = convertMessagesToStreamItems(currentAgentPackets);
    const textContent = streamItems
      .filter((item) => item.type === "text")
      .map((item) => item.content)
      .join("");

    if (streamItems.length > 0 || textContent) {
      consolidated.push({
        id: currentAgentPackets[0]?.id || genId("agent-msg"),
        type: "assistant",
        content: textContent,
        timestamp: currentAgentPackets[0]?.timestamp || new Date(),
        turn_index: currentAgentPackets[0]?.turn_index,
        message_metadata: {
          streamItems,
        },
      });
    }
    currentAgentPackets = [];
  }

  for (const message of rawMessages) {
    if (message.type === "user") {
      // If we have accumulated agent packets, consolidate them into one message
      flushCurrentAgentPackets();
      // Add the user message as-is
      consolidated.push(message);
    } else if (message.type === "assistant") {
      // Check if this message already has consolidated streamItems (from new format)
      if (message.message_metadata?.streamItems) {
        // Already consolidated, add as-is
        // Flush any pending packets first
        flushCurrentAgentPackets();
        consolidated.push(message);
      } else {
        // Old format - accumulate for consolidation
        currentAgentPackets.push(message);
      }
    }
  }

  // Don't forget any trailing agent packets
  flushCurrentAgentPackets();

  return consolidated;
}

function splitActiveTurnTranscript(
  messages: BuildMessage[],
  activeTurnIndex: number | null
): { messages: BuildMessage[]; streamItems: StreamItem[] } {
  if (activeTurnIndex === null) {
    return { messages, streamItems: [] };
  }

  const activeStreamItems: StreamItem[] = [];
  const settledMessages: BuildMessage[] = [];

  for (const message of messages) {
    if (
      message.type === "assistant" &&
      message.turn_index === activeTurnIndex
    ) {
      const streamItems = message.message_metadata?.streamItems;
      if (Array.isArray(streamItems)) {
        activeStreamItems.push(...(streamItems as StreamItem[]));
      }
      continue;
    }
    settledMessages.push(message);
  }

  return { messages: settledMessages, streamItems: activeStreamItems };
}

function mapApiSessionStatus(
  apiStatus: ApiSessionResponse["status"]
): SessionStatus {
  switch (apiStatus) {
    case "active":
      return "active";
    case "initializing":
      // Backend is still building the workspace (or a create was
      // interrupted); the next create/restore repairs it.
      return "creating";
    default:
      // "idle" and "failed" both recover through the restore flow.
      return "idle";
  }
}

// Re-export types for consumers
export type { Artifact, ArtifactType, SessionHistoryItem };

// =============================================================================
// Store Types (mirrors chat's useChatSessionStore pattern)
// =============================================================================

/** Pre-provisioning state machine - exactly one of these states at a time */
export type PreProvisioningState =
  | { status: "idle" }
  | { status: "provisioning" }
  | { status: "ready"; sessionId: string }
  | { status: "starting"; sessionId: string }
  | { status: "failed"; error: string; retryCount: number; retryAt: number };

// Module-level variable to store the provisioning promise (not in Zustand state for serializability)
let provisioningPromise: Promise<string | null> | null = null;
const webappReadinessChecks = new Map<string, Promise<boolean>>();
const outputInventoryRequests = new Map<string, Promise<void>>();

// Monotonic id for queued messages (kept out of Zustand state for simplicity).
let nextQueuedMessageId = 1;

interface CraftQueuedMessage {
  id: number;
  text: string;
  attachments: BuildMessageAttachment[];
}

const EMPTY_CRAFT_QUEUED_MESSAGES: readonly CraftQueuedMessage[] = [];

/** Files tab state - persisted across tab switches */
export interface FilesTabState {
  expandedPaths: string[];
  scrollTop: number;
}

/** Tab history entry - can be a pinned tab or a transient panel tab */
export type TabHistoryEntry =
  | { type: "pinned"; tab: OutputTabType }
  | { type: "panel-tab"; tabId: string };

/** Browser-style tab navigation history */
export interface TabNavigationHistory {
  entries: TabHistoryEntry[];
  currentIndex: number;
}

/** Output panel tab types */
export type OutputTabType = "preview" | "files" | "artifacts";

export interface BuildSessionData {
  id: string;
  instanceId: string;
  status: SessionStatus;
  messages: BuildMessage[];
  artifacts: Artifact[];
  /** Active backend turn, if this session is currently running. */
  activeTurnId: string | null;
  pendingCompletedTurnId: string | null;
  /** The user-message turn index for the active backend turn. */
  activeTurnIndex: number | null;
  /** True when this tab created the active turn and already owns its stream. */
  activeTurnLocalOwner: boolean;
  /**
   * FIFO stream items for the current agent turn.
   * Items are stored in chronological order as they arrive.
   * Rendered directly without transformation.
   */
  streamItems: StreamItem[];
  /**
   * Messages typed while a response is streaming. Auto-sent FIFO once the
   * current run finishes (see the auto-send effect in BuildChatPanel).
   */
  queuedMessages: CraftQueuedMessage[];
  /**
   * True between an interrupt request and the turn actually terminating. Drives
   * the "stopping…" affordance; cleared by each terminal stream handler (and on
   * a fresh turn / aborted fetch).
   */
  isInterrupting: boolean;
  /**
   * True from a user interrupt until the next turn starts. Drives the transient
   * "Response stopped" notice; cleared when a new message is sent.
   */
  wasInterrupted: boolean;
  /**
   * Bumped per new interactive turn; a pending reconcileInterruptedTurn bails
   * when it changes, so a stale reconcile can't clobber the superseding turn.
   */
  turnGeneration: number;
  loadGeneration: number;
  error: string | null;
  webappUrl: string | null;
  /** Backend sandbox state plus transient client-owned lifecycle states. */
  sandbox: SandboxRuntimeState | null;
  /** Model this session runs on (from the row); seeds the composer picker. */
  agentProvider: string | null;
  agentModel: string | null;
  skillsStale: boolean;
  /** Incremented only with skillsStale so async refreshes can reject stale responses. */
  skillsStaleRevision: number;
  origin: SessionOrigin;
  abortController: AbortController;
  lastAccessed: Date;
  isLoaded: boolean;
  contextUsage: ContextUsage | null;
  outputPanelOpen: boolean;
  /** Counter to trigger webapp refresh when web/ files change (increments on each edit) */
  webappNeedsRefresh: number;
  /** Counter to force an iframe remount (restore only — live edits are handled by HMR) */
  webappNeedsRemount: number;
  /** Counter to trigger files list refresh when outputs/ directory changes (increments on each write/edit) */
  filesNeedsRefresh: number;
  /** Transient panel tabs open in this session (files, subagents, etc.) */
  panelTabs: PanelTab[];
  /** Subagents spawned in this session, keyed by child opencode session id. */
  subagents: Map<string, SubagentState>;
  /**
   * When non-null, the main (left) column shows this subagent's transcript
   * in place of the chat. `null` = normal chat view.
   */
  viewedSubagentSessionId: string | null;
  /** Active pinned tab in output panel */
  activeOutputTab: OutputTabType;
  /** Active transient panel tab ID (when set, takes precedence over pinned tab) */
  activePanelTabId: string | null;
  /** Files tab state - expanded folders and scroll position */
  filesTabState: FilesTabState;
  /** Browser-style tab navigation history for back/forward */
  tabHistory: TabNavigationHistory;
  /** Shared metadata for discovery, Artifacts, and preview revisions. */
  outputInventory: Record<string, OutputFile> | null;
  outputInventoryStatus: "loading" | "complete" | "partial" | "error";
  /** Automatic discovery starts after the first complete inventory. */
  outputBaselinePending: boolean;
  /** Explicit preview reloads, keyed by file path. File edits use inventory revisions. */
  filePreviewRefreshKeys: Record<string, number>;
  /** Manual navigation, panel dismissal, or the first automatic selection locks selection until the next task. */
  outputSelectionLocked: boolean;
}

// Prefer deliverables over slide images and supporting notes within one batch.
function outputPreviewPriority(path: string): number {
  if (/\.pptx?$/i.test(path)) return 0;
  if (/\.pdf$/i.test(path)) return 1;
  if (/\.md$/i.test(path)) return 2;
  if (/\.(png|jpe?g|gif|webp|svg|bmp|ico|avif)$/i.test(path)) return 3;
  return 4;
}

function compareOutputInventory(
  previous: Record<string, OutputFile>,
  inventory: OutputInventory
) {
  const files: Record<string, OutputFile> = inventory.complete
    ? {}
    : { ...previous };
  const added: OutputFile[] = [];
  const changed: string[] = [];
  for (const file of inventory.files) {
    files[file.path] = file;
    if (previous[file.path] === undefined) added.push(file);
    else if (previous[file.path]?.revision !== file.revision)
      changed.push(file.path);
  }
  if (!inventory.complete) {
    const scannedPaths = new Set(inventory.files.map((file) => file.path));
    // A path cannot be both a file and a parent directory, even in a partial scan.
    for (const path of Object.keys(files)) {
      const segments = path.split("/");
      while (segments.length > 2) {
        segments.pop();
        const parent = segments.join("/");
        if (scannedPaths.has(parent)) {
          delete files[path];
          changed.push(path);
          break;
        }
        if (scannedPaths.has(path) && files[parent]) {
          delete files[parent];
          changed.push(parent);
        }
      }
    }
  }
  if (inventory.complete) {
    for (const path of Object.keys(previous)) {
      if (files[path] === undefined) changed.push(path);
    }
  }
  added.sort(
    (a, b) =>
      outputPreviewPriority(a.path) - outputPreviewPriority(b.path) ||
      a.path.localeCompare(b.path)
  );
  return { files, added, changed };
}

function automaticallySelectOutput(
  session: BuildSessionData,
  target: PanelTab | { kind: OutputTabType }
): Partial<BuildSessionData> {
  if (
    session.outputSelectionLocked ||
    session.isInterrupting ||
    session.wasInterrupted ||
    session.status === "failed"
  )
    return {};
  return {
    ...selectOutputTarget(session, target),
    outputPanelOpen: true,
    outputSelectionLocked: true,
  };
}

function selectOutputTarget(
  session: BuildSessionData,
  target: PanelTab | { kind: OutputTabType }
): Partial<BuildSessionData> {
  const entry: TabHistoryEntry =
    target.kind === "file"
      ? { type: "panel-tab", tabId: panelTabId(target) }
      : { type: "pinned", tab: target.kind };
  const currentEntry =
    session.tabHistory.entries[session.tabHistory.currentIndex];
  const isCurrentEntry =
    entry.type === "pinned"
      ? currentEntry?.type === "pinned" && currentEntry.tab === entry.tab
      : currentEntry?.type === "panel-tab" &&
        currentEntry.tabId === entry.tabId;
  const entries = [
    ...session.tabHistory.entries.slice(0, session.tabHistory.currentIndex + 1),
    entry,
  ];
  return {
    activeOutputTab:
      target.kind === "file" ? session.activeOutputTab : target.kind,
    activePanelTabId: target.kind === "file" ? panelTabId(target) : null,
    panelTabs:
      target.kind === "file" &&
      !session.panelTabs.some((tab) => panelTabId(tab) === panelTabId(target))
        ? [...session.panelTabs, target]
        : session.panelTabs,
    tabHistory: isCurrentEntry
      ? session.tabHistory
      : { entries, currentIndex: entries.length - 1 },
  };
}

function navigateOutputHistory(
  session: BuildSessionData,
  direction: -1 | 1
): Partial<BuildSessionData> | null {
  const { tabHistory } = session;
  const currentIndex = tabHistory.currentIndex + direction;
  const entry = tabHistory.entries[currentIndex];
  if (!entry) return null;

  let panelTabs = session.panelTabs;
  if (
    entry.type === "panel-tab" &&
    !panelTabs.some((tab) => panelTabId(tab) === entry.tabId) &&
    entry.tabId.startsWith("file:")
  ) {
    const path = entry.tabId.slice("file:".length);
    panelTabs = [
      ...panelTabs,
      { kind: "file", path, fileName: path.split("/").pop() || path },
    ];
  }
  return {
    tabHistory: { ...tabHistory, currentIndex },
    activeOutputTab:
      entry.type === "pinned" ? entry.tab : session.activeOutputTab,
    activePanelTabId: entry.type === "panel-tab" ? entry.tabId : null,
    panelTabs,
    outputSelectionLocked: true,
  };
}

interface BuildSessionStore {
  // Session management (mirrors chat)
  currentSessionId: string | null;
  sessions: Map<string, BuildSessionData>;
  sessionHistory: SessionHistoryItem[];

  // Pre-provisioning state (discriminated union - see PreProvisioningState type)
  preProvisioning: PreProvisioningState;

  // Controller state (replaces refs in useBuildSessionController for better race condition handling)
  controllerState: {
    /** Tracks which URL we've triggered provisioning for (prevents re-triggering) */
    lastTriggeredForUrl: string | null;
    /** Tracks which session ID has been loaded (prevents duplicate API calls) */
    loadedSessionId: string | null;
  };

  // Temporary output panel state when no session exists (resets when session is created/cleared)
  noSessionOutputPanelOpen: boolean;

  // Temporary active tab when no session exists (resets when session is created/cleared)
  noSessionActiveOutputTab: OutputTabType;

  // Actions - Session Management
  setCurrentSession: (sessionId: string | null) => void;
  createSession: (
    sessionId: string,
    initialData?: Partial<BuildSessionData>
  ) => void;
  updateSessionData: (
    sessionId: string,
    updates: Partial<BuildSessionData>
  ) => void;

  // Actions - Current Session Shortcuts
  appendMessageToCurrent: (message: BuildMessage) => void;
  toggleCurrentOutputPanel: () => void;

  // Actions - Session-specific operations (for streaming - immune to currentSessionId changes)
  appendMessageToSession: (sessionId: string, message: BuildMessage) => void;
  addArtifactToSession: (sessionId: string, artifact: Artifact) => void;

  // Actions - Stream Items (FIFO rendering)
  appendStreamItem: (sessionId: string, item: StreamItem) => void;
  updateStreamItem: (
    sessionId: string,
    itemId: string,
    updates: Partial<StreamItem>
  ) => void;
  updateLastStreamingText: (sessionId: string, content: string) => void;
  updateLastStreamingThinking: (sessionId: string, content: string) => void;
  updateToolCallStreamItem: (
    sessionId: string,
    toolCallId: string,
    updates: Partial<ToolCallState>
  ) => void;
  cancelLatestInFlightToolCallStreamItem: (sessionId: string) => void;
  upsertTodoListStreamItem: (
    sessionId: string,
    todoListId: string,
    todoList: TodoListState
  ) => void;
  clearStreamItems: (sessionId: string) => void;

  // Actions - Queued Messages
  enqueueMessage: (
    sessionId: string,
    text: string,
    attachments: BuildMessageAttachment[]
  ) => void;
  removeQueuedMessage: (sessionId: string, index: number) => void;

  // Actions - Abort Control
  setAbortController: (sessionId: string, controller: AbortController) => void;
  abortSession: (sessionId: string) => void;

  // Actions - Session Lifecycle
  loadSession: (
    sessionId: string,
    options?: { force?: boolean; preferPersisted?: boolean }
  ) => Promise<void>;

  // Actions - Session History
  refreshSessionHistory: () => Promise<void>;
  nameBuildSession: (sessionId: string) => Promise<void>;
  renameBuildSession: (sessionId: string, newName: string) => Promise<void>;
  deleteBuildSession: (sessionId: string) => Promise<void>;

  // Utilities
  cleanupOldSessions: (maxSessions?: number) => void;

  // Pre-provisioning Actions
  ensurePreProvisionedSession: () => Promise<string | null>;
  consumePreProvisionedSession: () => Promise<string | null>;

  // Controller State Actions (for useBuildSessionController - replaces refs)
  setControllerTriggered: (url: string | null) => void;
  setControllerLoaded: (sessionId: string | null) => void;

  // Webapp Refresh Actions
  triggerWebappRefresh: (sessionId: string) => void;
  // Files Refresh Actions
  triggerFilesRefresh: (sessionId: string) => void;

  // Output inventory and automatic navigation
  refreshOutputInventory: (
    sessionId: string,
    options?: { silent?: boolean; signal?: AbortSignal }
  ) => Promise<void>;
  maybeAutoOpenWebapp: (sessionId: string) => Promise<void>;

  // File Preview Actions
  openFilePreview: (sessionId: string, path: string, fileName: string) => void;
  /** Generic: remove the panel tab whose panelTabId === tabId; clears active if it was active. */
  closePanelTab: (sessionId: string, tabId: string) => void;
  setActiveOutputTab: (sessionId: string, tab: OutputTabType) => void;
  setActivePanelTabId: (sessionId: string, tabId: string | null) => void;
  /** Set active tab when no session exists (for pre-provisioned sandbox viewing) */
  setNoSessionActiveOutputTab: (tab: OutputTabType) => void;

  // Files Tab State Actions
  updateFilesTabState: (
    sessionId: string,
    updates: Partial<FilesTabState>
  ) => void;

  // Subagent Actions
  /** Swap the main column to show a subagent's transcript in place of the chat. */
  viewSubagent: (sessionId: string, subagentSessionId: string) => void;
  /** Return the main column to the normal chat (main-agent) view. */
  returnToMainAgent: (sessionId: string) => void;
  /** Upsert a subagent + one of its tool calls (creates the subagent if absent). */
  recordSubagentToolCall: (
    sessionId: string,
    subagentSessionId: string,
    parentToolCallId: string,
    toolCall: ToolCallState,
    subagentType: string | null,
    name: string
  ) => void;
  /**
   * Seed/backfill a subagent's identifying meta from a parent `task` event.
   * Creates the SubagentState if absent (status "running"); never clobbers
   * already-known identifying fields.
   */
  seedSubagentMeta: (
    sessionId: string,
    subagentSessionId: string,
    parentToolCallId: string,
    subagentType: string | null,
    name: string,
    prompt: string
  ) => void;
  /**
   * Mark a subagent as completed (or failed), optionally with its response.
   * When a response is provided, it is set on the LAST turn.
   */
  markSubagentComplete: (
    sessionId: string,
    subagentSessionId: string,
    status: SubagentStatus,
    response?: string | null
  ) => void;
  /** Append streamed response text to the LAST turn's response. */
  appendSubagentResponseChunk: (
    sessionId: string,
    subagentSessionId: string,
    text: string
  ) => void;
  /** Append streamed thinking text to the LAST turn's thinking stream. */
  appendSubagentThinkingChunk: (
    sessionId: string,
    subagentSessionId: string,
    text: string
  ) => void;

  // Tab Navigation History Actions
  navigateTabBack: (sessionId: string) => void;
  navigateTabForward: (sessionId: string) => void;
}

export function canReuseSession(
  session: BuildSessionData | undefined
): boolean {
  return (
    session?.isLoaded === true &&
    session.error === null &&
    session.pendingCompletedTurnId === null &&
    session.sandbox?.status !== "sleeping" &&
    session.sandbox?.status !== "terminated" &&
    session.sandbox?.status !== "failed"
  );
}

const completedTranscriptReads: Map<string, Promise<void>> = new Map();

function reconcileCompletedTranscript(
  sessionId: string,
  started: BuildSessionData
): void {
  const requestKey: string = `${sessionId}:${started.instanceId}:${started.loadGeneration}:${started.turnGeneration}:${started.pendingCompletedTurnId}`;
  if (completedTranscriptReads.has(requestKey)) return;
  const ownsCompletion: () => boolean = () => {
    const current: BuildSessionData | undefined = useBuildSessionStore
      .getState()
      .sessions.get(sessionId);
    return (
      current?.instanceId === started.instanceId &&
      current.turnGeneration === started.turnGeneration &&
      current.loadGeneration === started.loadGeneration &&
      current.pendingCompletedTurnId === started.pendingCompletedTurnId &&
      current.pendingCompletedTurnId !== null &&
      current.status !== "running" &&
      current.status !== "creating"
    );
  };
  const request: Promise<void> = (async () => {
    for (let attempt: number = 0; attempt < 30; attempt++) {
      await new Promise<void>((resolve) => setTimeout(resolve, 1000));
      if (!ownsCompletion()) return;
      try {
        const activeTurn: Awaited<ReturnType<typeof fetchActiveTurn>> =
          await fetchActiveTurn(sessionId);
        if (!ownsCompletion()) return;
        if (activeTurn?.turn_id === started.pendingCompletedTurnId) continue;
        if (activeTurn !== null) return;
        const messages: BuildMessage[] = await fetchMessages(sessionId);
        if (!ownsCompletion()) return;
        useBuildSessionStore.getState().updateSessionData(sessionId, {
          messages: consolidateMessagesIntoTurns(messages),
          streamItems: [],
          subagents: buildSubagentsFromMessages(messages),
          contextUsage: deriveContextUsage(messages),
          pendingCompletedTurnId: null,
        });
        return;
      } catch (error) {
        console.warn("Failed to reconcile completed transcript:", error);
      }
    }
  })().finally(() => completedTranscriptReads.delete(requestKey));
  completedTranscriptReads.set(requestKey, request);
}

// =============================================================================
// Initial State Factory
// =============================================================================

const createInitialSessionData = (
  sessionId: string,
  initialData?: Partial<BuildSessionData>
): BuildSessionData => ({
  id: sessionId,
  status: "idle",
  messages: [],
  artifacts: [],
  activeTurnId: null,
  pendingCompletedTurnId: null,
  activeTurnIndex: null,
  activeTurnLocalOwner: false,
  streamItems: [],
  queuedMessages: [],
  isInterrupting: false,
  wasInterrupted: false,
  turnGeneration: 0,
  loadGeneration: 0,
  error: null,
  webappUrl: null,
  sandbox: null,
  agentProvider: null,
  agentModel: null,
  skillsStale: false,
  skillsStaleRevision: 0,
  origin: "INTERACTIVE",
  abortController: new AbortController(),
  lastAccessed: new Date(),
  isLoaded: false,
  contextUsage: null,
  outputPanelOpen: false,
  webappNeedsRefresh: 0,
  webappNeedsRemount: 0,
  filesNeedsRefresh: 0,
  panelTabs: [],
  subagents: new Map(),
  viewedSubagentSessionId: null,
  activeOutputTab: "preview",
  activePanelTabId: null,
  filesTabState: {
    expandedPaths: [],
    scrollTop: 0,
  },
  tabHistory: {
    entries: [
      { type: "pinned", tab: initialData?.activeOutputTab ?? "preview" },
    ],
    currentIndex: 0,
  },
  outputInventory: null,
  outputInventoryStatus: "loading",
  outputBaselinePending: initialData?.outputInventory == null,
  filePreviewRefreshKeys: {},
  outputSelectionLocked: false,
  ...initialData,
  instanceId: genId("session-state"),
});

// =============================================================================
// Store
// =============================================================================

// The dev server is started fire-and-forget, so the backend reports RUNNING
// before the webapp serves. Bound polling and stalled requests by one deadline.
export async function waitForWebappReady(sessionId: string): Promise<boolean> {
  const controller: AbortController = new AbortController();
  const deadline: number = Date.now() + 30000;
  const timeout: ReturnType<typeof setTimeout> = setTimeout(
    () => controller.abort(),
    30000
  );
  try {
    while (!controller.signal.aborted) {
      let info: Awaited<ReturnType<typeof fetchWebappInfo>> | null = null;
      try {
        info = await fetchWebappInfo(sessionId, controller.signal);
      } catch {
        // Transient errors retry within the same deadline.
      }
      if (controller.signal.aborted) return false;
      if (info && (info.has_webapp === false || info.ready))
        return info.has_webapp === true && info.ready;
      await new Promise<void>((resolve) =>
        setTimeout(resolve, Math.min(1500, Math.max(0, deadline - Date.now())))
      );
    }
    return false;
  } finally {
    clearTimeout(timeout);
  }
}

export const useBuildSessionStore = create<BuildSessionStore>()((set, get) => ({
  currentSessionId: null,
  sessions: new Map<string, BuildSessionData>(),
  sessionHistory: [],

  // Pre-provisioning state
  preProvisioning: { status: "idle" },

  // Controller state (replaces refs in useBuildSessionController)
  controllerState: {
    lastTriggeredForUrl: null,
    loadedSessionId: null,
  },

  // Temporary output panel state when no session exists (resets when session is created/cleared)
  noSessionOutputPanelOpen: false,

  // The welcome page has no webapp to preview.
  noSessionActiveOutputTab: "files",

  // ===========================================================================
  // Session Management (mirrors chat's pattern)
  // ===========================================================================

  setCurrentSession: (sessionId: string | null) => {
    set((state) => {
      // If setting to null, clear current session and reset no-session panel state
      if (sessionId === null) {
        return {
          currentSessionId: null,
          noSessionOutputPanelOpen: false,
          noSessionActiveOutputTab: "files",
        };
      }

      // Keep the welcome sandbox available until the URL selects a session.
      const preProvisioning: PreProvisioningState =
        state.preProvisioning.status === "starting"
          ? { status: "idle" }
          : state.preProvisioning;

      // If session doesn't exist, create it and inherit output panel state
      if (!state.sessions.has(sessionId)) {
        const newSession = createInitialSessionData(sessionId, {
          outputPanelOpen: state.noSessionOutputPanelOpen,
          ...(state.noSessionOutputPanelOpen && {
            activeOutputTab: state.noSessionActiveOutputTab,
          }),
        });
        const newSessions = new Map(state.sessions);
        newSessions.set(sessionId, newSession);
        return {
          currentSessionId: sessionId,
          preProvisioning,
          sessions: newSessions,
          noSessionOutputPanelOpen: false,
        };
      }

      // Update last accessed for existing session and reset no-session panel state
      const session = state.sessions.get(sessionId)!;
      const updatedSession = { ...session, lastAccessed: new Date() };
      const newSessions = new Map(state.sessions);
      newSessions.set(sessionId, updatedSession);

      return {
        currentSessionId: sessionId,
        preProvisioning,
        sessions: newSessions,
        noSessionOutputPanelOpen: false,
      };
    });
  },

  // Initialize local session state (does NOT create backend session - use apiCreateSession for that)
  createSession: (
    sessionId: string,
    initialData?: Partial<BuildSessionData>
  ) => {
    set((state) => {
      // Carry the welcome panel's visible tab into the conversation.
      const outputPanelOpen =
        initialData?.outputPanelOpen ?? state.noSessionOutputPanelOpen;
      const newSession = createInitialSessionData(sessionId, {
        activeOutputTab: state.noSessionActiveOutputTab,
        filesTabState:
          state.sessions.get(sessionId)?.filesTabState ?? EMPTY_FILES_TAB_STATE,
        ...initialData,
        outputPanelOpen,
      });
      const newSessions = new Map(state.sessions);
      newSessions.set(sessionId, newSession);
      return { sessions: newSessions };
    });
  },

  updateSessionData: (
    sessionId: string,
    updates: Partial<BuildSessionData>
  ) => {
    set((state) => {
      const session = state.sessions.get(sessionId);
      if (!session) return state;

      const updatedSession: BuildSessionData = {
        ...session,
        ...updates,
        skillsStaleRevision:
          updates.skillsStale === undefined
            ? session.skillsStaleRevision
            : session.skillsStaleRevision + 1,
        lastAccessed: new Date(),
      };
      const newSessions = new Map(state.sessions);
      newSessions.set(sessionId, updatedSession);
      return { sessions: newSessions };
    });
  },

  // ===========================================================================
  // Current Session Shortcuts
  // ===========================================================================

  appendMessageToCurrent: (message: BuildMessage) => {
    const { currentSessionId } = get();
    if (!currentSessionId) return;

    set((state) => {
      const currentSession = state.sessions.get(currentSessionId);
      if (!currentSession) return state;

      const updatedSession: BuildSessionData = {
        ...currentSession,
        messages: [...currentSession.messages, message],
        lastAccessed: new Date(),
      };
      const newSessions = new Map(state.sessions);
      newSessions.set(currentSessionId, updatedSession);
      return { sessions: newSessions };
    });
  },

  toggleCurrentOutputPanel: () => {
    const {
      currentSessionId,
      sessions,
      updateSessionData,
      noSessionOutputPanelOpen,
    } = get();
    if (currentSessionId) {
      const session = sessions.get(currentSessionId);
      if (session) {
        const closing = session.outputPanelOpen;
        const update: Partial<BuildSessionData> = {
          outputPanelOpen: !session.outputPanelOpen,
        };
        if (closing) update.outputSelectionLocked = true;
        updateSessionData(currentSessionId, update);
      }
    } else {
      // No session - toggle temporary state
      set({ noSessionOutputPanelOpen: !noSessionOutputPanelOpen });
    }
  },

  // ===========================================================================
  // Session-specific operations (for streaming - immune to currentSessionId changes)
  // ===========================================================================

  appendMessageToSession: (sessionId: string, message: BuildMessage) => {
    set((state) => {
      const session = state.sessions.get(sessionId);
      if (!session) return state;

      const updatedSession: BuildSessionData = {
        ...session,
        messages: [...session.messages, message],
        lastAccessed: new Date(),
      };
      const newSessions = new Map(state.sessions);
      newSessions.set(sessionId, updatedSession);
      return { sessions: newSessions };
    });
  },

  addArtifactToSession: (sessionId: string, artifact: Artifact) => {
    set((state) => {
      const session = state.sessions.get(sessionId);
      if (!session) return state;

      const updatedSession: BuildSessionData = {
        ...session,
        artifacts: [...session.artifacts, artifact],
        lastAccessed: new Date(),
      };
      const newSessions = new Map(state.sessions);
      newSessions.set(sessionId, updatedSession);
      return { sessions: newSessions };
    });
  },

  // ===========================================================================
  // Stream Items (FIFO rendering)
  // ===========================================================================

  appendStreamItem: (sessionId: string, item: StreamItem) => {
    set((state) => {
      const session = state.sessions.get(sessionId);
      if (!session) return state;

      const updatedSession: BuildSessionData = {
        ...session,
        streamItems: [...session.streamItems, item],
        lastAccessed: new Date(),
      };
      const newSessions = new Map(state.sessions);
      newSessions.set(sessionId, updatedSession);
      return { sessions: newSessions };
    });
  },

  updateStreamItem: (
    sessionId: string,
    itemId: string,
    updates: Partial<StreamItem>
  ) => {
    set((state) => {
      const session = state.sessions.get(sessionId);
      if (!session) return state;

      const streamItems = session.streamItems.map((item) =>
        item.id === itemId ? { ...item, ...updates } : item
      ) as StreamItem[];
      const updatedSession: BuildSessionData = {
        ...session,
        streamItems,
        lastAccessed: new Date(),
      };
      const newSessions = new Map(state.sessions);
      newSessions.set(sessionId, updatedSession);
      return { sessions: newSessions };
    });
  },

  updateLastStreamingText: (sessionId: string, content: string) => {
    set((state) => {
      const session = state.sessions.get(sessionId);
      if (!session) return state;

      // Find the last text item that is streaming
      const items = [...session.streamItems];
      for (let i = items.length - 1; i >= 0; i--) {
        const item = items[i];
        if (item && item.type === "text" && item.isStreaming) {
          items[i] = { ...item, content };
          break;
        }
      }

      const updatedSession: BuildSessionData = {
        ...session,
        streamItems: items,
        lastAccessed: new Date(),
      };
      const newSessions = new Map(state.sessions);
      newSessions.set(sessionId, updatedSession);
      return { sessions: newSessions };
    });
  },

  updateLastStreamingThinking: (sessionId: string, content: string) => {
    set((state) => {
      const session = state.sessions.get(sessionId);
      if (!session) return state;

      // Find the last thinking item that is streaming
      const items = [...session.streamItems];
      for (let i = items.length - 1; i >= 0; i--) {
        const item = items[i];
        if (item && item.type === "thinking" && item.isStreaming) {
          items[i] = { ...item, content };
          break;
        }
      }

      const updatedSession: BuildSessionData = {
        ...session,
        streamItems: items,
        lastAccessed: new Date(),
      };
      const newSessions = new Map(state.sessions);
      newSessions.set(sessionId, updatedSession);
      return { sessions: newSessions };
    });
  },

  updateToolCallStreamItem: (
    sessionId: string,
    toolCallId: string,
    updates: Partial<ToolCallState>
  ) => {
    set((state) => {
      const session = state.sessions.get(sessionId);
      if (!session) return state;

      const streamItems = session.streamItems.map((item): StreamItem => {
        if (item.type === "tool_call" && item.toolCall.id === toolCallId) {
          return {
            ...item,
            toolCall: { ...item.toolCall, ...updates },
          };
        }
        return item;
      });

      const updatedSession: BuildSessionData = {
        ...session,
        streamItems,
        lastAccessed: new Date(),
      };
      const newSessions = new Map(state.sessions);
      newSessions.set(sessionId, updatedSession);
      return { sessions: newSessions };
    });
  },

  cancelLatestInFlightToolCallStreamItem: (sessionId: string) => {
    set((state) => {
      const session = state.sessions.get(sessionId);
      if (!session) return state;

      let latestInFlightIndex = -1;
      for (let i = session.streamItems.length - 1; i >= 0; i--) {
        const item = session.streamItems[i];
        if (
          item?.type === "tool_call" &&
          (item.toolCall.status === "pending" ||
            item.toolCall.status === "in_progress")
        ) {
          latestInFlightIndex = i;
          break;
        }
      }

      if (latestInFlightIndex === -1) return state;

      const streamItems = session.streamItems.map((item, index): StreamItem => {
        if (index === latestInFlightIndex && item.type === "tool_call") {
          return {
            ...item,
            toolCall: { ...item.toolCall, status: "cancelled" as const },
          };
        }
        return item;
      });

      const updatedSession: BuildSessionData = {
        ...session,
        streamItems,
        lastAccessed: new Date(),
      };
      const newSessions = new Map(state.sessions);
      newSessions.set(sessionId, updatedSession);
      return { sessions: newSessions };
    });
  },

  upsertTodoListStreamItem: (
    sessionId: string,
    todoListId: string,
    todoList: TodoListState
  ) => {
    set((state) => {
      const session = state.sessions.get(sessionId);
      if (!session) return state;

      // Check if a todo_list with this ID already exists
      const existingIndex = session.streamItems.findIndex(
        (item) => item.type === "todo_list" && item.todoList.id === todoListId
      );

      let streamItems: StreamItem[];
      if (existingIndex >= 0) {
        // Update existing todo_list
        streamItems = session.streamItems.map((item, index): StreamItem => {
          if (index === existingIndex && item.type === "todo_list") {
            return {
              ...item,
              todoList: { ...item.todoList, ...todoList },
            };
          }
          return item;
        });
      } else {
        // Create new todo_list item
        streamItems = [
          ...session.streamItems,
          {
            type: "todo_list" as const,
            id: todoListId,
            todoList,
          },
        ];
      }

      const updatedSession: BuildSessionData = {
        ...session,
        streamItems,
        lastAccessed: new Date(),
      };
      const newSessions = new Map(state.sessions);
      newSessions.set(sessionId, updatedSession);
      return { sessions: newSessions };
    });
  },

  clearStreamItems: (sessionId: string) => {
    set((state) => {
      const session = state.sessions.get(sessionId);
      if (!session) return state;

      const updatedSession: BuildSessionData = {
        ...session,
        streamItems: [],
        lastAccessed: new Date(),
      };
      const newSessions = new Map(state.sessions);
      newSessions.set(sessionId, updatedSession);
      return { sessions: newSessions };
    });
  },

  // ===========================================================================
  // Queued Messages
  // ===========================================================================

  enqueueMessage: (
    sessionId: string,
    text: string,
    attachments: BuildMessageAttachment[]
  ) => {
    set((state) => {
      const session = state.sessions.get(sessionId);
      if (!session || session.queuedMessages.length >= MAX_QUEUED_MESSAGES) {
        return state;
      }
      const updatedSession: BuildSessionData = {
        ...session,
        queuedMessages: [
          ...session.queuedMessages,
          { id: nextQueuedMessageId++, text, attachments },
        ],
        lastAccessed: new Date(),
      };
      const newSessions = new Map(state.sessions);
      newSessions.set(sessionId, updatedSession);
      return { sessions: newSessions };
    });
  },

  removeQueuedMessage: (sessionId: string, index: number) => {
    set((state) => {
      const session = state.sessions.get(sessionId);
      if (!session) return state;
      const updatedSession: BuildSessionData = {
        ...session,
        queuedMessages: session.queuedMessages.filter((_, i) => i !== index),
        lastAccessed: new Date(),
      };
      const newSessions = new Map(state.sessions);
      newSessions.set(sessionId, updatedSession);
      return { sessions: newSessions };
    });
  },

  // ===========================================================================
  // Abort Control (mirrors chat's per-session pattern)
  // ===========================================================================

  setAbortController: (sessionId: string, controller: AbortController) => {
    get().updateSessionData(sessionId, { abortController: controller });
  },

  abortSession: (sessionId: string) => {
    const session = get().sessions.get(sessionId);
    if (session?.abortController) {
      session.abortController.abort();
      get().updateSessionData(sessionId, {
        abortController: new AbortController(),
      });
    }
  },

  // ===========================================================================
  // Session Lifecycle
  // ===========================================================================

  loadSession: async (
    sessionId: string,
    options?: { force?: boolean; preferPersisted?: boolean }
  ) => {
    const { setCurrentSession, updateSessionData, sessions } = get();

    // Check if already loaded in cache
    const existingSession = sessions.get(sessionId);
    if (canReuseSession(existingSession) && options?.force !== true) {
      setCurrentSession(sessionId);
      return;
    }

    // Set as current and mark as loading
    setCurrentSession(sessionId);
    const loadingSession: BuildSessionData | undefined =
      get().sessions.get(sessionId);
    if (!loadingSession) return;
    const loadGeneration: number = loadingSession.loadGeneration + 1;
    updateSessionData(sessionId, { loadGeneration });
    const isCurrentRuntimeLoad: () => boolean = () => {
      const current: BuildSessionData | undefined =
        get().sessions.get(sessionId);
      return (
        current?.instanceId === loadingSession.instanceId &&
        current.loadGeneration === loadGeneration
      );
    };
    const isCurrentLoad: () => boolean = () => {
      const current: BuildSessionData | undefined =
        get().sessions.get(sessionId);
      return (
        current?.instanceId === loadingSession.instanceId &&
        current.turnGeneration === loadingSession.turnGeneration &&
        current.loadGeneration === loadGeneration
      );
    };
    const skillsStaleRevision: number = loadingSession.skillsStaleRevision;
    const canApplySkillsStale: () => boolean = () =>
      get().sessions.get(sessionId)?.skillsStaleRevision ===
      skillsStaleRevision;

    try {
      // Capture runtime failures while history loads independently.
      const runtimeRequest: Promise<
        [PromiseSettledResult<Awaited<ReturnType<typeof fetchSession>>>]
      > = Promise.allSettled([fetchSession(sessionId)]);
      let activeTurn: Awaited<ReturnType<typeof fetchActiveTurn>> = null;
      let activeTurnLookupSucceeded: boolean = false;
      try {
        activeTurn = await fetchActiveTurn(sessionId);
        activeTurnLookupSucceeded = true;
      } catch (err) {
        console.warn("Failed to fetch active turn:", err);
      }
      if (!isCurrentLoad()) return;
      // Server completion follows the final transcript commit. Observe it before reading messages.
      const messages: BuildMessage[] = await fetchMessages(sessionId);
      if (!isCurrentLoad()) return;

      // Preserve optimistic messages if actively streaming (pre-provisioned flow).
      const currentSession: BuildSessionData | undefined =
        get().sessions.get(sessionId);
      const currentSessionIsLive: boolean =
        currentSession?.status === "running" ||
        currentSession?.status === "creating";
      const isStreaming: boolean =
        currentSessionIsLive && (currentSession?.messages.length ?? 0) > 0;
      // settle() (the only preferPersisted caller) runs on a live "running"
      // session, so the isStreaming status branch below already keeps status live,
      // leaving settle the sole owner of the flip to "active" (else auto-send races).
      const pendingCompletedTurnId: string | null | undefined =
        currentSession?.pendingCompletedTurnId;
      // A completion learned during this load requires a later transcript read.
      const keepCompletedTranscript: boolean =
        !currentSessionIsLive &&
        options?.preferPersisted !== true &&
        pendingCompletedTurnId != null &&
        (loadingSession.pendingCompletedTurnId !== pendingCompletedTurnId ||
          !activeTurnLookupSucceeded ||
          activeTurn?.turn_id === pendingCompletedTurnId);
      const useDbMessages: boolean =
        (!isStreaming && !keepCompletedTranscript) ||
        options?.preferPersisted === true;

      const resolvedActiveTurnId: string | null = keepCompletedTranscript
        ? null
        : (activeTurn?.turn_id ??
          (useDbMessages ? null : currentSession!.activeTurnId));
      const resolvedActiveTurnIndex: number | null = keepCompletedTranscript
        ? null
        : (activeTurn?.turn_index ??
          (useDbMessages ? null : currentSession!.activeTurnIndex));

      const status: SessionStatus =
        isStreaming || keepCompletedTranscript
          ? currentSession!.status
          : activeTurn
            ? "running"
            : currentSession!.status;
      const persistedMessages: BuildMessage[] = useDbMessages
        ? consolidateMessagesIntoTurns(messages)
        : currentSession!.messages;
      const restoredActiveTurn: ReturnType<typeof splitActiveTurnTranscript> =
        useDbMessages
          ? splitActiveTurnTranscript(
              persistedMessages,
              resolvedActiveTurnIndex
            )
          : {
              messages: persistedMessages,
              streamItems: currentSession!.streamItems,
            };
      const resolvedMessages: BuildMessage[] = restoredActiveTurn.messages;
      const streamItems: StreamItem[] = restoredActiveTurn.streamItems;
      // Reconstruct subagents from the raw (un-consolidated) messages — they
      // carry the per-packet _meta needed for classification. Preserve the
      // live map if actively streaming.
      const subagents: Map<string, SubagentState> = useDbMessages
        ? buildSubagentsFromMessages(messages)
        : currentSession!.subagents;
      updateSessionData(sessionId, {
        status,
        messages: resolvedMessages,
        streamItems,
        subagents,
        activeTurnId: resolvedActiveTurnId,
        pendingCompletedTurnId: useDbMessages
          ? null
          : currentSession!.pendingCompletedTurnId,
        activeTurnIndex: resolvedActiveTurnIndex,
        activeTurnLocalOwner: useDbMessages
          ? false
          : currentSession!.activeTurnLocalOwner,
        contextUsage: useDbMessages
          ? deriveContextUsage(messages)
          : currentSession!.contextUsage,
        error: null,
        isLoaded: true,
      });

      if (keepCompletedTranscript) {
        const completedSession: BuildSessionData | undefined =
          get().sessions.get(sessionId);
        if (completedSession)
          reconcileCompletedTranscript(sessionId, completedSession);
      }

      const [runtimeResult] = await runtimeRequest;
      if (!isCurrentLoad()) return;
      if (runtimeResult.status === "rejected") throw runtimeResult.reason;
      let sessionData = runtimeResult.value;
      const runtimeSession: BuildSessionData | undefined =
        get().sessions.get(sessionId);
      if (!runtimeSession) return;
      const needsRestore: boolean =
        sessionData.sandbox?.status === "sleeping" ||
        sessionData.sandbox?.status === "terminated" ||
        sessionData.sandbox?.status === "failed" ||
        (sessionData.sandbox?.status === "running" &&
          !sessionData.session_loaded_in_sandbox);
      updateSessionData(sessionId, {
        status:
          isStreaming ||
          keepCompletedTranscript ||
          runtimeSession.status !== status ||
          runtimeSession.activeTurnId !== resolvedActiveTurnId ||
          runtimeSession.pendingCompletedTurnId !==
            (useDbMessages ? null : currentSession!.pendingCompletedTurnId)
            ? runtimeSession.status
            : activeTurn
              ? "running"
              : needsRestore
                ? "creating"
                : mapApiSessionStatus(sessionData.status),
        sandbox:
          needsRestore && sessionData.sandbox
            ? { ...sessionData.sandbox, status: "restoring" }
            : sessionData.sandbox,
        agentProvider: sessionData.agent_provider,
        agentModel: sessionData.agent_model,
        ...(canApplySkillsStale() && { skillsStale: sessionData.skills_stale }),
        origin: sessionData.origin,
      });
      if (!needsRestore) {
        const artifacts: Artifact[] = await fetchArtifacts(sessionId);
        if (!isCurrentLoad()) return;
        const hasWebapp: boolean = artifacts.some(
          (artifact) =>
            artifact.type === "nextjs_app" || artifact.type === "web_app"
        );
        updateSessionData(sessionId, {
          artifacts,
          webappUrl:
            hasWebapp && sessionData.nextjs_port
              ? `http://localhost:${sessionData.nextjs_port}`
              : null,
        });
        if (
          get().sessions.get(sessionId)?.outputInventory === null ||
          runtimeSession.status !== "running"
        )
          void get().refreshOutputInventory(sessionId, { silent: true });
      }

      if (needsRestore) {
        const skillsStaleRevisionBeforeRestore: number | undefined =
          get().sessions.get(sessionId)?.skillsStaleRevision;
        try {
          sessionData = await restoreSession(sessionId);
          if (!isCurrentRuntimeLoad()) return;
        } catch (restoreErr) {
          if (!isCurrentRuntimeLoad()) return;
          // Only a genuine restore failure marks the sandbox failed.
          console.error("Sandbox restore failed:", restoreErr);
          updateSessionData(sessionId, {
            ...(isCurrentLoad() && { status: "idle" }),
            sandbox: sessionData.sandbox
              ? { ...sessionData.sandbox, status: "failed" }
              : null,
          });
          return;
        }

        // Hold the chip on "restoring" (and poll webapp readiness) until the
        // webapp actually serves, then flip to the real status below.
        updateSessionData(sessionId, {
          ...(isCurrentLoad() && {
            status: mapApiSessionStatus(sessionData.status),
          }),
          sandbox: sessionData.sandbox
            ? { ...sessionData.sandbox, status: "restoring" }
            : sessionData.sandbox,
          ...(get().sessions.get(sessionId)?.skillsStaleRevision ===
            skillsStaleRevisionBeforeRestore && {
            skillsStale: sessionData.skills_stale,
          }),
          webappNeedsRefresh:
            (get().sessions.get(sessionId)?.webappNeedsRefresh || 0) + 1,
        });

        // Remount the iframe only once the restored pod serves — the old
        // page's HMR socket died with the old pod. If readiness times out the
        // remount still runs: worst case the iframe lands on the offline page,
        // which reloads itself until the server responds.
        await waitForWebappReady(sessionId);
        if (
          !isCurrentRuntimeLoad() ||
          get().sessions.get(sessionId)?.sandbox?.id !== sessionData.sandbox?.id
        )
          return;
        updateSessionData(sessionId, {
          sandbox: sessionData.sandbox,
          filesNeedsRefresh:
            (get().sessions.get(sessionId)?.filesNeedsRefresh ?? 0) + 1,
          webappNeedsRemount:
            (get().sessions.get(sessionId)?.webappNeedsRemount || 0) + 1,
        });

        // An artifact-fetch failure must NOT flip the sandbox to "failed".
        try {
          if (!isCurrentLoad()) return;
          const restoredArtifacts: Artifact[] = await fetchArtifacts(sessionId);
          if (!isCurrentLoad()) return;
          updateSessionData(sessionId, { artifacts: restoredArtifacts });
          void get().refreshOutputInventory(sessionId, { silent: true });
        } catch (artifactsErr) {
          console.warn(
            "Failed to fetch artifacts after restore:",
            artifactsErr
          );
        }
      }
    } catch (err) {
      if (!isCurrentLoad()) return;
      console.error("Failed to load session:", err);
      updateSessionData(sessionId, {
        error: (err as Error).message,
      });
    } finally {
      const completedSession: BuildSessionData | undefined =
        get().sessions.get(sessionId);
      if (
        isCurrentRuntimeLoad() &&
        completedSession?.pendingCompletedTurnId != null &&
        completedSession.status !== "running" &&
        completedSession.status !== "creating"
      ) {
        reconcileCompletedTranscript(sessionId, completedSession);
      }
    }
  },

  // ===========================================================================
  // Session History
  // ===========================================================================

  refreshSessionHistory: async () => {
    try {
      const history = await fetchSessionHistory();
      set({ sessionHistory: history });
    } catch (err) {
      console.error("Failed to fetch session history:", err);
    }
  },

  nameBuildSession: async (sessionId: string) => {
    try {
      // Generate name using LLM based on first user message
      const generatedName = await generateSessionName(sessionId);

      // Optimistically update the session title in sessionHistory immediately
      // This triggers the typewriter animation in the sidebar
      set((state) => ({
        sessionHistory: state.sessionHistory.map((item) =>
          item.id === sessionId ? { ...item, title: generatedName } : item
        ),
      }));

      // Persist the name to backend (fire and forget - error handling below)
      await updateSessionName(sessionId, generatedName);
    } catch (err) {
      console.error("Failed to auto-name session:", err);
      // On error, refresh to get the actual state from backend
      await get().refreshSessionHistory();
    }
  },

  renameBuildSession: async (sessionId: string, newName: string) => {
    try {
      await updateSessionName(sessionId, newName);
      set((state) => ({
        sessionHistory: state.sessionHistory.map((item) =>
          item.id === sessionId ? { ...item, title: newName } : item
        ),
      }));
    } catch (err) {
      console.error("Failed to rename session:", err);
      await get().refreshSessionHistory();
      throw err;
    }
  },

  deleteBuildSession: async (sessionId: string) => {
    const { currentSessionId, abortSession, refreshSessionHistory } = get();

    try {
      abortSession(sessionId);
      await apiDeleteSession(sessionId);

      // Remove session from local state
      set((state) => {
        const newSessions = new Map(state.sessions);
        newSessions.delete(sessionId);
        return {
          sessions: newSessions,
          sessionHistory: state.sessionHistory.filter(
            (historyItem) => historyItem.id !== sessionId
          ),
          currentSessionId:
            currentSessionId === sessionId ? null : state.currentSessionId,
        };
      });

      void refreshSessionHistory();
    } catch (err) {
      console.error("Failed to delete session:", err);
      throw err;
    }
  },

  // ===========================================================================
  // Utilities (mirrors chat's cleanup pattern)
  // ===========================================================================

  cleanupOldSessions: (maxSessions: number = 10) => {
    set((state) => {
      const sortedSessions = Array.from(state.sessions.entries()).sort(
        ([, a], [, b]) => b.lastAccessed.getTime() - a.lastAccessed.getTime()
      );

      if (sortedSessions.length <= maxSessions) {
        return state;
      }

      const sessionsToKeep = sortedSessions.slice(0, maxSessions);
      const sessionsToRemove = sortedSessions.slice(maxSessions);

      // Abort controllers for sessions being removed
      sessionsToRemove.forEach(([, session]) => {
        if (session.abortController) {
          session.abortController.abort();
        }
      });

      return {
        sessions: new Map(sessionsToKeep),
      };
    });
  },

  // ===========================================================================
  // Pre-provisioning Actions
  // ===========================================================================

  ensurePreProvisionedSession: async () => {
    const { preProvisioning } = get();

    if (preProvisioning.status === "ready") {
      return preProvisioning.sessionId;
    }

    if (preProvisioning.status === "starting") return null;

    if (preProvisioning.status === "provisioning") {
      return provisioningPromise;
    }

    let currentRetryCount = 0;
    if (preProvisioning.status === "failed") {
      currentRetryCount = preProvisioning.retryCount;
      if (Date.now() < preProvisioning.retryAt) {
        return null;
      }
      set({ preProvisioning: { status: "idle" } });
    }

    const promise = (async (): Promise<string | null> => {
      try {
        // Default model at provision time; per-message override sets it later.
        const sessionData = await apiCreateSession({});

        provisioningPromise = null;
        set((state) => ({
          sessions: new Map(state.sessions).set(
            sessionData.id,
            state.sessions.get(sessionData.id) ??
              createInitialSessionData(sessionData.id)
          ),
          preProvisioning: {
            status: "ready",
            sessionId: sessionData.id,
          },
        }));
        void get().refreshOutputInventory(sessionData.id, { silent: true });
        return sessionData.id;
      } catch (err) {
        console.error("[PreProvision] Failed to pre-provision session:", err);
        const errorMessage =
          err instanceof Error ? err.message : "Unknown error";

        const newRetryCount = currentRetryCount + 1;
        const backoffMs = Math.min(
          1000 * Math.pow(2, newRetryCount - 1),
          30000
        );

        provisioningPromise = null;
        set({
          preProvisioning: {
            status: "failed",
            error: errorMessage,
            retryCount: newRetryCount,
            retryAt: Date.now() + backoffMs,
          },
        });
        return null;
      }
    })();

    provisioningPromise = promise;
    set({
      preProvisioning: { status: "provisioning" },
    });
    return promise;
  },

  consumePreProvisionedSession: async () => {
    const { preProvisioning } = get();

    // Wait for provisioning to complete if in progress
    if (preProvisioning.status === "provisioning") {
      await provisioningPromise;
    }

    // Re-check state after awaiting (may have changed)
    const { preProvisioning: currentState, sessionHistory } = get();

    if (currentState.status === "ready") {
      const { sessionId } = currentState;

      // Optimistically add to session history so it appears in sidebar immediately
      // (Backend excludes empty sessions, but we're about to send a message)
      const alreadyInHistory = sessionHistory.some(
        (item) => item.id === sessionId
      );
      set({
        preProvisioning: { status: "starting", sessionId },
        sessionHistory: alreadyInHistory
          ? sessionHistory
          : [
              {
                id: sessionId,
                title: "Fresh Craft",
                createdAt: new Date(),
              },
              ...sessionHistory,
            ],
      });
      return sessionId;
    }

    // No session available
    return null;
  },

  // ===========================================================================
  // Controller State Actions (replaces refs in useBuildSessionController)
  // ===========================================================================

  setControllerTriggered: (url: string | null) => {
    set((state) => ({
      controllerState: {
        ...state.controllerState,
        lastTriggeredForUrl: url,
      },
    }));
  },

  setControllerLoaded: (sessionId: string | null) => {
    set((state) => ({
      controllerState: {
        ...state.controllerState,
        loadedSessionId: sessionId,
      },
    }));
  },

  // ===========================================================================
  // Webapp Refresh Actions
  // ===========================================================================

  triggerWebappRefresh: (sessionId: string) => {
    const session = get().sessions.get(sessionId);
    if (session) {
      // Refresh data and apply the same dismissal policy as file outputs.
      get().updateSessionData(sessionId, {
        webappNeedsRefresh: (session.webappNeedsRefresh || 0) + 1,
      });
      void get().maybeAutoOpenWebapp(sessionId);
    }
  },

  triggerFilesRefresh: (sessionId: string) => {
    const session = get().sessions.get(sessionId);
    if (session) {
      // Increment refresh counter to trigger files list refresh
      // Using a counter ensures each filesystem change triggers a new refresh
      get().updateSessionData(sessionId, {
        filesNeedsRefresh: (session.filesNeedsRefresh || 0) + 1,
      });
    }
  },

  // ===========================================================================
  // Auto-open Actions
  // ===========================================================================

  refreshOutputInventory: async (
    sessionId,
    { silent = false, signal } = {}
  ) => {
    const started: BuildSessionData | undefined = get().sessions.get(sessionId);
    if (!started || signal?.aborted) return;
    const isCurrent = (): boolean => {
      const current = get().sessions.get(sessionId);
      return (
        !signal?.aborted &&
        current !== undefined &&
        current.turnGeneration === started.turnGeneration &&
        (!silent || current.activeTurnId === started.activeTurnId) &&
        (!current.activeTurnId ||
          !started.activeTurnId ||
          current.activeTurnId === started.activeTurnId)
      );
    };
    const readInventory = async (): Promise<void> => {
      for (let attempt = 0; attempt < 3; attempt++) {
        if (!isCurrent()) return;
        const controller = new AbortController();
        const abort = (): void => controller.abort();
        signal?.addEventListener("abort", abort, { once: true });
        // Allow the backend's 30-second RPC deadline plus HTTP overhead.
        const timeout = setTimeout(abort, 35000);
        try {
          const inventory = await fetchOutputInventory(
            sessionId,
            controller.signal
          );
          if (!isCurrent()) return;
          const session = get().sessions.get(sessionId);
          if (!session) return;
          const previous = session.outputInventory;
          const { files, added, changed } = compareOutputInventory(
            previous ?? {},
            inventory
          );
          const updates: Partial<BuildSessionData> = {
            outputInventory: files,
            outputInventoryStatus: inventory.complete ? "complete" : "partial",
            outputBaselinePending:
              (session.outputBaselinePending || previous === null) &&
              !inventory.complete,
            filesNeedsRefresh:
              session.filesNeedsRefresh +
              (previous !== null && (added.length > 0 || changed.length > 0)
                ? 1
                : 0),
          };
          // Unknown baselines still refresh previews, but cannot attribute files to this task.
          if (previous === null || session.outputBaselinePending || silent) {
            get().updateSessionData(sessionId, updates);
            return;
          }
          const newTabs: PanelTab[] = added
            .filter((file) => outputPreviewPriority(file.path) < 4)
            .map(
              (file): PanelTab => ({
                kind: "file",
                path: file.path,
                fileName: file.path.split("/").pop() || file.path,
              })
            );
          const existingIds: Set<string> = new Set(
            session.panelTabs.map(panelTabId)
          );
          const panelTabs: PanelTab[] = [
            ...session.panelTabs,
            ...newTabs.filter((tab) => !existingIds.has(panelTabId(tab))),
          ];
          updates.panelTabs = panelTabs;
          const target: PanelTab | undefined = newTabs[0];
          if (target)
            Object.assign(
              updates,
              automaticallySelectOutput({ ...session, panelTabs }, target)
            );
          get().updateSessionData(sessionId, updates);
          return;
        } catch (error) {
          if (!isCurrent()) return;
          if (attempt === 2) {
            get().updateSessionData(sessionId, {
              outputInventoryStatus: "error",
            });
            console.warn(
              "[Streaming] Failed to refresh output inventory:",
              error
            );
          }
        } finally {
          clearTimeout(timeout);
          signal?.removeEventListener("abort", abort);
        }
        if (attempt < 2) {
          await new Promise<void>((resolve) =>
            setTimeout(resolve, 1000 * (attempt + 1))
          );
        }
      }
    };

    // Focus and panel reads must not consume files before pending turn discovery.
    const previousRequest = outputInventoryRequests.get(sessionId);
    const request = previousRequest
      ? previousRequest.then(readInventory)
      : readInventory();
    outputInventoryRequests.set(sessionId, request);
    try {
      await request;
    } finally {
      if (outputInventoryRequests.get(sessionId) === request)
        outputInventoryRequests.delete(sessionId);
    }
  },

  maybeAutoOpenWebapp: async (sessionId) => {
    const started = get().sessions.get(sessionId);
    if (!started || started.outputSelectionLocked) return;

    let readiness = webappReadinessChecks.get(sessionId);
    if (!readiness) {
      readiness = waitForWebappReady(sessionId).finally(() => {
        webappReadinessChecks.delete(sessionId);
      });
      webappReadinessChecks.set(sessionId, readiness);
    }
    if (!(await readiness)) return;
    const session = get().sessions.get(sessionId);
    if (
      !session ||
      session.turnGeneration !== started.turnGeneration ||
      (session.activeTurnId &&
        started.activeTurnId &&
        session.activeTurnId !== started.activeTurnId)
    )
      return;
    get().updateSessionData(
      sessionId,
      automaticallySelectOutput(session, { kind: "preview" })
    );
  },

  openFilePreview: (sessionId, path, fileName) => {
    const session = get().sessions.get(sessionId);
    if (!session) return;
    get().updateSessionData(sessionId, {
      ...selectOutputTarget(session, { kind: "file", path, fileName }),
      outputPanelOpen: true,
      outputSelectionLocked: true,
    });
  },

  closePanelTab: (sessionId, tabId) => {
    const session = get().sessions.get(sessionId);
    if (!session) return;
    const wasActive = session.activePanelTabId === tabId;
    get().updateSessionData(sessionId, {
      panelTabs: session.panelTabs.filter((tab) => panelTabId(tab) !== tabId),
      activePanelTabId: wasActive ? null : session.activePanelTabId,
      activeOutputTab: wasActive ? "files" : session.activeOutputTab,
      outputSelectionLocked: true,
    });
  },

  setActiveOutputTab: (sessionId, tab) => {
    const session = get().sessions.get(sessionId);
    if (!session) return;
    get().updateSessionData(sessionId, {
      ...selectOutputTarget(session, { kind: tab }),
      outputSelectionLocked: true,
    });
  },

  setActivePanelTabId: (sessionId, tabId) => {
    const session = get().sessions.get(sessionId);
    if (!session) return;
    const tab = session.panelTabs.find(
      (candidate) => panelTabId(candidate) === tabId
    );
    if (tabId !== null && !tab) return;
    get().updateSessionData(sessionId, {
      ...(tab ? selectOutputTarget(session, tab) : { activePanelTabId: null }),
      outputSelectionLocked: true,
    });
  },

  setNoSessionActiveOutputTab: (tab: OutputTabType) => {
    set({ noSessionActiveOutputTab: tab });
  },

  // ===========================================================================
  // Files Tab State Actions
  // ===========================================================================

  updateFilesTabState: (sessionId: string, updates: Partial<FilesTabState>) => {
    set((state) => {
      const session = state.sessions.get(sessionId);
      if (!session) return state;

      const updatedSession: BuildSessionData = {
        ...session,
        filesTabState: { ...session.filesTabState, ...updates },
        lastAccessed: new Date(),
      };
      const newSessions = new Map(state.sessions);
      newSessions.set(sessionId, updatedSession);
      return { sessions: newSessions };
    });
  },

  // ===========================================================================
  // Subagent Actions
  // ===========================================================================

  viewSubagent: (sessionId: string, subagentSessionId: string) => {
    set((state) => {
      const session = state.sessions.get(sessionId);
      if (!session) return state;
      // Guard against viewing a subagent that doesn't exist in this session.
      if (!session.subagents.has(subagentSessionId)) return state;

      const updatedSession: BuildSessionData = {
        ...session,
        viewedSubagentSessionId: subagentSessionId,
        lastAccessed: new Date(),
      };
      const newSessions = new Map(state.sessions);
      newSessions.set(sessionId, updatedSession);
      return { sessions: newSessions };
    });
  },

  returnToMainAgent: (sessionId: string) => {
    set((state) => {
      const session = state.sessions.get(sessionId);
      if (!session) return state;
      if (session.viewedSubagentSessionId === null) return state;

      const updatedSession: BuildSessionData = {
        ...session,
        viewedSubagentSessionId: null,
        lastAccessed: new Date(),
      };
      const newSessions = new Map(state.sessions);
      newSessions.set(sessionId, updatedSession);
      return { sessions: newSessions };
    });
  },

  recordSubagentToolCall: (
    sessionId: string,
    subagentSessionId: string,
    parentToolCallId: string,
    toolCall: ToolCallState,
    subagentType: string | null,
    name: string
  ) => {
    set((state) => {
      const session = state.sessions.get(sessionId);
      if (!session) return state;

      const existing = session.subagents.get(subagentSessionId);
      const base: SubagentState = existing ?? {
        sessionId: subagentSessionId,
        parentToolCallId,
        subagentType,
        name,
        status: "running",
        turns: [emptyTurn()],
        startedAt: Date.now(),
        completedAt: null,
      };

      // Upsert the tool call into the LAST turn (by id).
      const turns = base.turns.length > 0 ? [...base.turns] : [emptyTurn()];
      const last = turns[turns.length - 1] ?? emptyTurn();
      const tcIndex = last.toolCalls.findIndex((tc) => tc.id === toolCall.id);
      const toolCalls =
        tcIndex >= 0
          ? last.toolCalls.map((tc, i) => (i === tcIndex ? toolCall : tc))
          : [...last.toolCalls, toolCall];
      turns[turns.length - 1] = {
        ...last,
        toolCalls,
        streamItems: upsertToolStreamItem(
          settleStreamItems(last.streamItems),
          toolCall
        ),
      };

      const updatedSubagent: SubagentState = {
        ...base,
        // Backfill identifying fields if they arrive later.
        parentToolCallId: base.parentToolCallId || parentToolCallId,
        subagentType: base.subagentType ?? subagentType,
        name: base.name || name,
        turns,
      };

      const subagents = new Map(session.subagents);
      subagents.set(subagentSessionId, updatedSubagent);

      const updatedSession: BuildSessionData = {
        ...session,
        subagents,
        lastAccessed: new Date(),
      };
      const newSessions = new Map(state.sessions);
      newSessions.set(sessionId, updatedSession);
      return { sessions: newSessions };
    });
  },

  seedSubagentMeta: (
    sessionId: string,
    subagentSessionId: string,
    parentToolCallId: string,
    subagentType: string | null,
    name: string,
    prompt: string
  ) => {
    set((state) => {
      const session = state.sessions.get(sessionId);
      if (!session) return state;

      const existing = session.subagents.get(subagentSessionId);
      const base: SubagentState = existing ?? {
        sessionId: subagentSessionId,
        parentToolCallId,
        subagentType,
        name,
        status: "running",
        turns: [emptyTurn(prompt)],
        startedAt: Date.now(),
        completedAt: null,
      };

      // Ensure turns[0] exists; backfill its prompt without clobbering real
      // known prompts. The early task start can only say "Spawning subagent";
      // replace that placeholder when later task progress carries the prompt.
      const turns = base.turns.length > 0 ? [...base.turns] : [emptyTurn()];
      const firstTurn = turns[0] ?? emptyTurn();
      turns[0] = {
        ...firstTurn,
        prompt:
          !firstTurn.prompt || isPlaceholderSubagentLabel(firstTurn.prompt)
            ? prompt
            : firstTurn.prompt,
      };

      const updatedSubagent: SubagentState = {
        ...base,
        // Seed/backfill identifying fields; never clobber real known values.
        parentToolCallId: base.parentToolCallId || parentToolCallId,
        subagentType: base.subagentType ?? subagentType,
        name:
          !base.name || isPlaceholderSubagentLabel(base.name)
            ? name
            : base.name,
        turns,
      };

      const subagents = new Map(session.subagents);
      subagents.set(subagentSessionId, updatedSubagent);

      const updatedSession: BuildSessionData = {
        ...session,
        subagents,
        lastAccessed: new Date(),
      };
      const newSessions = new Map(state.sessions);
      newSessions.set(sessionId, updatedSession);
      return { sessions: newSessions };
    });
  },

  markSubagentComplete: (
    sessionId: string,
    subagentSessionId: string,
    status: SubagentStatus,
    response?: string | null
  ) => {
    set((state) => {
      const session = state.sessions.get(sessionId);
      if (!session) return state;

      const existing = session.subagents.get(subagentSessionId);
      if (!existing) return state;

      // When a response is provided, set it on the LAST turn.
      let turns = existing.turns;
      if (response !== undefined) {
        turns = existing.turns.length > 0 ? [...existing.turns] : [emptyTurn()];
        const last = turns[turns.length - 1] ?? emptyTurn();
        turns[turns.length - 1] = {
          ...last,
          response,
          streamItems: replaceOrAppendSettledTextItem(
            last.streamItems,
            response
          ),
        };
      } else {
        turns = existing.turns.map((turn) => ({
          ...turn,
          streamItems: settleStreamItems(turn.streamItems),
        }));
      }

      const subagents = new Map(session.subagents);
      subagents.set(subagentSessionId, {
        ...existing,
        status,
        completedAt: Date.now(),
        turns,
      });

      const updatedSession: BuildSessionData = {
        ...session,
        subagents,
        lastAccessed: new Date(),
      };
      const newSessions = new Map(state.sessions);
      newSessions.set(sessionId, updatedSession);
      return { sessions: newSessions };
    });
  },

  appendSubagentResponseChunk: (
    sessionId: string,
    subagentSessionId: string,
    text: string
  ) => {
    set((state) => {
      const session = state.sessions.get(sessionId);
      if (!session) return state;

      const existing = session.subagents.get(subagentSessionId);
      const base: SubagentState = existing ?? {
        sessionId: subagentSessionId,
        parentToolCallId: "",
        subagentType: null,
        name: "",
        status: "running",
        turns: [emptyTurn()],
        startedAt: Date.now(),
        completedAt: null,
      };

      const turns = base.turns.length > 0 ? [...base.turns] : [emptyTurn()];
      const last = turns[turns.length - 1] ?? emptyTurn();
      turns[turns.length - 1] = {
        ...last,
        response: (last.response ?? "") + text,
        streamItems: appendStreamingSubagentChunk(
          last.streamItems,
          "text",
          text
        ),
      };

      const subagents = new Map(session.subagents);
      subagents.set(subagentSessionId, { ...base, turns });

      const updatedSession: BuildSessionData = {
        ...session,
        subagents,
        lastAccessed: new Date(),
      };
      const newSessions = new Map(state.sessions);
      newSessions.set(sessionId, updatedSession);
      return { sessions: newSessions };
    });
  },

  appendSubagentThinkingChunk: (
    sessionId: string,
    subagentSessionId: string,
    text: string
  ) => {
    set((state) => {
      const session = state.sessions.get(sessionId);
      if (!session) return state;

      const existing = session.subagents.get(subagentSessionId);
      const base: SubagentState = existing ?? {
        sessionId: subagentSessionId,
        parentToolCallId: "",
        subagentType: null,
        name: "",
        status: "running",
        turns: [emptyTurn()],
        startedAt: Date.now(),
        completedAt: null,
      };

      const turns = base.turns.length > 0 ? [...base.turns] : [emptyTurn()];
      const last = turns[turns.length - 1] ?? emptyTurn();
      turns[turns.length - 1] = {
        ...last,
        thinking: (last.thinking ?? "") + text,
        streamItems: appendStreamingSubagentChunk(
          last.streamItems,
          "thinking",
          text
        ),
      };

      const subagents = new Map(session.subagents);
      subagents.set(subagentSessionId, { ...base, turns });

      const updatedSession: BuildSessionData = {
        ...session,
        subagents,
        lastAccessed: new Date(),
      };
      const newSessions = new Map(state.sessions);
      newSessions.set(sessionId, updatedSession);
      return { sessions: newSessions };
    });
  },

  // ===========================================================================
  // Tab Navigation History Actions
  // ===========================================================================

  navigateTabBack: (sessionId) => {
    const session = get().sessions.get(sessionId);
    if (!session) return;
    const updates = navigateOutputHistory(session, -1);
    if (updates) get().updateSessionData(sessionId, updates);
  },

  navigateTabForward: (sessionId) => {
    const session = get().sessions.get(sessionId);
    if (!session) return;
    const updates = navigateOutputHistory(session, 1);
    if (updates) get().updateSessionData(sessionId, updates);
  },
}));

// =============================================================================
// Selector Hooks (mirrors chat's pattern)
// =============================================================================

// Stable empty references for SSR hydration (prevents infinite loop)
const EMPTY_PANEL_TABS: PanelTab[] = [];
const EMPTY_FILES_TAB_STATE: FilesTabState = {
  expandedPaths: [],
  scrollTop: 0,
};
const EMPTY_TAB_HISTORY: TabNavigationHistory = {
  entries: [],
  currentIndex: 0,
};
const EMPTY_SUBAGENTS: Map<string, SubagentState> = new Map();

/**
 * Returns the current session data with stable reference.
 * Returns null when no session exists.
 */
export const useSession = (): BuildSessionData | null =>
  useBuildSessionStore((state) => {
    const { currentSessionId, sessions } = state;
    if (!currentSessionId) return null;
    return sessions.get(currentSessionId) ?? null;
  });

export const useSessionId = () =>
  useBuildSessionStore((state) => state.currentSessionId);

export const useHasSession = () =>
  useBuildSessionStore((state) => state.currentSessionId !== null);

export const useIsRunning = () =>
  useBuildSessionStore((state) => {
    const { currentSessionId, sessions } = state;
    if (!currentSessionId) return false;
    const session = sessions.get(currentSessionId);
    return session?.status === "running" || session?.status === "creating";
  });

export const useIsInterrupting = () =>
  useBuildSessionStore((state) => {
    const { currentSessionId, sessions } = state;
    if (!currentSessionId) return false;
    return sessions.get(currentSessionId)?.isInterrupting ?? false;
  });

export const useWasInterrupted = () =>
  useBuildSessionStore((state) => {
    const { currentSessionId, sessions } = state;
    if (!currentSessionId) return false;
    return sessions.get(currentSessionId)?.wasInterrupted ?? false;
  });

export const useSessionHistory = () =>
  useBuildSessionStore((state) => state.sessionHistory);

/**
 * Returns the output panel open state for the current session.
 * Falls back to temporary state when no session exists (welcome page).
 * This temporary state resets to false when a session is created or cleared.
 */
export const useOutputPanelOpen = () =>
  useBuildSessionStore((state) => {
    const { currentSessionId, sessions, noSessionOutputPanelOpen } = state;
    if (!currentSessionId) return noSessionOutputPanelOpen;
    return sessions.get(currentSessionId)?.outputPanelOpen ?? false;
  });

export const useToggleOutputPanel = () =>
  useBuildSessionStore((state) => state.toggleCurrentOutputPanel);

// Pre-provisioning selectors
export const useIsPreProvisioning = () =>
  useBuildSessionStore(
    (state) => state.preProvisioning.status === "provisioning"
  );

export const useIsPreProvisioningReady = () =>
  useBuildSessionStore((state) => state.preProvisioning.status === "ready");

export const useIsPreProvisioningFailed = () =>
  useBuildSessionStore((state) => state.preProvisioning.status === "failed");

export const usePreProvisionedSessionId = () =>
  useBuildSessionStore((state) =>
    state.preProvisioning.status === "ready" ||
    state.preProvisioning.status === "starting"
      ? state.preProvisioning.sessionId
      : null
  );

// Queued messages selector
export const useQueuedMessages = () =>
  useBuildSessionStore((state) => {
    const { currentSessionId, sessions } = state;
    if (!currentSessionId) return EMPTY_CRAFT_QUEUED_MESSAGES;
    return (
      sessions.get(currentSessionId)?.queuedMessages ??
      EMPTY_CRAFT_QUEUED_MESSAGES
    );
  });

// Webapp refresh selector
export const useWebappNeedsRefresh = () =>
  useBuildSessionStore((state) => {
    const { currentSessionId, sessions } = state;
    if (!currentSessionId) return 0;
    return sessions.get(currentSessionId)?.webappNeedsRefresh ?? 0;
  });

// Webapp remount selector
export const useWebappNeedsRemount = () =>
  useBuildSessionStore((state) => {
    const { currentSessionId, sessions } = state;
    if (!currentSessionId) return 0;
    return sessions.get(currentSessionId)?.webappNeedsRemount ?? 0;
  });

// Panel tab selectors
export const usePanelTabs = () =>
  useBuildSessionStore((state) => {
    const { currentSessionId, sessions } = state;
    if (!currentSessionId) return EMPTY_PANEL_TABS;
    return sessions.get(currentSessionId)?.panelTabs ?? EMPTY_PANEL_TABS;
  });

export const useActiveOutputTab = () =>
  useBuildSessionStore((state) => {
    const { currentSessionId, sessions, noSessionActiveOutputTab } = state;
    if (!currentSessionId) return noSessionActiveOutputTab;
    return sessions.get(currentSessionId)?.activeOutputTab ?? "preview";
  });

export const useActivePanelTabId = () =>
  useBuildSessionStore((state) => {
    const { currentSessionId, sessions } = state;
    if (!currentSessionId) return null;
    return sessions.get(currentSessionId)?.activePanelTabId ?? null;
  });

export const useFilesTabState = (sessionId: string | null) =>
  useBuildSessionStore((state) => {
    if (!sessionId) return EMPTY_FILES_TAB_STATE;
    return (
      state.sessions.get(sessionId)?.filesTabState ?? EMPTY_FILES_TAB_STATE
    );
  });

export const useTabHistory = () =>
  useBuildSessionStore((state) => {
    const { currentSessionId, sessions } = state;
    if (!currentSessionId) return EMPTY_TAB_HISTORY;
    return sessions.get(currentSessionId)?.tabHistory ?? EMPTY_TAB_HISTORY;
  });

// Subagent selectors
export const useSubagents = () =>
  useBuildSessionStore((state) => {
    const { currentSessionId, sessions } = state;
    if (!currentSessionId) return EMPTY_SUBAGENTS;
    return sessions.get(currentSessionId)?.subagents ?? EMPTY_SUBAGENTS;
  });

export const useSubagent = (
  subagentSessionId: string | null
): SubagentState | null =>
  useBuildSessionStore((state) => {
    if (!subagentSessionId) return null;
    const { currentSessionId, sessions } = state;
    if (!currentSessionId) return null;
    return (
      sessions.get(currentSessionId)?.subagents.get(subagentSessionId) ?? null
    );
  });

/**
 * Subagent currently shown in the main column, or `null` for the normal chat
 * view. Returns `null` if the referenced subagent no longer exists.
 */
export const useViewedSubagentSessionId = (): string | null =>
  useBuildSessionStore((state) => {
    const { currentSessionId, sessions } = state;
    if (!currentSessionId) return null;
    const session = sessions.get(currentSessionId);
    if (!session) return null;
    const id = session.viewedSubagentSessionId;
    if (id === null || !session.subagents.has(id)) return null;
    return id;
  });

/** Title of the current session, derived from `sessionHistory`. */
export const useCurrentSessionTitle = (): string | null =>
  useBuildSessionStore((state) => {
    const { currentSessionId, sessionHistory } = state;
    if (!currentSessionId) return null;
    return (
      sessionHistory.find((item) => item.id === currentSessionId)?.title ?? null
    );
  });
