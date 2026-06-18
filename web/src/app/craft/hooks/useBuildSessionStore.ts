"use client";

import { create } from "zustand";
import { DELETE_SUCCESS_DISPLAY_DURATION_MS } from "@/app/craft/constants";

import {
  ApiSandboxResponse,
  Artifact,
  ArtifactType,
  BuildMessage,
  SessionHistoryItem,
  SessionOrigin,
  SessionStatus,
} from "@/app/craft/types/streamingTypes";

import {
  StreamItem,
  ToolCallState,
  TodoListState,
  type PanelTab,
  panelTabId,
  type SubagentState,
  type SubagentStatus,
  type SubagentTurn,
} from "@/app/craft/types/displayTypes";

import {
  QueuedMessage,
  MAX_QUEUED_MESSAGES,
  EMPTY_QUEUED_MESSAGES,
} from "@/app/app/interfaces";

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

      // agent_plan_update and other packet types are not rendered as stream items
      default:
        break;
    }
  }

  return items;
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
  | { status: "failed"; error: string; retryCount: number; retryAt: number };

// Module-level variable to store the provisioning promise (not in Zustand state for serializability)
let provisioningPromise: Promise<string | null> | null = null;

// Monotonic id for queued messages (kept out of Zustand state for simplicity).
let nextQueuedMessageId = 1;

/** File preview tab data */
export interface FilePreviewTab {
  path: string;
  fileName: string;
}

/** Files tab state - persisted across tab switches */
export interface FilesTabState {
  expandedPaths: string[];
  scrollTop: number;
  /** Cached directory listings by path - avoids refetch on tab switch */
  directoryCache: Record<string, unknown[]>;
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
  status: SessionStatus;
  messages: BuildMessage[];
  artifacts: Artifact[];
  /** Active backend turn, if this session is currently running. */
  activeTurnId: string | null;
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
  queuedMessages: QueuedMessage[];
  /**
   * True between an interrupt request and the turn actually terminating. Drives
   * the "stopping…" affordance; cleared by each terminal stream handler (and on
   * a fresh turn / aborted fetch).
   */
  isInterrupting: boolean;
  error: string | null;
  webappUrl: string | null;
  /** Sandbox info from backend */
  sandbox: ApiSandboxResponse | null;
  /** Model this session runs on (from the row); seeds the composer picker. */
  agentProvider: string | null;
  agentModel: string | null;
  origin: SessionOrigin;
  abortController: AbortController;
  lastAccessed: Date;
  isLoaded: boolean;
  outputPanelOpen: boolean;
  /** Counter to trigger webapp refresh when web/ files change (increments on each edit) */
  webappNeedsRefresh: number;
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
  /** True if the user has manually closed the panel this session; suppresses auto-open-on-first-preview */
  panelManuallyDismissed: boolean;
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
  addArtifactToCurrent: (artifact: Artifact) => void;
  setCurrentError: (error: string | null) => void;
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
  enqueueMessage: (sessionId: string, text: string) => void;
  removeQueuedMessage: (sessionId: string, index: number) => void;

  // Actions - Abort Control
  setAbortController: (sessionId: string, controller: AbortController) => void;
  abortSession: (sessionId: string) => void;
  abortCurrentSession: () => void;

  // Actions - Session Lifecycle
  loadSession: (
    sessionId: string,
    options?: { force?: boolean }
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

  // Auto-open Actions
  maybeAutoOpenPanelForPreview: (sessionId: string) => void;

  // File Preview Actions
  openFilePreview: (sessionId: string, path: string, fileName: string) => void;
  /** Atomically open panel + create file tab + set active for a markdown file detected during streaming */
  openMarkdownPreview: (sessionId: string, filePath: string) => void;
  closeFilePreview: (sessionId: string, path: string) => void;
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
  activeTurnIndex: null,
  activeTurnLocalOwner: false,
  streamItems: [],
  queuedMessages: [],
  isInterrupting: false,
  error: null,
  webappUrl: null,
  sandbox: null,
  agentProvider: null,
  agentModel: null,
  origin: "INTERACTIVE",
  abortController: new AbortController(),
  lastAccessed: new Date(),
  isLoaded: false,
  outputPanelOpen: false,
  webappNeedsRefresh: 0,
  filesNeedsRefresh: 0,
  panelTabs: [],
  subagents: new Map(),
  viewedSubagentSessionId: null,
  activeOutputTab: "preview",
  activePanelTabId: null,
  filesTabState: { expandedPaths: [], scrollTop: 0, directoryCache: {} },
  tabHistory: {
    entries: [{ type: "pinned", tab: "preview" }],
    currentIndex: 0,
  },
  panelManuallyDismissed: false,
  ...initialData,
});

