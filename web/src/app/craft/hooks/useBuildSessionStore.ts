"use client";

import type { TextPartUpdate } from "@/app/craft/utils/packetTypes";

import type { BuildLlmSelection } from "@/app/craft/onboarding/constants";

import { create } from "zustand";
import { mutate } from "swr";
import { SWR_KEYS } from "@/lib/swr-keys";
import { useShallow } from "zustand/react/shallow";
import {
  readOutputPanelPreferences,
  clearOutputPanelPreferences,
} from "@/app/craft/services/outputPanelPreferences";

import {
  ApiSessionResponse,
  Artifact,
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
  type OutputPanelMode,
  normalizePanelPath,
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
  fetchKnownTurn,
  fetchScheduledRunContext,
  fetchArtifacts,
  fetchOutputInventory,
  fetchWebappInfo,
  restoreSession,
} from "@/app/craft/services/apiServices";

import { isAuthStatusError, isNotFoundError } from "@/lib/fetcher";

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
  let items: StreamItem[] = [];

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
        if (packet.text && packet.part) {
          items = settleStreamItems(
            appendStreamingChunk(items, "text", packet.text, packet.part)
          );
        } else if (packet.text) {
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
        if (packet.text && packet.part) {
          items = settleStreamItems(
            appendStreamingChunk(items, "thinking", packet.text, packet.part)
          );
        } else if (packet.text) {
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

function appendStreamingChunk(
  items: StreamItem[],
  type: "text" | "thinking",
  text: string,
  part?: TextPartUpdate
): StreamItem[] {
  if (part) {
    const existing = items.find(
      (item) => item.type === type && item.partId === part.partId
    );
    if (
      existing &&
      (existing.type === "text" || existing.type === "thinking")
    ) {
      return items.map((item) =>
        item === existing
          ? {
              ...existing,
              content: part.snapshotText ?? existing.content + text,
            }
          : item
      );
    }
    return [
      ...settleStreamItems(items),
      {
        type,
        id: genId(type),
        partId: part.partId,
        content: part.snapshotText ?? text,
        isStreaming: true,
      },
    ];
  }
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
    return settleStreamItems(appendStreamingChunk(settled, "text", text));
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
              appendStreamingChunk(
                last.streamItems,
                "text",
                packet.text,
                packet.part
              )
            ),
          };
        } else {
          turns[turns.length - 1] = {
            ...last,
            thinking: (last.thinking ?? "") + packet.text,
            streamItems: settleStreamItems(
              appendStreamingChunk(
                last.streamItems,
                "thinking",
                packet.text,
                packet.part
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
        // Child rows own the transcript; response can contain several parts.
        streamItems:
          firstTurn.response !== null
            ? settleStreamItems(firstTurn.streamItems)
            : replaceOrAppendSettledTextItem(firstTurn.streamItems, response),
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

interface OutputInventoryRequest {
  controller: AbortController;
  promise: Promise<void>;
  session: BuildSessionData;
  coalescible: boolean;
}
const outputInventoryRequests = new Map<string, OutputInventoryRequest>();

function sameSessionRuntime(
  first: BuildSessionData,
  second: BuildSessionData
): boolean {
  return (
    first.instanceId === second.instanceId &&
    first.sandbox?.id === second.sandbox?.id &&
    first.sandbox?.status === second.sandbox?.status
  );
}

// Monotonic id for queued messages (kept out of Zustand state for simplicity).
let nextQueuedMessageId = 1;

export interface CraftQueuedMessage {
  id: number;
  phase: "waiting" | "starting" | "failed";
  model?: BuildLlmSelection | null;
  text: string;
  attachments: BuildMessageAttachment[];
}

const EMPTY_CRAFT_QUEUED_MESSAGES: readonly CraftQueuedMessage[] = [];

/** Files tab state - persisted across tab switches */
export interface FilesTabState {
  expandedPaths: string[];
  scrollTop: number;
}

export type CompletionOwner =
  | { kind: "interactive"; turnId: string | null }
  | { kind: "scheduled"; runId: string };

export type TurnSettlement = {
  owner: CompletionOwner;
  turnGeneration: number;
} & (
  | { phase: "reconciling" | "ready" }
  | { phase: "failed"; error: string | null }
);

export interface BuildSessionData {
  id: string;
  /** Reject responses from an earlier instance of this local session. */
  instanceId: string;
  status: SessionStatus;
  messages: BuildMessage[];
  artifacts: Artifact[];
  /** Active backend turn, if this session is currently running. */
  activeTurnId: string | null;
  /** The streamed response stays visible until this turn reaches durable completion. */
  turnSettlement: TurnSettlement | null;
  /** The user-message turn index for the active backend turn. */
  activeTurnIndex: number | null;
  /** True while this tab owns a pending start or its accepted turn stream. */
  activeTurnLocalOwner: boolean;
  /**
   * FIFO stream items for the current agent turn.
   * Items are stored in chronological order as they arrive.
   * Rendered directly without transformation.
   */
  streamItems: StreamItem[];
  /**
   * Messages typed while a response is streaming. Auto-sent FIFO once the
   * session confirms completion and its stream owner claims the queue head.
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
  /** Only the latest API load can publish session state. */
  loadGeneration: number;
  error: string | null;
  loadError: string | null;
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
  /** UI identity remains stable while a welcome workspace becomes a conversation. */
  outputWorkspaceId: string;
  outputPanelMode: OutputPanelMode;
  outputPanelInitialized: boolean;
  mediumPanelProportion: number;
  /** Counter to trigger webapp refresh when web/ files change (increments on each edit) */
  webappNeedsRefresh: number;
  /** Counter to force an iframe remount (restore only — live edits are handled by HMR) */
  webappNeedsRemount: number;
  /** Counter to trigger files list refresh when outputs/ directory changes (increments on each write/edit) */
  filesNeedsRefresh: number;
  /** The Outputs collection can be narrowed to one completed turn. */
  outputsTabState: {
    turnIndex: number | null;
    searchQuery: string;
    folder: string;
    fileType: string;
  };
  /** Ordered resource tabs scoped to this session. */
  panelTabs: PanelTab[];
  /** Subagents spawned in this session, keyed by child opencode session id. */
  subagents: Map<string, SubagentState>;
  /**
   * When non-null, the main (left) column shows this subagent's transcript
   * in place of the chat. `null` = normal chat view.
   */
  viewedSubagentSessionId: string | null;
  /** Selected resource tab, or null when all tabs are closed. */
  activePanelTabId: string | null;
  /** Unique open tab IDs, most recently viewed first. */
  panelTabHistory: string[];
  /** Files tab state - expanded folders and scroll position */
  filesTabState: FilesTabState;
  /** Shared file metadata for discovery and preview revisions. */
  outputInventory: Record<string, OutputFile> | null;
  outputInventoryStatus: "unloaded" | "complete" | "partial" | "error";
  outputInventoryLoading: boolean;
  outputInventoryError?: Error;
  /** True until an authoritative inventory establishes which files predate this task. */
  outputBaselinePending: boolean;
  /** Manual navigation or the first automatic preview retains selection until the next task. */
  outputSelectionLocked: boolean;
  /** Explicit preview reloads, keyed by file path. File edits use inventory revisions. */
  filePreviewRefreshKeys: Record<string, number>;
}

export function canReuseSession(
  session: BuildSessionData | undefined
): boolean {
  return (
    session?.isLoaded === true &&
    session.loadError === null &&
    session.turnSettlement?.phase !== "reconciling" &&
    session.sandbox?.status !== "sleeping" &&
    session.sandbox?.status !== "terminated" &&
    session.sandbox?.status !== "failed"
  );
}

const completedTranscriptReads: Map<string, Promise<void>> = new Map();

function reconcileCompletedTranscript(
  sessionId: string,
  started: BuildSessionData
): Promise<void> {
  const owner = started.turnSettlement?.owner;
  const requestKey = `${sessionId}:${started.instanceId}:${started.turnGeneration}:${owner?.kind}:${owner?.kind === "interactive" ? owner.turnId : owner?.runId}`;
  const existing = completedTranscriptReads.get(requestKey);
  if (existing) return existing;
  const ownsCompletion = () => {
    const current = useBuildSessionStore.getState().sessions.get(sessionId);
    return (
      current?.instanceId === started.instanceId &&
      current.turnGeneration === started.turnGeneration &&
      current.turnSettlement?.owner === owner &&
      current.turnSettlement?.phase === "reconciling"
    );
  };
  const fail = (error: unknown) => {
    const current = useBuildSessionStore.getState().sessions.get(sessionId);
    if (!ownsCompletion() || !current?.turnSettlement) return;
    useBuildSessionStore.getState().updateSessionData(sessionId, {
      status: "idle",
      isInterrupting: false,
      turnSettlement: {
        ...current.turnSettlement,
        phase: "failed",
        error:
          error === null
            ? null
            : error instanceof Error
              ? error.message
              : String(error),
      },
    });
  };
  const request = (async () => {
    try {
      for (let attempt = 0; attempt < 33; attempt++) {
        // Catch the usual short commit tail quickly, then back off for slow workers.
        const retryDelay = attempt < 4 ? 250 : 1000;
        if (!ownsCompletion()) return;
        if (!owner) return;
        let waiting: boolean;
        let approvalPause = false;
        let scheduledFailure = false;
        let interactiveFailure: string | null = null;
        let interactiveFailed = false;
        let successor: Awaited<ReturnType<typeof fetchActiveTurn>> = null;
        if (owner.kind === "scheduled") {
          const run = await fetchScheduledRunContext(sessionId);
          if (!ownsCompletion()) return;
          if (run.run_id !== owner.runId) return;
          scheduledFailure =
            run.status === "FAILED" || run.status === "SKIPPED";
          waiting = run.status === "RUNNING" || run.status === "QUEUED";
          approvalPause = run.status === "AWAITING_APPROVAL";
        } else {
          const activeTurn = await fetchActiveTurn(sessionId);
          if (!ownsCompletion()) return;
          successor =
            activeTurn && activeTurn.turn_id !== owner.turnId
              ? activeTurn
              : null;
          waiting = activeTurn !== null && !successor;
        }
        if (!ownsCompletion()) return;
        if (waiting) {
          await new Promise<void>((resolve) => setTimeout(resolve, retryDelay));
          continue;
        }
        if (owner.kind === "interactive" && owner.turnId !== null) {
          const completedTurn = await fetchKnownTurn(sessionId, owner.turnId);
          if (!ownsCompletion()) return;
          if (!completedTurn) {
            fail(null);
            return;
          }
          if (
            completedTurn.status === "QUEUED" ||
            completedTurn.status === "RUNNING"
          ) {
            await new Promise<void>((resolve) =>
              setTimeout(resolve, retryDelay)
            );
            continue;
          }
          interactiveFailed = completedTurn.status === "FAILED";
          interactiveFailure = completedTurn.error_detail ?? null;
        }
        // The worker has committed output revisions. Fetch cards alongside history.
        void mutate(
          (key) =>
            Array.isArray(key) &&
            key[0] === SWR_KEYS.buildSessionOutputCards(sessionId)
        ).catch(() => undefined);
        let messages = await fetchMessages(sessionId);
        if (!ownsCompletion()) return;
        if (owner.kind === "interactive") {
          const historyTurnId = successor?.turn_id;
          const activeTurn = await fetchActiveTurn(sessionId);
          if (!ownsCompletion()) return;
          if (activeTurn) {
            if (activeTurn.turn_id === owner.turnId) {
              await new Promise<void>((resolve) =>
                setTimeout(resolve, retryDelay)
              );
              continue;
            }
            successor = activeTurn;
          }
          if (successor && successor.turn_id !== historyTurnId) {
            messages = await fetchMessages(sessionId);
            if (!ownsCompletion()) return;
          }
        }
        const restored = splitActiveTurnTranscript(
          consolidateMessagesIntoTurns(messages),
          successor?.turn_index ?? null
        );
        const current = useBuildSessionStore.getState().sessions.get(sessionId);
        if (!current?.turnSettlement) return;
        if (!successor)
          void useBuildSessionStore
            .getState()
            .refreshOutputInventory(sessionId);
        useBuildSessionStore.getState().updateSessionData(sessionId, {
          messages: restored.messages,
          streamItems: restored.streamItems,
          subagents: buildSubagentsFromMessages(messages),
          contextUsage: deriveContextUsage(messages),
          status: successor
            ? "running"
            : scheduledFailure || interactiveFailed
              ? "failed"
              : "active",
          error:
            interactiveFailed && !successor
              ? interactiveFailure
              : current.error,
          isInterrupting: false,
          activeTurnId: successor?.turn_id ?? null,
          activeTurnIndex: successor?.turn_index ?? null,
          activeTurnLocalOwner: false,
          ...(successor && {
            turnGeneration: current.turnGeneration + 1,
            outputSelectionLocked: false,
            wasInterrupted: false,
          }),
          turnSettlement:
            successor || approvalPause || scheduledFailure || interactiveFailed
              ? null
              : { ...current.turnSettlement, phase: "ready" },
        });
        return;
      }
      fail(null);
    } catch (error) {
      fail(error);
    }
  })().finally(() => completedTranscriptReads.delete(requestKey));
  completedTranscriptReads.set(requestKey, request);
  return request;
}

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
  return { files, added, changed };
}

function panelTabHistory(
  tabs: PanelTab[],
  active: string | null,
  history: readonly string[] = []
): string[] {
  const openIds = new Set(tabs.map(panelTabId));
  return [...new Set(active ? [active, ...history] : history)].filter((id) =>
    openIds.has(id)
  );
}

function selectOutputTarget(
  session: Pick<BuildSessionData, "panelTabs" | "panelTabHistory">,
  target: PanelTab
): Pick<
  BuildSessionData,
  "panelTabs" | "activePanelTabId" | "panelTabHistory"
> {
  const id = panelTabId(target);
  const panelTabs = session.panelTabs.some((tab) => panelTabId(tab) === id)
    ? session.panelTabs
    : [...session.panelTabs, target];
  return {
    activePanelTabId: id,
    panelTabs,
    panelTabHistory: panelTabHistory(panelTabs, id, session.panelTabHistory),
  };
}

function selectWelcomeOutputTarget(
  state: BuildSessionStore,
  target: PanelTab
): Partial<BuildSessionStore> {
  const selected = selectOutputTarget(
    {
      panelTabs: state.noSessionPanelTabs,
      panelTabHistory: state.noSessionPanelTabHistory,
    },
    target
  );
  return {
    noSessionPanelTabs: selected.panelTabs,
    noSessionActivePanelTabId: selected.activePanelTabId,
    noSessionPanelTabHistory: selected.panelTabHistory,
  };
}

function canAutomaticallySelectOutput(session: BuildSessionData): boolean {
  return (
    !session.outputSelectionLocked &&
    !session.isInterrupting &&
    !session.wasInterrupted &&
    session.status !== "failed"
  );
}

function automaticallySelectOutput(
  session: BuildSessionData,
  target: PanelTab
): Partial<BuildSessionData> {
  if (!canAutomaticallySelectOutput(session)) return {};
  const panelTabs: PanelTab[] = session.outputPanelInitialized
    ? session.panelTabs
    : [{ kind: "outputs" }, ...session.panelTabs];
  return {
    ...selectOutputTarget({ ...session, panelTabs }, target),
    outputSelectionLocked: true,
    outputPanelInitialized: true,
    outputPanelMode:
      session.outputPanelMode === "closed" ? "medium" : session.outputPanelMode,
  };
}

const webappAutoOpenRequests = new Map<
  string,
  { session: BuildSessionData; promise: Promise<void> }
>();

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
  noSessionOutputWorkspaceId: string;
  noSessionOutputPanelMode: OutputPanelMode;
  noSessionOutputPanelInitialized: boolean;
  noSessionMediumPanelProportion: number;
  noSessionPanelTabs: PanelTab[];
  noSessionActivePanelTabId: string | null;
  noSessionPanelTabHistory: string[];

  // Temporary active tab when no session exists (resets when session is created/cleared)

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
    attachments: BuildMessageAttachment[],
    model?: BuildLlmSelection | null
  ) => boolean;
  removeQueuedMessage: (sessionId: string, messageId: number) => void;
  claimQueuedMessage: (sessionId: string) => CraftQueuedMessage | null;
  beginTurnSettlement: (
    sessionId: string,
    owner: CompletionOwner,
    generation: number
  ) => Promise<void>;
  retryTurnSettlement: (sessionId: string) => Promise<void>;

  // Actions - Abort Control
  setAbortController: (sessionId: string, controller: AbortController) => void;
  abortSession: (sessionId: string) => void;

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
  maybeAutoOpenWebapp: (sessionId: string) => Promise<void>;
  // Files Refresh Actions
  triggerFilesRefresh: (sessionId: string) => void;

  // Output inventory and automatic navigation
  refreshOutputInventory: (
    sessionId: string,
    options?: { silent?: boolean; signal?: AbortSignal }
  ) => Promise<void>;

  // File Preview Actions
  openFilePreview: (
    sessionId: string | null,
    path: string,
    fileName: string
  ) => void;
  /** Generic: remove the panel tab whose panelTabId === tabId; clears active if it was active. */
  setCurrentOutputPanelMode: (mode: OutputPanelMode) => void;
  setCurrentMediumPanelProportion: (proportion: number) => void;
  openOutputsTab: (sessionId: string | null, turnIndex?: number | null) => void;
  updateOutputsTabState: (
    sessionId: string,
    updates: Partial<BuildSessionData["outputsTabState"]>
  ) => void;
  openFilesTab: (sessionId: string | null) => void;
  openBrowserTab: (
    sessionId: string | null,
    appId?: string,
    appName?: string
  ) => void;
  navigateBrowserTab: (
    sessionId: string | null,
    tabId: string,
    appId: string | null,
    appName?: string
  ) => void;
  reorderPanelTab: (
    sessionId: string | null,
    tabId: string,
    index: number
  ) => void;
  closePanelTab: (sessionId: string | null, tabId: string) => void;
  setActivePanelTabId: (sessionId: string | null, tabId: string | null) => void;
  /** Set active tab when no session exists (for pre-provisioned sandbox viewing) */

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
    text: string,
    part?: TextPartUpdate
  ) => void;
  /** Append streamed thinking text to the LAST turn's thinking stream. */
  appendSubagentThinkingChunk: (
    sessionId: string,
    subagentSessionId: string,
    text: string,
    part?: TextPartUpdate
  ) => void;
}