// =============================================================================
// Store
// =============================================================================

// The dev server is started fire-and-forget, so the backend reports RUNNING
// before the webapp serves. Poll webapp-info until ready (bounded by maxAttempts).
export async function waitForWebappReady(
  sessionId: string,
  { intervalMs = 1500, maxAttempts = 20 }: WaitForWebappReadyOptions = {}
): Promise<void> {
  for (let attempt = 0; attempt < maxAttempts; attempt++) {
    let info: Awaited<ReturnType<typeof fetchWebappInfo>> | null = null;
    try {
      info = await fetchWebappInfo(sessionId);
    } catch {
      // keep polling
    }
    // Done on a definitive answer (no webapp or serving); errors keep polling.
    if (info && (!info.has_webapp || info.ready)) return;
    await new Promise((resolve) => setTimeout(resolve, intervalMs));
  }
}

interface WaitForWebappReadyOptions {
  intervalMs?: number;
  maxAttempts?: number;
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

  // Temporary active tab when no session exists
  noSessionActiveOutputTab: "preview" as OutputTabType,

  // ===========================================================================
  // Session Management (mirrors chat's pattern)
  // ===========================================================================

  setCurrentSession: (sessionId: string | null) => {
    set((state) => {
      // If setting to null, clear current session and reset no-session panel state
      if (sessionId === null) {
        return { currentSessionId: null, noSessionOutputPanelOpen: false };
      }

      // If session doesn't exist, create it and inherit output panel state
      if (!state.sessions.has(sessionId)) {
        const newSession = createInitialSessionData(sessionId, {
          outputPanelOpen: state.noSessionOutputPanelOpen,
        });
        const newSessions = new Map(state.sessions);
        newSessions.set(sessionId, newSession);
        return {
          currentSessionId: sessionId,
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
      // Inherit output panel state from no-session state if not explicitly set
      const outputPanelOpen =
        initialData?.outputPanelOpen ?? state.noSessionOutputPanelOpen;
      const newSession = createInitialSessionData(sessionId, {
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

  addArtifactToCurrent: (artifact: Artifact) => {
    const { currentSessionId } = get();
    if (!currentSessionId) return;

    set((state) => {
      const session = state.sessions.get(currentSessionId);
      if (!session) return state;

      const updatedSession: BuildSessionData = {
        ...session,
        artifacts: [...session.artifacts, artifact],
        lastAccessed: new Date(),
      };
      const newSessions = new Map(state.sessions);
      newSessions.set(currentSessionId, updatedSession);
      return { sessions: newSessions };
    });
  },

  setCurrentError: (error: string | null) => {
    const { currentSessionId, updateSessionData } = get();
    if (currentSessionId) {
      updateSessionData(currentSessionId, { error });
    }
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
        updateSessionData(currentSessionId, {
          outputPanelOpen: !session.outputPanelOpen,
          ...(closing ? { panelManuallyDismissed: true } : {}),
        });
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

      const streamItems = session.streamItems.map((item) => {
        if (item.type === "tool_call" && item.toolCall.id === toolCallId) {
          return {
            ...item,
            toolCall: { ...item.toolCall, ...updates },
          };
        }
        return item;
      }) as StreamItem[];

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

      const streamItems = session.streamItems.map((item, index) => {
        if (index === latestInFlightIndex && item.type === "tool_call") {
          return {
            ...item,
            toolCall: { ...item.toolCall, status: "cancelled" as const },
          };
        }
        return item;
      }) as StreamItem[];

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
        streamItems = session.streamItems.map((item, index) => {
          if (index === existingIndex && item.type === "todo_list") {
            return {
              ...item,
              todoList: { ...item.todoList, ...todoList },
            };
          }
          return item;
        }) as StreamItem[];
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

  enqueueMessage: (sessionId: string, text: string) => {
    set((state) => {
      const session = state.sessions.get(sessionId);
      if (!session || session.queuedMessages.length >= MAX_QUEUED_MESSAGES) {
        return state;
      }
      const updatedSession: BuildSessionData = {
        ...session,
        queuedMessages: [
          ...session.queuedMessages,
          { id: nextQueuedMessageId++, text },
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

  abortCurrentSession: () => {
    const { currentSessionId, abortSession } = get();
    if (currentSessionId) {
      abortSession(currentSessionId);
    }
  },

  // ===========================================================================
  // Session Lifecycle
  // ===========================================================================

  loadSession: async (sessionId: string, options?: { force?: boolean }) => {
    const { setCurrentSession, updateSessionData, sessions } = get();

    // Check if already loaded in cache
    const existingSession = sessions.get(sessionId);
    if (existingSession?.isLoaded && options?.force !== true) {
      setCurrentSession(sessionId);
      return;
    }

    // Set as current and mark as loading
    setCurrentSession(sessionId);

    try {
      // First fetch session to check sandbox status
      let sessionData = await fetchSession(sessionId);

      // Check if session needs to be restored:
      // - Sandbox is sleeping or terminated
      // - Sandbox is running but session workspace is not loaded
      const needsRestore =
        sessionData.sandbox?.status === "sleeping" ||
        sessionData.sandbox?.status === "terminated" ||
        (sessionData.sandbox?.status === "running" &&
          !sessionData.session_loaded_in_sandbox);

      if (needsRestore) {
        // Show sandbox as "restoring" while we load messages + restore
        updateSessionData(sessionId, {
          status: "creating",
          sandbox: sessionData.sandbox
            ? { ...sessionData.sandbox, status: "restoring" }
            : null,
        });
      }

      // Messages come from DB and don't need the sandbox running.
      // Artifacts need sandbox filesystem, so skip during restore.
      const messages = await fetchMessages(sessionId);
      let activeTurn: Awaited<ReturnType<typeof fetchActiveTurn>> = null;
      try {
        activeTurn = await fetchActiveTurn(sessionId);
      } catch (err) {
        console.warn("Failed to fetch active turn:", err);
      }
      const artifacts = needsRestore ? [] : await fetchArtifacts(sessionId);

      // Preserve optimistic messages if actively streaming (pre-provisioned flow).
      const currentSession = get().sessions.get(sessionId);
      const currentSessionIsLive =
        currentSession?.status === "running" ||
        currentSession?.status === "creating";
      const hasOptimisticMessages =
        (currentSession?.messages?.length ?? 0) > 0 && currentSessionIsLive;
      const isStreaming = hasOptimisticMessages;

      // Construct webapp URL
      let webappUrl: string | null = null;
      const hasWebapp = artifacts.some(
        (a) => a.type === "nextjs_app" || a.type === "web_app"
      );
      if (hasWebapp && sessionData.sandbox?.nextjs_port) {
        webappUrl = `http://localhost:${sessionData.sandbox.nextjs_port}`;
      }

      const resolvedActiveTurnId =
        activeTurn?.turn_id ??
        (isStreaming ? currentSession!.activeTurnId : null);
      const resolvedActiveTurnIndex =
        activeTurn?.turn_index ??
        (isStreaming ? currentSession!.activeTurnIndex : null);

      const status = isStreaming
        ? currentSession!.status
        : activeTurn
          ? "running"
          : needsRestore
            ? "creating"
            : sessionData.status === "active"
              ? "active"
              : "idle";
      const persistedMessages = isStreaming
        ? currentSession!.messages
        : consolidateMessagesIntoTurns(messages);
      const restoredActiveTurn = isStreaming
        ? {
            messages: persistedMessages,
            streamItems: currentSession!.streamItems,
          }
        : splitActiveTurnTranscript(persistedMessages, resolvedActiveTurnIndex);
      const resolvedMessages = restoredActiveTurn.messages;
      const streamItems = restoredActiveTurn.streamItems;
      // Reconstruct subagents from the raw (un-consolidated) messages — they
      // carry the per-packet _meta needed for classification. Preserve the
      // live map if actively streaming.
      const subagents = isStreaming
        ? currentSession!.subagents
        : buildSubagentsFromMessages(messages);
      const sandbox =
        needsRestore && sessionData.sandbox
          ? { ...sessionData.sandbox, status: "restoring" as const }
          : sessionData.sandbox;

      updateSessionData(sessionId, {
        status,
        messages: resolvedMessages,
        streamItems,
        subagents,
        artifacts,
        webappUrl,
        sandbox,
        agentProvider: sessionData.agent_provider,
        agentModel: sessionData.agent_model,
        origin: sessionData.origin,
        activeTurnId: resolvedActiveTurnId,
        activeTurnIndex: resolvedActiveTurnIndex,
        activeTurnLocalOwner: isStreaming
          ? currentSession!.activeTurnLocalOwner
          : false,
        error: null,
        isLoaded: true,
      });

      if (needsRestore) {
        try {
          sessionData = await restoreSession(sessionId);
        } catch (restoreErr) {
          // Only a genuine restore failure marks the sandbox failed.
          console.error("Sandbox restore failed:", restoreErr);
          updateSessionData(sessionId, {
            status: "idle",
            sandbox: sessionData.sandbox
              ? { ...sessionData.sandbox, status: "failed" }
              : null,
          });
          return;
        }

        // Hold the chip on "restoring" (and refresh the preview) until the
        // webapp actually serves, then flip to the real status below.
        updateSessionData(sessionId, {
          status: sessionData.status === "active" ? "active" : "idle",
          sandbox: sessionData.sandbox
            ? { ...sessionData.sandbox, status: "restoring" }
            : sessionData.sandbox,
          webappNeedsRefresh:
            (get().sessions.get(sessionId)?.webappNeedsRefresh || 0) + 1,
        });

        await waitForWebappReady(sessionId);
        updateSessionData(sessionId, { sandbox: sessionData.sandbox });

        // An artifact-fetch failure must NOT flip the sandbox to "failed".
        try {
          const restoredArtifacts = await fetchArtifacts(sessionId);
          updateSessionData(sessionId, { artifacts: restoredArtifacts });
        } catch (artifactsErr) {
          console.warn(
            "Failed to fetch artifacts after restore:",
            artifactsErr
          );
        }
      }
    } catch (err) {
      console.error("Failed to load session:", err);
      updateSessionData(sessionId, {
        error: (err as Error).message,
      });
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
          currentSessionId:
            currentSessionId === sessionId ? null : state.currentSessionId,
        };
      });

      // Refresh history after UI has shown success state
      setTimeout(
        () => refreshSessionHistory(),
        DELETE_SUCCESS_DISPLAY_DURATION_MS
      );
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
        set({
          preProvisioning: {
            status: "ready",
            sessionId: sessionData.id,
          },
        });
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
      if (!alreadyInHistory) {
        set({
          sessionHistory: [
            {
              id: sessionId,
              title: "Fresh Craft",
              createdAt: new Date(),
            },
            ...sessionHistory,
          ],
        });
      }

      // Reset to idle and return the session ID
      set({ preProvisioning: { status: "idle" } });
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
      // Increment refresh counter and open panel if not already open
      // Using a counter ensures each edit triggers a new refresh
      get().updateSessionData(sessionId, {
        webappNeedsRefresh: (session.webappNeedsRefresh || 0) + 1,
        ...(session.outputPanelOpen ? {} : { outputPanelOpen: true }),
      });
    }
  },

  triggerFilesRefresh: (sessionId: string) => {
    const session = get().sessions.get(sessionId);
    if (session) {
      // Increment refresh counter to trigger files list refresh
      // Using a counter ensures each write/edit triggers a new refresh
      // Also collapse the attachments directory to show fresh state
      const collapsedExpandedPaths = session.filesTabState.expandedPaths.filter(
        (path) => path !== "attachments" && !path.startsWith("attachments/")
      );
      get().updateSessionData(sessionId, {
        filesNeedsRefresh: (session.filesNeedsRefresh || 0) + 1,
        filesTabState: {
          ...session.filesTabState,
          expandedPaths: collapsedExpandedPaths,
        },
      });
    }
  },

  // ===========================================================================
  // Auto-open Actions
  // ===========================================================================

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
        activeOutputTab: "preview",
        activePanelTabId: null,
      });
      return { sessions: newSessions };
    });
  },

  // ===========================================================================
  // File Preview Actions
  // ===========================================================================

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

      const { tabHistory } = session;
      const newEntry: TabHistoryEntry = { type: "panel-tab", tabId };
      const newEntries = [
        ...tabHistory.entries.slice(0, tabHistory.currentIndex + 1),
        newEntry,
      ];

      const updatedSession: BuildSessionData = {
        ...session,
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

  closePanelTab: (sessionId: string, tabId: string) => {
    set((state) => {
      const session = state.sessions.get(sessionId);
      if (!session) return state;

      const panelTabs = session.panelTabs.filter(
        (t) => panelTabId(t) !== tabId
      );

      const wasActive = session.activePanelTabId === tabId;
      const activePanelTabId = wasActive ? null : session.activePanelTabId;
      const activeOutputTab = wasActive ? "files" : session.activeOutputTab;

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

  setActiveOutputTab: (sessionId: string, tab: OutputTabType) => {
    set((state) => {
      const session = state.sessions.get(sessionId);
      if (!session) return state;

      // Push to history (truncate forward history if navigating from middle)
      const { tabHistory } = session;
      const newEntry: TabHistoryEntry = { type: "pinned", tab };
      const newEntries = [
        ...tabHistory.entries.slice(0, tabHistory.currentIndex + 1),
        newEntry,
      ];

      const updatedSession: BuildSessionData = {
        ...session,
        activeOutputTab: tab,
        activePanelTabId: null, // Clear transient tab when selecting pinned tab
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

  setActivePanelTabId: (sessionId: string, tabId: string | null) => {
    set((state) => {
      const session = state.sessions.get(sessionId);
      if (!session) return state;

      // Push to history if switching to a panel tab (truncate forward history)
      const { tabHistory } = session;
      let newTabHistory = tabHistory;
      if (tabId !== null) {
        const newEntry: TabHistoryEntry = { type: "panel-tab", tabId };
        const newEntries = [
          ...tabHistory.entries.slice(0, tabHistory.currentIndex + 1),
          newEntry,
        ];
        newTabHistory = {
          entries: newEntries,
          currentIndex: newEntries.length - 1,
        };
      }

      const updatedSession: BuildSessionData = {
        ...session,
        activePanelTabId: tabId,
        tabHistory: newTabHistory,
        lastAccessed: new Date(),
      };
      const newSessions = new Map(state.sessions);
      newSessions.set(sessionId, updatedSession);
      return { sessions: newSessions };
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

  navigateTabBack: (sessionId: string) => {
    set((state) => {
      const session = state.sessions.get(sessionId);
      if (!session) return state;

      const { tabHistory } = session;
      if (tabHistory.currentIndex <= 0) return state;

      const newIndex = tabHistory.currentIndex - 1;
      const entry = tabHistory.entries[newIndex];
      if (!entry) return state;

      // TODO: extract a shared reconstructPanelTab(tabId) helper, or store the
      // full PanelTab in TabHistoryEntry instead of just the tabId, to avoid
      // duplicating this parsing in both navigateTabBack and navigateTabForward.
      // Re-open panel tab if it was closed
      let panelTabs = session.panelTabs;
      if (entry.type === "panel-tab") {
        const tabExists = panelTabs.some((t) => panelTabId(t) === entry.tabId);
        if (!tabExists) {
          // Reconstruct a file tab from the ID (format: "file:<path>")
          if (entry.tabId.startsWith("file:")) {
            const path = entry.tabId.slice("file:".length);
            const fileName = path.split("/").pop() || path;
            panelTabs = [...panelTabs, { kind: "file", path, fileName }];
          }
        }
      }

      const updatedSession: BuildSessionData = {
        ...session,
        tabHistory: { ...tabHistory, currentIndex: newIndex },
        activeOutputTab:
          entry.type === "pinned" ? entry.tab : session.activeOutputTab,
        activePanelTabId: entry.type === "panel-tab" ? entry.tabId : null,
        panelTabs,
        lastAccessed: new Date(),
      };
      const newSessions = new Map(state.sessions);
      newSessions.set(sessionId, updatedSession);
      return { sessions: newSessions };
    });
  },

  navigateTabForward: (sessionId: string) => {
    set((state) => {
      const session = state.sessions.get(sessionId);
      if (!session) return state;

      const { tabHistory } = session;
      if (tabHistory.currentIndex >= tabHistory.entries.length - 1)
        return state;

      const newIndex = tabHistory.currentIndex + 1;
      const entry = tabHistory.entries[newIndex];
      if (!entry) return state;

      // Re-open panel tab if it was closed
      let panelTabs = session.panelTabs;
      if (entry.type === "panel-tab") {
        const tabExists = panelTabs.some((t) => panelTabId(t) === entry.tabId);
        if (!tabExists) {
          // Reconstruct a file tab from the ID (format: "file:<path>")
          if (entry.tabId.startsWith("file:")) {
            const path = entry.tabId.slice("file:".length);
            const fileName = path.split("/").pop() || path;
            panelTabs = [...panelTabs, { kind: "file", path, fileName }];
          }
        }
      }

      const updatedSession: BuildSessionData = {
        ...session,
        tabHistory: { ...tabHistory, currentIndex: newIndex },
        activeOutputTab:
          entry.type === "pinned" ? entry.tab : session.activeOutputTab,
        activePanelTabId: entry.type === "panel-tab" ? entry.tabId : null,
        panelTabs,
        lastAccessed: new Date(),
      };
      const newSessions = new Map(state.sessions);
      newSessions.set(sessionId, updatedSession);
      return { sessions: newSessions };
    });
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
  directoryCache: {},
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
    state.preProvisioning.status === "ready"
      ? state.preProvisioning.sessionId
      : null
  );

// Queued messages selector
export const useQueuedMessages = () =>
  useBuildSessionStore((state) => {
    const { currentSessionId, sessions } = state;
    if (!currentSessionId) return EMPTY_QUEUED_MESSAGES;
    return (
      sessions.get(currentSessionId)?.queuedMessages ?? EMPTY_QUEUED_MESSAGES
    );
  });

// Webapp refresh selector
export const useWebappNeedsRefresh = () =>
  useBuildSessionStore((state) => {
    const { currentSessionId, sessions } = state;
    if (!currentSessionId) return 0;
    return sessions.get(currentSessionId)?.webappNeedsRefresh ?? 0;
  });

// Files refresh selector
export const useFilesNeedsRefresh = () =>
  useBuildSessionStore((state) => {
    const { currentSessionId, sessions } = state;
    if (!currentSessionId) return 0;
    return sessions.get(currentSessionId)?.filesNeedsRefresh ?? 0;
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

export const useFilesTabState = () =>
  useBuildSessionStore((state) => {
    const { currentSessionId, sessions } = state;
    if (!currentSessionId) return EMPTY_FILES_TAB_STATE;
    return (
      sessions.get(currentSessionId)?.filesTabState ?? EMPTY_FILES_TAB_STATE
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