// =============================================================================
// Initial State Factory
// =============================================================================

const createInitialSessionData = (
  sessionId: string,
  initialData?: Partial<BuildSessionData>
): BuildSessionData => {
  const preferences = readOutputPanelPreferences(sessionId);
  initialData = { ...preferences, ...initialData };
  const mode = initialData?.outputPanelMode ?? "closed";
  let panelTabs = (initialData?.panelTabs ?? []).map(
    (tab): PanelTab =>
      tab.kind === "file" ? { ...tab, path: normalizePanelPath(tab.path) } : tab
  );
  let activePanelTabId = initialData?.activePanelTabId ?? null;
  if (activePanelTabId?.startsWith("file:"))
    activePanelTabId = `file:${normalizePanelPath(activePanelTabId.slice("file:".length))}`;
  const initialized =
    initialData?.outputPanelInitialized ??
    (mode !== "closed" || panelTabs.length > 0);
  if (
    mode !== "closed" &&
    panelTabs.length === 0 &&
    initialData?.outputPanelInitialized === undefined
  ) {
    panelTabs = [{ kind: "outputs" }];
    activePanelTabId = "outputs";
  }
  return {
    id: sessionId,
    status: "idle",
    messages: [],
    artifacts: [],
    activeTurnId: null,
    turnSettlement: null,
    activeTurnIndex: null,
    activeTurnLocalOwner: false,
    streamItems: [],
    queuedMessages: [],
    isInterrupting: false,
    wasInterrupted: false,
    turnGeneration: 0,
    loadGeneration: 0,
    error: null,
    loadError: null,
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

    mediumPanelProportion: 0.5,
    webappNeedsRefresh: 0,
    webappNeedsRemount: 0,
    filesNeedsRefresh: 0,
    outputsTabState: {
      turnIndex: null,
      searchQuery: "",
      folder: "",
      fileType: "all",
    },
    subagents: new Map(),
    viewedSubagentSessionId: null,
    filesTabState: {
      expandedPaths: ["outputs"],
      scrollTop: 0,
    },
    outputInventory: null,
    outputInventoryStatus: "unloaded",
    outputInventoryLoading: false,
    outputBaselinePending: initialData?.outputInventory == null,
    outputSelectionLocked: preferences?.outputPanelInitialized ?? false,
    filePreviewRefreshKeys: {},
    ...initialData,
    instanceId: genId("session-state"),
    outputWorkspaceId: initialData?.outputWorkspaceId ?? sessionId,
    outputPanelMode: mode,
    outputPanelInitialized: initialized,
    panelTabs,
    activePanelTabId,
    panelTabHistory: panelTabHistory(
      panelTabs,
      activePanelTabId,
      initialData.panelTabHistory
    ),
  };
};

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
  noSessionOutputWorkspaceId: genId("workspace"),
  noSessionOutputPanelMode: "closed",
  noSessionOutputPanelInitialized: false,
  noSessionMediumPanelProportion: 0.5,
  noSessionPanelTabs: [],
  noSessionActivePanelTabId: null,
  noSessionPanelTabHistory: [],

  // ===========================================================================
  // Session Management (mirrors chat's pattern)
  // ===========================================================================

  setCurrentSession: (sessionId: string | null) => {
    set((state) => {
      // If setting to null, clear current session and reset no-session panel state
      if (sessionId === null) {
        return {
          currentSessionId: null,
          noSessionOutputWorkspaceId: genId("workspace"),
          noSessionOutputPanelMode: "closed",
          noSessionOutputPanelInitialized: false,
          noSessionPanelTabs: [],
          noSessionActivePanelTabId: null,
          noSessionPanelTabHistory: [],
        };
      }

      // Keep the welcome sandbox available until the URL selects a session.
      const preProvisioning: PreProvisioningState =
        state.preProvisioning.status === "starting"
          ? { status: "idle" }
          : state.preProvisioning;

      // History sessions restore their own panel preferences.
      if (!state.sessions.has(sessionId)) {
        const newSession = createInitialSessionData(sessionId);
        const newSessions = new Map(state.sessions);
        newSessions.set(sessionId, newSession);
        return {
          currentSessionId: sessionId,
          preProvisioning,
          sessions: newSessions,
        };
      }

      // Update last accessed for existing session and reset no-session panel state
      const session = state.sessions.get(sessionId)!;
      const claimedWelcome =
        state.currentSessionId === null &&
        state.noSessionOutputPanelInitialized &&
        (state.preProvisioning.status === "ready" ||
          state.preProvisioning.status === "starting") &&
        state.preProvisioning.sessionId === sessionId;
      const updatedSession = { ...session, lastAccessed: new Date() };
      if (claimedWelcome) {
        updatedSession.outputWorkspaceId = state.noSessionOutputWorkspaceId;
        updatedSession.outputPanelMode = state.noSessionOutputPanelMode;
        updatedSession.outputPanelInitialized = true;
        updatedSession.panelTabs = state.noSessionPanelTabs;
        updatedSession.activePanelTabId = state.noSessionActivePanelTabId;
        updatedSession.panelTabHistory = state.noSessionPanelTabHistory;
        updatedSession.mediumPanelProportion =
          state.noSessionMediumPanelProportion;
      }
      const newSessions = new Map(state.sessions);
      newSessions.set(sessionId, updatedSession);

      return {
        currentSessionId: sessionId,
        preProvisioning,
        sessions: newSessions,
      };
    });
  },

  // Initialize local session state (does NOT create backend session - use apiCreateSession for that)
  createSession: (
    sessionId: string,
    initialData?: Partial<BuildSessionData>
  ) => {
    set((state) => {
      const existingSession = state.sessions.get(sessionId);
      // Carry the welcome panel's visible tab into the conversation.
      const newSession = createInitialSessionData(sessionId, {
        ...(state.currentSessionId === null &&
          state.noSessionOutputPanelInitialized && {
            outputWorkspaceId: state.noSessionOutputWorkspaceId,
            outputPanelMode: state.noSessionOutputPanelMode,
            outputPanelInitialized: true,
            panelTabs: state.noSessionPanelTabs,
            activePanelTabId: state.noSessionActivePanelTabId,
            panelTabHistory: state.noSessionPanelTabHistory,
            mediumPanelProportion: state.noSessionMediumPanelProportion,
          }),
        ...(existingSession && {
          filesTabState: existingSession.filesTabState,
        }),
        ...initialData,
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
    const state = get();
    const mode = state.currentSessionId
      ? state.sessions.get(state.currentSessionId)?.outputPanelMode
      : state.noSessionOutputPanelMode;
    state.setCurrentOutputPanelMode(mode === "closed" ? "medium" : "closed");
  },

  setCurrentOutputPanelMode: (mode) => {
    const state = get();
    if (state.currentSessionId) {
      const session = state.sessions.get(state.currentSessionId);
      if (!session) return;
      const updates: Partial<BuildSessionData> = {
        outputPanelMode: mode,
        ...(mode === "closed" && { outputSelectionLocked: true }),
        outputPanelInitialized:
          session.outputPanelInitialized || mode !== "closed",
      };
      if (mode !== "closed" && !session.outputPanelInitialized)
        Object.assign(
          updates,
          selectOutputTarget(session, { kind: "outputs" })
        );
      state.updateSessionData(state.currentSessionId, updates);
    } else {
      const fresh = mode !== "closed" && !state.noSessionOutputPanelInitialized;
      const updates: Partial<BuildSessionStore> = {
        noSessionOutputPanelInitialized:
          state.noSessionOutputPanelInitialized || mode !== "closed",
        noSessionOutputPanelMode: mode,
      };
      if (fresh) {
        Object.assign(
          updates,
          selectWelcomeOutputTarget(state, { kind: "outputs" })
        );
      }
      set(updates);
    }
  },

  setCurrentMediumPanelProportion: (proportion) => {
    if (!Number.isFinite(proportion)) return;
    const value = Math.max(0, Math.min(1, proportion));
    const state = get();
    if (state.currentSessionId)
      state.updateSessionData(state.currentSessionId, {
        mediumPanelProportion: value,
      });
    else set({ noSessionMediumPanelProportion: value });
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
    if (artifact.type === "nextjs_app" || artifact.type === "web_app")
      void get().maybeAutoOpenWebapp(sessionId);
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
    attachments: BuildMessageAttachment[],
    model?: BuildLlmSelection | null
  ) => {
    let accepted = false;
    set((state) => {
      const session = state.sessions.get(sessionId);
      if (
        !session ||
        session.queuedMessages.length >= MAX_QUEUED_MESSAGES ||
        (session.status === "creating" &&
          !session.activeTurnLocalOwner &&
          session.activeTurnId === null)
      ) {
        return state;
      }
      accepted = true;
      const updatedSession: BuildSessionData = {
        ...session,
        queuedMessages: [
          ...session.queuedMessages,
          {
            id: nextQueuedMessageId++,
            phase: "waiting",
            text,
            attachments,
            model,
          },
        ],
        lastAccessed: new Date(),
      };
      const newSessions = new Map(state.sessions);
      newSessions.set(sessionId, updatedSession);
      return { sessions: newSessions };
    });
    return accepted;
  },

  claimQueuedMessage: (sessionId) => {
    let claimed: CraftQueuedMessage | null = null;
    set((state) => {
      const session = state.sessions.get(sessionId);
      if (
        !session ||
        session.status !== "active" ||
        session.activeTurnId !== null ||
        session.error ||
        session.turnSettlement?.phase !== "ready" ||
        session.turnSettlement.turnGeneration !== session.turnGeneration
      )
        return state;
      const head = session.queuedMessages[0];
      if (!head || head.phase !== "waiting") return state;
      claimed = head;
      const sessions = new Map(state.sessions);
      sessions.set(sessionId, {
        ...session,
        queuedMessages: session.queuedMessages.map((message) =>
          message.id === head.id ? { ...message, phase: "starting" } : message
        ),
      });
      return { sessions };
    });
    return claimed;
  },

  beginTurnSettlement: async (sessionId, owner, generation) => {
    const session = get().sessions.get(sessionId);
    if (
      !session ||
      session.turnGeneration !== generation ||
      session.error ||
      session.isInterrupting ||
      session.turnSettlement
    )
      return;
    if (owner.kind === "scheduled") {
      if (session.activeTurnLocalOwner || session.activeTurnId !== null) return;
    } else if (session.status !== "running" && session.status !== "creating")
      return;
    get().updateSessionData(sessionId, {
      status: "running",
      activeTurnId: null,
      activeTurnIndex: null,
      activeTurnLocalOwner: false,
      turnSettlement: {
        owner,
        turnGeneration: generation,
        phase: "reconciling",
      },
    });
    const started = get().sessions.get(sessionId);
    if (started) await reconcileCompletedTranscript(sessionId, started);
  },

  retryTurnSettlement: async (sessionId) => {
    const session = get().sessions.get(sessionId);
    if (
      !session?.turnSettlement ||
      session.turnSettlement.phase !== "failed" ||
      session.turnSettlement.turnGeneration !== session.turnGeneration ||
      session.activeTurnId !== null
    )
      return;
    get().updateSessionData(sessionId, {
      status: "running",
      turnSettlement: {
        owner: session.turnSettlement.owner,
        turnGeneration: session.turnGeneration,
        phase: "reconciling",
      },
    });
    const started = get().sessions.get(sessionId);
    if (started) await reconcileCompletedTranscript(sessionId, started);
  },

  removeQueuedMessage: (sessionId: string, messageId: number) => {
    let discardedStart: BuildSessionData | undefined;
    set((state) => {
      const session = state.sessions.get(sessionId);
      if (!session) return state;
      const head = session.queuedMessages[0];
      const discardsFailedStart =
        head?.id === messageId &&
        head.phase === "failed" &&
        (session.status === "failed" || session.status === "active") &&
        session.error !== null &&
        session.activeTurnId === null &&
        !session.activeTurnLocalOwner &&
        session.turnSettlement === null;
      const updatedSession: BuildSessionData = {
        ...session,
        queuedMessages: session.queuedMessages.filter(
          (message) => message.id !== messageId || message.phase === "starting"
        ),
        ...(discardsFailedStart && {
          status: "running" as const,
          error: null,
          isInterrupting: false,
          turnSettlement: {
            owner: { kind: "interactive" as const, turnId: null },
            turnGeneration: session.turnGeneration,
            phase: "reconciling" as const,
          },
        }),
        lastAccessed: new Date(),
      };
      if (discardsFailedStart) discardedStart = updatedSession;
      const newSessions = new Map(state.sessions);
      newSessions.set(sessionId, updatedSession);
      return { sessions: newSessions };
    });
    // A lost start response can hide an accepted turn. Reconcile before dispatch.
    if (discardedStart)
      void reconcileCompletedTranscript(sessionId, discardedStart);
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

  loadSession: async (sessionId: string, options?: { force?: boolean }) => {
    const { updateSessionData, sessions } = get();

    // Check if already loaded in cache
    const existingSession = sessions.get(sessionId);
    if (canReuseSession(existingSession) && options?.force !== true) {
      if (
        existingSession?.sandbox?.status === "running" &&
        existingSession.status !== "running"
      )
        void get().refreshOutputInventory(sessionId, { silent: true });
      return;
    }

    // Load metadata without changing the active session.
    if (!get().sessions.has(sessionId)) get().createSession(sessionId);
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
        current.turnSettlement === loadingSession.turnSettlement &&
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
      try {
        activeTurn = await fetchActiveTurn(sessionId);
      } catch (err) {
        console.warn("Failed to fetch active turn:", err);
      }
      if (!isCurrentRuntimeLoad()) return;
      // Server completion follows the final transcript commit. Observe it before reading messages.
      let messages: BuildMessage[] = await fetchMessages(sessionId);
      if (!isCurrentRuntimeLoad()) return;
      const historyTurnId = activeTurn?.turn_id;
      try {
        // A second tab can start while history loads. Keep the first owner if it completed during the read.
        activeTurn = (await fetchActiveTurn(sessionId)) ?? activeTurn;
      } catch (err) {
        console.warn("Failed to recheck active turn:", err);
      }
      if (!isCurrentRuntimeLoad()) return;
      if (activeTurn && activeTurn.turn_id !== historyTurnId) {
        // The new turn may have committed its prompt after our history read.
        messages = await fetchMessages(sessionId);
        if (!isCurrentRuntimeLoad()) return;
      }

      // Preserve optimistic messages if actively streaming (pre-provisioned flow).
      const currentSession: BuildSessionData | undefined =
        get().sessions.get(sessionId);
      const currentSessionIsLive: boolean =
        currentSession?.status === "running" ||
        currentSession?.status === "creating";
      const isStreaming: boolean =
        currentSessionIsLive && (currentSession?.messages.length ?? 0) > 0;
      const keepCompletedTranscript =
        currentSession?.turnSettlement != null &&
        currentSession.turnSettlement.phase !== "ready";
      const useDbMessages = !keepCompletedTranscript && !isStreaming;

      const resolvedActiveTurnId: string | null = keepCompletedTranscript
        ? currentSession!.activeTurnId
        : (activeTurn?.turn_id ??
          (useDbMessages ? null : currentSession!.activeTurnId));
      const resolvedActiveTurnIndex: number | null = keepCompletedTranscript
        ? currentSession!.activeTurnIndex
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
      if (isCurrentLoad())
        updateSessionData(sessionId, {
          status,
          messages: resolvedMessages,
          streamItems,
          subagents,
          activeTurnId: resolvedActiveTurnId,
          turnSettlement: currentSession!.turnSettlement,
          activeTurnIndex: resolvedActiveTurnIndex,
          activeTurnLocalOwner: useDbMessages
            ? false
            : currentSession!.activeTurnLocalOwner,
          contextUsage: useDbMessages
            ? deriveContextUsage(messages)
            : currentSession!.contextUsage,
        });

      const [runtimeResult] = await runtimeRequest;
      if (!isCurrentRuntimeLoad()) return;
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
          !isCurrentLoad() ||
          isStreaming ||
          keepCompletedTranscript ||
          runtimeSession.status !== status ||
          runtimeSession.activeTurnId !== resolvedActiveTurnId ||
          runtimeSession.turnSettlement !== currentSession!.turnSettlement
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
        ...(runtimeSession.agentProvider === loadingSession.agentProvider &&
          runtimeSession.agentModel === loadingSession.agentModel && {
            agentProvider: sessionData.agent_provider,
            agentModel: sessionData.agent_model,
          }),
        isLoaded: true,
        loadError: null,
        ...(canApplySkillsStale() && { skillsStale: sessionData.skills_stale }),
        origin: sessionData.origin,
      });
      if (!needsRestore) {
        if (
          get().sessions.get(sessionId)?.outputInventory === null ||
          runtimeSession.status !== "running"
        )
          void get().refreshOutputInventory(sessionId, { silent: true });
        const artifacts: Artifact[] = await fetchArtifacts(sessionId);
        if (!isCurrentRuntimeLoad()) return;
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
      }

      if (needsRestore) {
        outputInventoryRequests.get(sessionId)?.controller.abort();
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

        updateSessionData(sessionId, {
          ...(isCurrentLoad() && {
            status: mapApiSessionStatus(sessionData.status),
          }),
          sandbox: sessionData.sandbox,
          ...(get().sessions.get(sessionId)?.skillsStaleRevision ===
            skillsStaleRevisionBeforeRestore && {
            skillsStale: sessionData.skills_stale,
          }),
          filesNeedsRefresh:
            (get().sessions.get(sessionId)?.filesNeedsRefresh ?? 0) + 1,
          webappNeedsRefresh:
            (get().sessions.get(sessionId)?.webappNeedsRefresh ?? 0) + 1,
        });
        void get().refreshOutputInventory(sessionId, { silent: true });

        // App readiness controls iframe replacement, not restored filesystem access.
        void waitForWebappReady(sessionId).then(() => {
          const current = get().sessions.get(sessionId);
          if (
            current?.instanceId !== loadingSession.instanceId ||
            current.sandbox?.id !== sessionData.sandbox?.id
          )
            return;
          updateSessionData(sessionId, {
            webappNeedsRemount:
              (get().sessions.get(sessionId)?.webappNeedsRemount ?? 0) + 1,
          });
        });

        // An artifact-fetch failure must NOT flip the sandbox to "failed".
        try {
          if (!isCurrentRuntimeLoad()) return;
          const restoredArtifacts: Artifact[] = await fetchArtifacts(sessionId);
          if (!isCurrentRuntimeLoad()) return;
          updateSessionData(sessionId, { artifacts: restoredArtifacts });
        } catch (artifactsErr) {
          console.warn(
            "Failed to fetch artifacts after restore:",
            artifactsErr
          );
        }
      }
    } catch (err) {
      if (!isCurrentRuntimeLoad()) return;
      console.error("Failed to load session:", err);
      updateSessionData(sessionId, {
        loadError: err instanceof Error ? err.message : String(err),
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
    const { abortSession, refreshSessionHistory } = get();

    try {
      await apiDeleteSession(sessionId);
      abortSession(sessionId);
      clearOutputPanelPreferences(sessionId);

      // Remove session from local state
      set((state) => {
        const newSessions = new Map(state.sessions);
        newSessions.delete(sessionId);
        return {
          sessions: newSessions,
          sessionHistory: state.sessionHistory.filter(
            (historyItem) => historyItem.id !== sessionId
          ),
        };
      });

      if (get().currentSessionId === sessionId) get().setCurrentSession(null);
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
      get().updateSessionData(sessionId, {
        webappNeedsRefresh: (session.webappNeedsRefresh || 0) + 1,
      });
      void get().maybeAutoOpenWebapp(sessionId);
    }
  },

  triggerFilesRefresh: (sessionId: string) => {
    const session = get().sessions.get(sessionId);
    if (session) {
      get().updateSessionData(sessionId, {
        filesNeedsRefresh: session.filesNeedsRefresh + 1,
      });
      // Streaming owns discovery during a task; idle writes only validate metadata.
      if (
        !session.activeTurnId &&
        session.status !== "running" &&
        session.status !== "creating"
      ) {
        // A write needs a read started after the mutation.
        const previousRead = outputInventoryRequests.get(sessionId);
        if (previousRead) previousRead.coalescible = false;
        void get().refreshOutputInventory(sessionId, { silent: true });
      }
    }
  },

  // ===========================================================================
  // Output Inventory
  // ===========================================================================

  refreshOutputInventory: async (
    sessionId,
    { silent = false, signal } = {}
  ) => {
    const started: BuildSessionData | undefined = get().sessions.get(sessionId);
    if (!started || signal?.aborted) return;
    const matchesRuntime = (session: BuildSessionData): boolean =>
      sameSessionRuntime(session, started);
    const previousRequest = outputInventoryRequests.get(sessionId);
    const sameRuntime =
      previousRequest &&
      !previousRequest.controller.signal.aborted &&
      sameSessionRuntime(previousRequest.session, started);
    if (previousRequest && !sameRuntime) previousRequest.controller.abort();
    const runtimeController =
      sameRuntime && previousRequest
        ? previousRequest.controller
        : new AbortController();
    const coalescible = silent && signal === undefined;
    if (
      coalescible &&
      sameRuntime &&
      previousRequest?.coalescible &&
      previousRequest.session.activeTurnId === started.activeTurnId &&
      matchesRuntime(previousRequest.session) &&
      previousRequest.session.turnGeneration === started.turnGeneration
    ) {
      await previousRequest.promise;
      return;
    }
    const requestSignal = signal
      ? AbortSignal.any([signal, runtimeController.signal])
      : runtimeController.signal;
    const isCurrent = (): boolean => {
      const current = get().sessions.get(sessionId);
      if (requestSignal.aborted || !current || !matchesRuntime(current))
        return false;
      // Passive reads cannot consume files from a newly attached turn.
      if (silent)
        return (
          current.turnGeneration === started.turnGeneration &&
          current.activeTurnId === started.activeTurnId
        );
      return true;
    };
    const ownsTurn = (session: BuildSessionData): boolean =>
      session.turnGeneration === started.turnGeneration &&
      (!session.activeTurnId ||
        !started.activeTurnId ||
        session.activeTurnId === started.activeTurnId);
    const readInventory = async (): Promise<void> => {
      if (!isCurrent()) return;
      for (let attempt = 0; attempt < 3; attempt++) {
        const current = get().sessions.get(sessionId);
        if (!isCurrent() || !current || (attempt > 0 && !ownsTurn(current)))
          return;
        const controller = new AbortController();
        const abort = (): void => controller.abort();
        // Allow the backend's 30-second RPC deadline plus HTTP overhead.
        const timeout = setTimeout(abort, 35000);
        try {
          const inventory = await fetchOutputInventory(
            sessionId,
            AbortSignal.any([controller.signal, requestSignal])
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
            outputInventoryError: undefined,
            outputBaselinePending:
              (session.outputBaselinePending || previous === null) &&
              !inventory.complete,
            filesNeedsRefresh:
              session.filesNeedsRefresh +
              (previous !== null && (added.length > 0 || changed.length > 0)
                ? 1
                : 0),
          };
          if (
            previous !== null &&
            !session.outputBaselinePending &&
            !silent &&
            ownsTurn(session)
          ) {
            const newTabs: PanelTab[] = added
              .filter((file) => outputPreviewPriority(file.path) < 4)
              .sort(
                (a, b) =>
                  outputPreviewPriority(a.path) -
                    outputPreviewPriority(b.path) ||
                  a.path.localeCompare(b.path)
              )
              .map((file) => ({
                kind: "file",
                path: file.path,
                fileName: file.path.split("/").pop() || file.path,
              }));
            const existingIds = new Set(session.panelTabs.map(panelTabId));
            updates.panelTabs = [
              ...session.panelTabs,
              ...newTabs.filter((tab) => !existingIds.has(panelTabId(tab))),
            ];
            const target = newTabs[0];
            if (target)
              Object.assign(
                updates,
                automaticallySelectOutput(
                  { ...session, panelTabs: updates.panelTabs },
                  target
                )
              );
          }
          get().updateSessionData(sessionId, updates);
          return;
        } catch (error) {
          const current = get().sessions.get(sessionId);
          if (!isCurrent() || !current || !ownsTurn(current)) return;
          const terminal = isAuthStatusError(error) || isNotFoundError(error);
          if (terminal || attempt === 2) {
            get().updateSessionData(sessionId, {
              outputInventoryStatus: "error",
              outputInventoryError:
                error instanceof Error ? error : new Error(String(error)),
              ...(terminal && {
                outputInventory: null,
                outputBaselinePending: true,
              }),
            });
            console.warn(
              "[Streaming] Failed to refresh output inventory:",
              error
            );
            return;
          }
        } finally {
          clearTimeout(timeout);
        }
        if (attempt < 2) {
          await new Promise<void>((resolve) =>
            setTimeout(resolve, 1000 * (attempt + 1))
          );
        }
      }
    };

    // Loading belongs to the request queue; accepted completeness stays intact.
    get().updateSessionData(sessionId, { outputInventoryLoading: true });
    // Focus and panel reads must not consume files before pending turn discovery.
    const request =
      sameRuntime && previousRequest
        ? previousRequest.promise.then(readInventory)
        : readInventory();
    const queued: OutputInventoryRequest = {
      controller: runtimeController,
      promise: request,
      session: started,
      coalescible,
    };
    outputInventoryRequests.set(sessionId, queued);
    try {
      await request;
    } finally {
      if (outputInventoryRequests.get(sessionId) === queued) {
        outputInventoryRequests.delete(sessionId);
        if (get().sessions.get(sessionId)?.instanceId === started.instanceId)
          get().updateSessionData(sessionId, { outputInventoryLoading: false });
      }
    }
  },

  maybeAutoOpenWebapp: async (sessionId) => {
    const started = get().sessions.get(sessionId);
    if (!started || !canAutomaticallySelectOutput(started)) return;
    const matchesRuntime = (session: BuildSessionData) =>
      sameSessionRuntime(session, started) &&
      session.turnGeneration === started.turnGeneration &&
      session.webappNeedsRemount === started.webappNeedsRemount;
    const existing = webappAutoOpenRequests.get(sessionId);
    if (existing && matchesRuntime(existing.session)) return existing.promise;
    const request = (async () => {
      if (!(await waitForWebappReady(sessionId))) return;
      const session = get().sessions.get(sessionId);
      if (
        !session ||
        !matchesRuntime(session) ||
        !canAutomaticallySelectOutput(session)
      )
        return;
      const target: PanelTab = session.panelTabs.find(
        (tab) => tab.kind === "browser" && tab.appId === sessionId
      ) ?? { kind: "browser", id: genId("browser"), appId: sessionId };
      get().updateSessionData(
        sessionId,
        automaticallySelectOutput(session, target)
      );
    })();
    const entry = { session: started, promise: request };
    webappAutoOpenRequests.set(sessionId, entry);
    try {
      await request;
    } finally {
      if (webappAutoOpenRequests.get(sessionId) === entry)
        webappAutoOpenRequests.delete(sessionId);
    }
  },

  openFilePreview: (sessionId, path, fileName) => {
    if (!sessionId) {
      const state = get();
      const tab: PanelTab = {
        kind: "file",
        path: normalizePanelPath(path),
        fileName,
      };
      set({
        ...selectWelcomeOutputTarget(state, tab),
        noSessionOutputPanelInitialized: true,
        noSessionOutputPanelMode:
          state.noSessionOutputPanelMode === "closed"
            ? "medium"
            : state.noSessionOutputPanelMode,
      });
      return;
    }
    const session = get().sessions.get(sessionId);
    if (!session) return;
    get().updateSessionData(sessionId, {
      outputPanelInitialized: true,
      outputSelectionLocked: true,
      ...selectOutputTarget(session, {
        kind: "file",
        path: normalizePanelPath(path),
        fileName,
      }),
      outputPanelMode:
        session.outputPanelMode === "closed"
          ? "medium"
          : session.outputPanelMode,
    });
  },

  openOutputsTab: (sessionId, turnIndex = null) => {
    if (sessionId)
      get().updateSessionData(sessionId, {
        outputsTabState: {
          turnIndex,
          searchQuery: "",
          folder: "",
          fileType: "all",
        },
      });
    openCollectionTab(sessionId, "outputs");
  },

  openFilesTab: (sessionId) => openCollectionTab(sessionId, "files"),

  updateOutputsTabState: (sessionId, updates) => {
    const session = get().sessions.get(sessionId);
    if (session)
      get().updateSessionData(sessionId, {
        outputsTabState: { ...session.outputsTabState, ...updates },
      });
  },

  openBrowserTab: (sessionId, appId, appName) => {
    const state = get();
    const session = sessionId ? state.sessions.get(sessionId) : undefined;
    if (sessionId && !session) return;
    const tabs = session?.panelTabs ?? state.noSessionPanelTabs;
    const existing = appId
      ? tabs.find((tab) => tab.kind === "browser" && tab.appId === appId)
      : undefined;
    const tab: PanelTab = existing ?? {
      kind: "browser",
      id: genId("browser"),
      appId: appId ?? null,
      appName,
    };
    if (session && sessionId)
      state.updateSessionData(sessionId, {
        outputPanelInitialized: true,
        outputSelectionLocked: true,
        ...selectOutputTarget(session, tab),
        outputPanelMode:
          session.outputPanelMode === "closed"
            ? "medium"
            : session.outputPanelMode,
      });
    else
      set({
        noSessionOutputPanelInitialized: true,
        ...selectWelcomeOutputTarget(state, tab),
        noSessionOutputPanelMode:
          state.noSessionOutputPanelMode === "closed"
            ? "medium"
            : state.noSessionOutputPanelMode,
      });
  },

  navigateBrowserTab: (sessionId, tabId, appId, appName) => {
    const state = get();
    const tabs = sessionId
      ? state.sessions.get(sessionId)?.panelTabs
      : state.noSessionPanelTabs;
    if (!tabs) return;
    const panelTabs = tabs.map((tab) =>
      panelTabId(tab) === tabId && tab.kind === "browser"
        ? { ...tab, appId, appName }
        : tab
    );
    if (sessionId)
      state.updateSessionData(sessionId, {
        panelTabs,
        outputSelectionLocked: true,
      });
    else set({ noSessionPanelTabs: panelTabs });
  },

  reorderPanelTab: (sessionId, tabId, index) => {
    const state = get();
    const tabs = sessionId
      ? state.sessions.get(sessionId)?.panelTabs
      : state.noSessionPanelTabs;
    if (!tabs) return;
    const tab = tabs.find((item) => panelTabId(item) === tabId);
    if (!tab) return;
    const panelTabs = tabs.filter((item) => panelTabId(item) !== tabId);
    panelTabs.splice(Math.max(0, Math.min(panelTabs.length, index)), 0, tab);
    if (sessionId)
      state.updateSessionData(sessionId, {
        panelTabs,
        outputSelectionLocked: true,
      });
    else set({ noSessionPanelTabs: panelTabs });
  },

  closePanelTab: (sessionId, tabId) => {
    const state = get();
    const session = sessionId ? state.sessions.get(sessionId) : undefined;
    if (sessionId && !session) return;
    const tabs = session?.panelTabs ?? state.noSessionPanelTabs;
    const index = tabs.findIndex((tab) => panelTabId(tab) === tabId);
    if (index < 0) return;
    const panelTabs = tabs.filter((tab) => panelTabId(tab) !== tabId);
    const active = session
      ? session.activePanelTabId
      : state.noSessionActivePanelTabId;
    const history = panelTabHistory(
      panelTabs,
      null,
      session?.panelTabHistory ?? state.noSessionPanelTabHistory
    );
    const neighbor = panelTabs[Math.max(0, index - 1)];
    const activePanelTabId =
      active === tabId
        ? (history[0] ?? (neighbor ? panelTabId(neighbor) : null))
        : active;
    const nextHistory = panelTabHistory(panelTabs, activePanelTabId, history);
    if (sessionId)
      state.updateSessionData(sessionId, {
        panelTabs,
        activePanelTabId,
        panelTabHistory: nextHistory,
        outputSelectionLocked: true,
      });
    else
      set({
        noSessionPanelTabs: panelTabs,
        noSessionActivePanelTabId: activePanelTabId,
        noSessionPanelTabHistory: nextHistory,
      });
  },

  setActivePanelTabId: (sessionId, tabId) => {
    if (!sessionId) {
      if (
        tabId === null ||
        get().noSessionPanelTabs.some((tab) => panelTabId(tab) === tabId)
      )
        set((state) => ({
          noSessionActivePanelTabId: tabId,
          noSessionPanelTabHistory: panelTabHistory(
            state.noSessionPanelTabs,
            tabId,
            state.noSessionPanelTabHistory
          ),
        }));
      return;
    }
    const session = get().sessions.get(sessionId);
    if (!session) return;
    const tab = session.panelTabs.find(
      (candidate) => panelTabId(candidate) === tabId
    );
    if (tabId !== null && !tab) return;
    get().updateSessionData(sessionId, {
      outputSelectionLocked: true,
      ...(tab ? selectOutputTarget(session, tab) : { activePanelTabId: null }),
    });
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
    text: string,
    part?: TextPartUpdate
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
      const streamItems = appendStreamingChunk(
        last.streamItems,
        "text",
        text,
        part
      );
      turns[turns.length - 1] = {
        ...last,
        response: part
          ? streamItems
              .filter((item) => item.type === "text")
              .map((item) => (item.type === "text" ? item.content : ""))
              .join("")
          : (last.response ?? "") + text,
        streamItems,
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
    text: string,
    part?: TextPartUpdate
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
      const streamItems = appendStreamingChunk(
        last.streamItems,
        "thinking",
        text,
        part
      );
      turns[turns.length - 1] = {
        ...last,
        thinking: part
          ? streamItems
              .filter((item) => item.type === "thinking")
              .map((item) => (item.type === "thinking" ? item.content : ""))
              .join("")
          : (last.thinking ?? "") + text,
        streamItems,
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
}));

// =============================================================================
// Selector Hooks (mirrors chat's pattern)
// =============================================================================

// Stable empty references for SSR hydration (prevents infinite loop)
const EMPTY_PANEL_TABS: PanelTab[] = [];
const EMPTY_FILES_TAB_STATE: FilesTabState = {
  expandedPaths: ["outputs"],
  scrollTop: 0,
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

type ChatSessionData = Pick<
  BuildSessionData,
  | "origin"
  | "status"
  | "agentProvider"
  | "agentModel"
  | "contextUsage"
  | "activeTurnId"
  | "activeTurnLocalOwner"
  | "error"
  | "loadError"
  | "turnSettlement"
  | "isLoaded"
  | "messages"
  | "streamItems"
  | "webappNeedsRefresh"
  | "skillsStale"
>;

/** Output controls do not invalidate the chat transcript subscription. */
export const useChatSession = (): ChatSessionData | null =>
  useBuildSessionStore(
    useShallow((state) => {
      const session = state.currentSessionId
        ? state.sessions.get(state.currentSessionId)
        : undefined;
      if (!session) return null;
      const {
        origin,
        status,
        agentProvider,
        agentModel,
        contextUsage,
        activeTurnId,
        activeTurnLocalOwner,
        error,
        loadError,
        turnSettlement,
        isLoaded,
        messages,
        streamItems,
        webappNeedsRefresh,
        skillsStale,
      } = session;
      return {
        origin,
        status,
        agentProvider,
        agentModel,
        contextUsage,
        activeTurnId,
        activeTurnLocalOwner,
        error,
        loadError,
        turnSettlement,
        isLoaded,
        messages,
        streamItems,
        webappNeedsRefresh,
        skillsStale,
      };
    })
  );

function openCollectionTab(
  sessionId: string | null,
  kind: "outputs" | "files"
): void {
  const state = useBuildSessionStore.getState();
  if (sessionId) {
    const session = state.sessions.get(sessionId);
    if (!session) return;
    state.updateSessionData(sessionId, {
      outputPanelInitialized: true,
      outputSelectionLocked: true,
      ...selectOutputTarget(session, { kind }),
      outputPanelMode:
        session.outputPanelMode === "closed"
          ? "medium"
          : session.outputPanelMode,
    });
  } else {
    useBuildSessionStore.setState({
      noSessionOutputPanelInitialized: true,
      noSessionOutputPanelMode:
        state.noSessionOutputPanelMode === "closed"
          ? "medium"
          : state.noSessionOutputPanelMode,
      ...selectWelcomeOutputTarget(state, { kind }),
    });
  }
}

type OutputSessionData = Pick<
  BuildSessionData,
  | "sandbox"
  | "status"
  | "webappNeedsRefresh"
  | "outputInventory"
  | "outputInventoryStatus"
  | "outputInventoryLoading"
  | "filePreviewRefreshKeys"
  | "webappNeedsRemount"
>;

export const useOutputSession = (): OutputSessionData | null =>
  useBuildSessionStore(
    useShallow((state) => {
      const session = state.currentSessionId
        ? state.sessions.get(state.currentSessionId)
        : undefined;
      if (!session) return null;
      const {
        sandbox,
        status,
        webappNeedsRefresh,
        outputInventory,
        outputInventoryStatus,
        outputInventoryLoading,
        filePreviewRefreshKeys,
        webappNeedsRemount,
      } = session;
      return {
        sandbox,
        status,
        webappNeedsRefresh,
        outputInventory,
        outputInventoryStatus,
        outputInventoryLoading,
        filePreviewRefreshKeys,
        webappNeedsRemount,
      };
    })
  );

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

// Panel tab selectors
export const usePanelTabs = () =>
  useBuildSessionStore((state) => {
    const { currentSessionId, sessions } = state;
    if (!currentSessionId) return state.noSessionPanelTabs;
    return sessions.get(currentSessionId)?.panelTabs ?? EMPTY_PANEL_TABS;
  });

export const useActivePanelTabId = () =>
  useBuildSessionStore((state) => {
    const { currentSessionId, sessions } = state;
    if (!currentSessionId) return state.noSessionActivePanelTabId;
    return sessions.get(currentSessionId)?.activePanelTabId ?? null;
  });

export const useFilesTabState = (sessionId: string | null) =>
  useBuildSessionStore((state) => {
    if (!sessionId) return EMPTY_FILES_TAB_STATE;
    return (
      state.sessions.get(sessionId)?.filesTabState ?? EMPTY_FILES_TAB_STATE
    );
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

export const useOutputPanelMode = () =>
  useBuildSessionStore((state) =>
    state.currentSessionId
      ? (state.sessions.get(state.currentSessionId)?.outputPanelMode ??
        "closed")
      : state.noSessionOutputPanelMode
  );

export const useMediumPanelProportion = () =>
  useBuildSessionStore((state) =>
    state.currentSessionId
      ? (state.sessions.get(state.currentSessionId)?.mediumPanelProportion ??
        0.5)
      : state.noSessionMediumPanelProportion
  );

export const useOutputWorkspaceId = () =>
  useBuildSessionStore((state) =>
    state.currentSessionId
      ? (state.sessions.get(state.currentSessionId)?.outputWorkspaceId ??
        state.currentSessionId)
      : state.noSessionOutputWorkspaceId
  );
