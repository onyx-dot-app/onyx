"use client";

import { create } from "zustand";
import Cookies from "js-cookie";
import { BUILD_DEMO_DATA_COOKIE_NAME } from "@/app/build/v1/constants";
import {
  getBuildUserPersona,
  getBuildLlmSelection,
} from "@/app/build/onboarding/constants";
import { DELETE_SUCCESS_DISPLAY_DURATION_MS } from "@/app/build/constants";

import {
  ApiSandboxResponse,
  Artifact,
  ArtifactType,
  BuildMessage,
  Session,
  SessionHistoryItem,
  SessionStatus,
  ToolCall,
  ToolCallStatus,
} from "@/app/build/types/streamingTypes";

import {
  StreamItem,
  ToolCallState,
  TodoListState,
} from "@/app/build/types/displayTypes";

import {
  createSession as apiCreateSession,
  fetchSession,
  fetchSessionHistory,
  generateSessionName,
  updateSessionName,
  deleteSession as apiDeleteSession,
  fetchMessages,
  fetchArtifacts,
  restoreSession,
} from "@/app/build/services/apiServices";

import { genId } from "@/app/build/utils/streamItemHelpers";
import { parsePacket } from "@/app/build/utils/parsePacket";

/**
 * Convert loaded messages (with message_metadata) to StreamItem[] format.
 *
 * The backend stores messages with these packet types in message_metadata:
 * - user_message: {type: "user_message", content: {type: "text", text: "..."}}
 * - agent_message: {type: "agent_message", content: {type: "text", text: "..."}}
 * - agent_thought: {type: "agent_thought", content: {type: "text", text: "..."}}
 * - tool_call_progress: Full tool call data with status="completed"
 * - agent_plan_update: Plan entries (not rendered as stream items)
 *
 * This function converts assistant messages to StreamItem[] for rendering.
 */
function convertMessagesToStreamItems(messages: BuildMessage[]): StreamItem[] {
  const items: StreamItem[] = [];

  for (const message of messages) {
    if (message.type === "user") continue;

    const metadata = message.message_metadata;
    if (!metadata || typeof metadata !== "object") continue;

    // SAME parsePacket — identical classification for both code paths
    const packet = parsePacket(metadata);

    switch (packet.type) {
      case "text_chunk":
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
              title: packet.title,
              description: packet.description,
              command: packet.command,
              status: packet.status,
              rawOutput: packet.rawOutput,
              subagentType: packet.subagentType ?? undefined,
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
 * Consolidate raw backend messages into proper conversation turns.
 *
 * The backend stores each streaming packet as a separate message. This function:
 * 1. Groups consecutive assistant messages (between user messages) into turns
 * 2. Converts each group's packets to streamItems
 * 3. Creates consolidated messages with streamItems in message_metadata
 *
 * Returns: Array of consolidated messages (user messages + one assistant message per turn)
 */
function consolidateMessagesIntoTurns(
  rawMessages: BuildMessage[]
): BuildMessage[] {
  const consolidated: BuildMessage[] = [];
  let currentAssistantPackets: BuildMessage[] = [];

  for (const message of rawMessages) {
    if (message.type === "user") {
      // If we have accumulated assistant packets, consolidate them into one message
      if (currentAssistantPackets.length > 0) {
        const streamItems = convertMessagesToStreamItems(
          currentAssistantPackets
        );
        const textContent = streamItems
          .filter((item) => item.type === "text")
          .map((item) => item.content)
          .join("");

        consolidated.push({
          id: currentAssistantPackets[0]?.id || genId("assistant-msg"),
          type: "assistant",
          content: textContent,
          timestamp: currentAssistantPackets[0]?.timestamp || new Date(),
          message_metadata: {
            streamItems,
          },
        });
        currentAssistantPackets = [];
      }
      // Add the user message as-is
      consolidated.push(message);
    } else if (message.type === "assistant") {
      // Check if this message already has consolidated streamItems (from new format)
      if (message.message_metadata?.streamItems) {
        // Already consolidated, add as-is
        if (currentAssistantPackets.length > 0) {
          // Flush any pending packets first
          const streamItems = convertMessagesToStreamItems(
            currentAssistantPackets
          );
          const textContent = streamItems
            .filter((item) => item.type === "text")
            .map((item) => item.content)
            .join("");

          consolidated.push({
            id: currentAssistantPackets[0]?.id || genId("assistant-msg"),
            type: "assistant",
            content: textContent,
            timestamp: currentAssistantPackets[0]?.timestamp || new Date(),
            message_metadata: {
              streamItems,
            },
          });
          currentAssistantPackets = [];
        }
        consolidated.push(message);
      } else {
        // Old format - accumulate for consolidation
        currentAssistantPackets.push(message);
      }
    }
  }

  // Don't forget any trailing assistant packets
  if (currentAssistantPackets.length > 0) {
    const streamItems = convertMessagesToStreamItems(currentAssistantPackets);
    const textContent = streamItems
      .filter((item) => item.type === "text")
      .map((item) => item.content)
      .join("");

    consolidated.push({
      id: currentAssistantPackets[0]?.id || genId("assistant-msg"),
      type: "assistant",
      content: textContent,
      timestamp: currentAssistantPackets[0]?.timestamp || new Date(),
      message_metadata: {
        streamItems,
      },
    });
  }

  return consolidated;
}

// Re-export types for consumers
export type {
  Artifact,
  ArtifactType,
  BuildMessage,
  Session,
  SessionHistoryItem,
  SessionStatus,
  ToolCall,
  ToolCallStatus,
};

// =============================================================================
// Store Types (mirrors chat's useChatSessionStore pattern)
// =============================================================================

/** Pre-provisioning state machine - exactly one of these states at a time */
export type PreProvisioningState =
  | { status: "idle" }
  | {
      status: "provisioning";
      promise: Promise<string | null>;
      demoDataEnabled: boolean;
    }
  | { status: "ready"; sessionId: string; demoDataEnabled: boolean }
  | { status: "failed"; error: string };

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

/** Tab history entry - can be a pinned tab or a file preview */
export type TabHistoryEntry =
  | { type: "pinned"; tab: OutputTabType }
  | { type: "file"; path: string };

/** Browser-style tab navigation history */
export interface TabNavigationHistory {
  entries: TabHistoryEntry[];
  currentIndex: number;
}

/** Follow-up suggestion bubble */
export interface SuggestionBubble {
  theme: "add" | "question";
  text: string;
}

/** Output panel tab types */
export type OutputTabType = "preview" | "files" | "artifacts";

export interface BuildSessionData {
  id: string;
  status: SessionStatus;
  messages: BuildMessage[];
  artifacts: Artifact[];
  /** Active tool calls for the current response */
  toolCalls: ToolCall[];
  /**
   * FIFO stream items for the current assistant turn.
   * Items are stored in chronological order as they arrive.
   * Rendered directly without transformation.
   */
  streamItems: StreamItem[];
  error: string | null;
  webappUrl: string | null;
  /** Sandbox info from backend */
  sandbox: ApiSandboxResponse | null;
  abortController: AbortController;
  lastAccessed: Date;
  isLoaded: boolean;
  outputPanelOpen: boolean;
  /** Counter to trigger webapp refresh when web/ files change (increments on each edit) */
  webappNeedsRefresh: number;
  /** Counter to trigger files list refresh when outputs/ directory changes (increments on each write/edit) */
  filesNeedsRefresh: number;
  /** File preview tabs open in this session */
  filePreviewTabs: FilePreviewTab[];
  /** Active pinned tab in output panel */
  activeOutputTab: OutputTabType;
  /** Active file preview path (when set, this is the active tab instead of pinned tab) */
  activeFilePreviewPath: string | null;
  /** Files tab state - expanded folders and scroll position */
  filesTabState: FilesTabState;
  /** Browser-style tab navigation history for back/forward */
  tabHistory: TabNavigationHistory;
  /** Follow-up suggestions after first assistant message */
  followupSuggestions: SuggestionBubble[] | null;
  /** Whether suggestions are currently being generated */
  suggestionsLoading: boolean;
}

interface BuildSessionStore {
  // Session management (mirrors chat)
  currentSessionId: string | null;
  sessions: Map<string, BuildSessionData>;
  sessionHistory: SessionHistoryItem[];

  // Pre-provisioning state (discriminated union - see PreProvisioningState type)
  preProvisioning: PreProvisioningState;

  // Demo data toggle (controls whether demo files are mounted in sandbox)
  demoDataEnabled: boolean;

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
  setCurrentSessionStatus: (status: SessionStatus) => void;
  appendMessageToCurrent: (message: BuildMessage) => void;
  updateLastMessageInCurrent: (content: string) => void;
  addArtifactToCurrent: (artifact: Artifact) => void;
  setCurrentError: (error: string | null) => void;
  setCurrentOutputPanelOpen: (open: boolean) => void;
  toggleCurrentOutputPanel: () => void;

  // Actions - Session-specific operations (for streaming - immune to currentSessionId changes)
  appendMessageToSession: (sessionId: string, message: BuildMessage) => void;
  updateLastMessageInSession: (sessionId: string, content: string) => void;
  updateMessageByIdInSession: (
    sessionId: string,
    messageId: string,
    content: string
  ) => void;
  addArtifactToSession: (sessionId: string, artifact: Artifact) => void;

  // Actions - Tool Call Management
  addToolCallToSession: (sessionId: string, toolCall: ToolCall) => void;
  updateToolCallInSession: (
    sessionId: string,
    toolCallId: string,
    updates: Partial<ToolCall>
  ) => void;
  clearToolCallsInSession: (sessionId: string) => void;

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
  updateTodoListStreamItem: (
    sessionId: string,
    todoListId: string,
    updates: Partial<TodoListState>
  ) => void;
  upsertTodoListStreamItem: (
    sessionId: string,
    todoListId: string,
    todoList: TodoListState
  ) => void;
  clearStreamItems: (sessionId: string) => void;

  // Actions - Abort Control
  setAbortController: (sessionId: string, controller: AbortController) => void;
  abortSession: (sessionId: string) => void;
  abortCurrentSession: () => void;

  // Actions - Session Lifecycle
  createNewSession: (prompt: string) => Promise<string | null>;
  loadSession: (sessionId: string) => Promise<void>;

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
  /** Clear and delete any pre-provisioned session (used when settings change) */
  clearPreProvisionedSession: () => Promise<void>;

  // Demo Data Actions
  setDemoDataEnabled: (enabled: boolean) => void;

  // Webapp Refresh Actions
  triggerWebappRefresh: (sessionId: string) => void;
  // Files Refresh Actions
  triggerFilesRefresh: (sessionId: string) => void;

  // File Preview Actions
  openFilePreview: (sessionId: string, path: string, fileName: string) => void;
  /** Atomically open panel + create file tab + set active for a markdown file detected during streaming */
  openMarkdownPreview: (sessionId: string, filePath: string) => void;
  closeFilePreview: (sessionId: string, path: string) => void;
  setActiveOutputTab: (sessionId: string, tab: OutputTabType) => void;
  setActiveFilePreviewPath: (sessionId: string, path: string | null) => void;
  /** Set active tab when no session exists (for pre-provisioned sandbox viewing) */
  setNoSessionActiveOutputTab: (tab: OutputTabType) => void;

  // Files Tab State Actions
  updateFilesTabState: (
    sessionId: string,
    updates: Partial<FilesTabState>
  ) => void;

  // Tab Navigation History Actions
  navigateTabBack: (sessionId: string) => void;
  navigateTabForward: (sessionId: string) => void;

  // Follow-up Suggestion Actions
  setFollowupSuggestions: (
    sessionId: string,
    suggestions: SuggestionBubble[] | null
  ) => void;
  setSuggestionsLoading: (sessionId: string, loading: boolean) => void;
  clearFollowupSuggestions: (sessionId: string) => void;
}

// =============================================================================
// Cookie Helpers
// =============================================================================

/**
 * Read initial demoDataEnabled value from cookie.
 * Defaults to true if cookie doesn't exist or is invalid.
 */
function getInitialDemoDataEnabled(): boolean {
  if (typeof window === "undefined") return true; // SSR fallback
  const cookieValue = Cookies.get(BUILD_DEMO_DATA_COOKIE_NAME);
  if (cookieValue === "false") return false;
  return true; // Default to true
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
  toolCalls: [],
  streamItems: [],
  error: null,
  webappUrl: null,
  sandbox: null,
  abortController: new AbortController(),
  lastAccessed: new Date(),
  isLoaded: false,
  outputPanelOpen: false,
  webappNeedsRefresh: 0,
  filesNeedsRefresh: 0,
  filePreviewTabs: [],
  activeOutputTab: "preview",
  activeFilePreviewPath: null,
  filesTabState: { expandedPaths: [], scrollTop: 0, directoryCache: {} },
  tabHistory: {
    entries: [{ type: "pinned", tab: "preview" }],
    currentIndex: 0,
  },
  followupSuggestions: null,
  suggestionsLoading: false,
  ...initialData,
});

// =============================================================================
// Store
// =============================================================================

export const useBuildSessionStore = create<BuildSessionStore>()((set, get) => ({
  currentSessionId: null,
  sessions: new Map<string, BuildSessionData>(),
  sessionHistory: [],

  // Pre-provisioning state
  preProvisioning: { status: "idle" },

  // Demo data toggle (persisted to cookie, defaults to true)
  demoDataEnabled: getInitialDemoDataEnabled(),

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

  setCurrentSessionStatus: (status: SessionStatus) => {
    const { currentSessionId, updateSessionData } = get();
    if (currentSessionId) {
      updateSessionData(currentSessionId, { status });
    }
  },

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

  updateLastMessageInCurrent: (content: string) => {
    const { currentSessionId } = get();
    if (!currentSessionId) return;

    set((state) => {
      const session = state.sessions.get(currentSessionId);
      if (!session || session.messages.length === 0) return state;

      const messages = session.messages.map((msg, idx) =>
        idx === session.messages.length - 1 ? { ...msg, content } : msg
      );
      const updatedSession: BuildSessionData = {
        ...session,
        messages,
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

  setCurrentOutputPanelOpen: (open: boolean) => {
    const { currentSessionId, updateSessionData } = get();
    if (currentSessionId) {
      updateSessionData(currentSessionId, { outputPanelOpen: open });
    } else {
      // No session - update temporary state
      set({ noSessionOutputPanelOpen: open });
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
        updateSessionData(currentSessionId, {
          outputPanelOpen: !session.outputPanelOpen,
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

  updateLastMessageInSession: (sessionId: string, content: string) => {
    set((state) => {
      const session = state.sessions.get(sessionId);
      if (!session || session.messages.length === 0) return state;

      const messages = session.messages.map((msg, idx) =>
        idx === session.messages.length - 1 ? { ...msg, content } : msg
      );
      const updatedSession: BuildSessionData = {
        ...session,
        messages,
        lastAccessed: new Date(),
      };
      const newSessions = new Map(state.sessions);
      newSessions.set(sessionId, updatedSession);
      return { sessions: newSessions };
    });
  },

  updateMessageByIdInSession: (
    sessionId: string,
    messageId: string,
    content: string
  ) => {
    set((state) => {
      const session = state.sessions.get(sessionId);
      if (!session) return state;

      const messages = session.messages.map((msg) =>
        msg.id === messageId ? { ...msg, content } : msg
      );
      const updatedSession: BuildSessionData = {
        ...session,
        messages,
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
  // Tool Call Management
  // ===========================================================================

  addToolCallToSession: (sessionId: string, toolCall: ToolCall) => {
    set((state) => {
      const session = state.sessions.get(sessionId);
      if (!session) return state;

      const updatedSession: BuildSessionData = {
        ...session,
        toolCalls: [...session.toolCalls, toolCall],
        lastAccessed: new Date(),
      };
      const newSessions = new Map(state.sessions);
      newSessions.set(sessionId, updatedSession);
      return { sessions: newSessions };
    });
  },

  updateToolCallInSession: (
    sessionId: string,
    toolCallId: string,
    updates: Partial<ToolCall>
  ) => {
    set((state) => {
      const session = state.sessions.get(sessionId);
      if (!session) return state;

      const toolCalls = session.toolCalls.map((tc) =>
        tc.id === toolCallId ? { ...tc, ...updates } : tc
      );
      const updatedSession: BuildSessionData = {
        ...session,
        toolCalls,
        lastAccessed: new Date(),
      };
      const newSessions = new Map(state.sessions);
      newSessions.set(sessionId, updatedSession);
      return { sessions: newSessions };
    });
  },

  clearToolCallsInSession: (sessionId: string) => {
    set((state) => {
      const session = state.sessions.get(sessionId);
      if (!session) return state;

      const updatedSession: BuildSessionData = {
        ...session,
        toolCalls: [],
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

  updateTodoListStreamItem: (
    sessionId: string,
    todoListId: string,
    updates: Partial<TodoListState>
  ) => {
    set((state) => {
      const session = state.sessions.get(sessionId);
      if (!session) return state;

      const streamItems = session.streamItems.map((item) => {
        if (item.type === "todo_list" && item.todoList.id === todoListId) {
          return {
            ...item,
            todoList: { ...item.todoList, ...updates },
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

  createNewSession: async (prompt: string) => {
    const {
      setCurrentSession,
      updateSessionData,
      refreshSessionHistory,
      nameBuildSession,
      demoDataEnabled,
    } = get();

    // Create a temporary session ID for optimistic UI
    const tempId = `temp-${Date.now()}`;
    setCurrentSession(tempId);
    updateSessionData(tempId, { status: "creating" });

    try {
      // Get LLM selection from cookie
      const llmSelection = getBuildLlmSelection();
      const sessionData = await apiCreateSession({
        name: prompt.slice(0, 50),
        demoDataEnabled,
        llmProviderType: llmSelection?.provider || null,
        llmModelName: llmSelection?.modelName || null,
      });
      const realSessionId = sessionData.id;

      // Remove temp session and create real one
      set((state) => {
        const newSessions = new Map(state.sessions);
        newSessions.delete(tempId);
        newSessions.set(
          realSessionId,
          createInitialSessionData(realSessionId, {
            status: "idle",
            messages: [
              {
                id: `msg-${Date.now()}`,
                type: "user",
                content: prompt,
                timestamp: new Date(),
              },
            ],
            isLoaded: true,
            // Inherit output panel state from no-session state
            outputPanelOpen: state.noSessionOutputPanelOpen,
          })
        );
        return {
          currentSessionId: realSessionId,
          sessions: newSessions,
        };
      });

      // Auto-name the session after a short delay
      setTimeout(() => {
        nameBuildSession(realSessionId);
      }, 200);

      await refreshSessionHistory();
      return realSessionId;
    } catch (err) {
      console.error("Failed to create session:", err);
      updateSessionData(tempId, {
        status: "failed",
        error: (err as Error).message,
      });
      return null;
    }
  },

  loadSession: async (sessionId: string) => {
    const { setCurrentSession, updateSessionData, sessions } = get();

    // Check if already loaded in cache
    const existingSession = sessions.get(sessionId);
    if (existingSession?.isLoaded) {
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
        console.log(`Restoring session ${sessionId}...`);
        // Update UI to show restoring state
        updateSessionData(sessionId, {
          status: "creating", // Use "creating" to show loading indicator
        });

        // Call restore endpoint (blocks until complete)
        sessionData = await restoreSession(sessionId);
        console.log(`Session ${sessionId} restored successfully`);
      }

      // Now fetch messages and artifacts
      const [messages, artifacts] = await Promise.all([
        fetchMessages(sessionId),
        fetchArtifacts(sessionId),
      ]);

      // Construct webapp URL if sandbox has a Next.js port and there's a webapp artifact
      let webappUrl: string | null = null;
      const hasWebapp = artifacts.some(
        (a) => a.type === "nextjs_app" || a.type === "web_app"
      );
      if (hasWebapp && sessionData.sandbox?.nextjs_port) {
        webappUrl = `http://localhost:${sessionData.sandbox.nextjs_port}`;
      }

      // Re-fetch existing session to check for optimistic messages
      const currentSession = get().sessions.get(sessionId);
      const hasOptimisticMessages = (currentSession?.messages.length ?? 0) > 0;
      const isCurrentlyStreaming =
        currentSession?.status === "running" ||
        currentSession?.status === "creating";

      // Consolidate messages into proper conversation turns
      // Each assistant turn becomes a single message with streamItems in metadata
      // If there are optimistic messages (active streaming), preserve current state
      const messagesToUse = hasOptimisticMessages
        ? currentSession!.messages
        : consolidateMessagesIntoTurns(messages);
      // Session-level streamItems are only for current streaming response
      // When loading from history, they should be empty (each message has its own streamItems)
      const streamItemsToUse = hasOptimisticMessages
        ? currentSession!.streamItems
        : [];
      // Preserve streaming status if currently streaming, otherwise use backend status
      const statusToUse = isCurrentlyStreaming
        ? currentSession!.status
        : sessionData.status === "active"
          ? "completed"
          : "idle";

      updateSessionData(sessionId, {
        status: statusToUse,
        // Preserve optimistic messages if they exist (e.g., from pre-provisioned flow)
        messages: messagesToUse,
        streamItems: streamItemsToUse,
        artifacts,
        webappUrl,
        sandbox: sessionData.sandbox,
        error: null,
        isLoaded: true,
      });
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
    const { preProvisioning, demoDataEnabled } = get();

    // Already have a pre-provisioned session ready with matching demoDataEnabled
    if (preProvisioning.status === "ready") {
      // If demoDataEnabled changed, we need to re-provision (handled by setDemoDataEnabled)
      return preProvisioning.sessionId;
    }

    // Already provisioning - return existing promise
    if (preProvisioning.status === "provisioning") {
      return preProvisioning.promise;
    }

    // Start new provisioning with current demoDataEnabled value
    const promise = (async (): Promise<string | null> => {
      try {
        // Parse user persona and LLM selection from cookies
        const persona = getBuildUserPersona();
        const llmSelection = getBuildLlmSelection();

        const sessionData = await apiCreateSession({
          demoDataEnabled,
          userWorkArea: persona?.workArea || null,
          userLevel: persona?.level || null,
          llmProviderType: llmSelection?.provider || null,
          llmModelName: llmSelection?.modelName || null,
        });
        set({
          preProvisioning: {
            status: "ready",
            sessionId: sessionData.id,
            demoDataEnabled,
          },
        });
        return sessionData.id;
      } catch (err) {
        console.error("[PreProvision] Failed to pre-provision session:", err);
        const errorMessage =
          err instanceof Error ? err.message : "Unknown error";
        set({
          preProvisioning: {
            status: "failed",
            error: errorMessage,
          },
        });
        return null;
      }
    })();

    set({
      preProvisioning: { status: "provisioning", promise, demoDataEnabled },
    });
    return promise;
  },

  consumePreProvisionedSession: async () => {
    const { preProvisioning } = get();

    // Wait for provisioning to complete if in progress
    if (preProvisioning.status === "provisioning") {
      await preProvisioning.promise;
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

  clearPreProvisionedSession: async () => {
    const { preProvisioning } = get();

    // If provisioning is in progress, wait for it to complete
    if (preProvisioning.status === "provisioning") {
      await preProvisioning.promise;
    }

    // Re-check state after awaiting
    const { preProvisioning: currentState } = get();

    if (currentState.status === "ready") {
      const { sessionId } = currentState;

      // Reset to idle first
      set({ preProvisioning: { status: "idle" } });

      // Delete the session and wait for completion
      try {
        await apiDeleteSession(sessionId);
      } catch (err) {
        console.error(
          "[PreProvision] Failed to delete pre-provisioned session:",
          err
        );
      }
    } else {
      // Just reset to idle if not ready
      set({ preProvisioning: { status: "idle" } });
    }
  },

  // ===========================================================================
  // Demo Data Actions
  // ===========================================================================

  setDemoDataEnabled: (enabled: boolean) => {
    const {
      preProvisioning,
      demoDataEnabled: currentValue,
      ensurePreProvisionedSession,
    } = get();

    // If value hasn't changed, do nothing
    if (enabled === currentValue) {
      return;
    }

    // Update the state value and persist to cookie
    set({ demoDataEnabled: enabled });
    Cookies.set(BUILD_DEMO_DATA_COOKIE_NAME, String(enabled), {
      path: "/",
      expires: 365, // 1 year
    });

    // Check if we need to invalidate a pre-provisioned session
    if (preProvisioning.status === "ready") {
      // Pre-provisioned session exists with different demoDataEnabled value
      if (preProvisioning.demoDataEnabled !== enabled) {
        const sessionIdToDelete = preProvisioning.sessionId;

        // Reset to idle first
        set({ preProvisioning: { status: "idle" } });

        // Delete the old session in the background (don't await)
        apiDeleteSession(sessionIdToDelete).catch((err) => {
          console.error(
            "[PreProvision] Failed to delete invalidated session:",
            err
          );
        });

        // Start new pre-provisioning with updated demoDataEnabled
        ensurePreProvisionedSession();
      }
    } else if (preProvisioning.status === "provisioning") {
      // If currently provisioning with different value, the new session will have wrong demoDataEnabled
      // We'll let it complete but mark it for replacement
      if (preProvisioning.demoDataEnabled !== enabled) {
        // Wait for current provisioning to complete, then invalidate
        preProvisioning.promise.then((sessionId) => {
          if (sessionId) {
            // Check if demoDataEnabled is still different (user may have toggled back)
            const { demoDataEnabled: latestValue } = get();
            if (latestValue !== preProvisioning.demoDataEnabled) {
              // Delete the session and re-provision
              set({ preProvisioning: { status: "idle" } });
              apiDeleteSession(sessionId).catch((err) => {
                console.error(
                  "[PreProvision] Failed to delete invalidated session:",
                  err
                );
              });
              get().ensurePreProvisionedSession();
            }
          }
        });
      }
    }
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
      get().updateSessionData(sessionId, {
        filesNeedsRefresh: (session.filesNeedsRefresh || 0) + 1,
      });
    }
  },

  // ===========================================================================
  // File Preview Actions
  // ===========================================================================

  openFilePreview: (sessionId: string, path: string, fileName: string) => {
    set((state) => {
      const session = state.sessions.get(sessionId);
      if (!session) return state;

      // Check if tab already exists
      const existingTab = session.filePreviewTabs.find(
        (tab) => tab.path === path
      );

      let filePreviewTabs = session.filePreviewTabs;
      if (!existingTab) {
        // Add new tab
        filePreviewTabs = [...session.filePreviewTabs, { path, fileName }];
      }

      // Push to history (truncate forward history if navigating from middle)
      const { tabHistory } = session;
      const newEntry: TabHistoryEntry = { type: "file", path };
      const newEntries = [
        ...tabHistory.entries.slice(0, tabHistory.currentIndex + 1),
        newEntry,
      ];

      const updatedSession: BuildSessionData = {
        ...session,
        filePreviewTabs,
        activeFilePreviewPath: path, // Always switch to this tab
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

      const existingTab = session.filePreviewTabs.find(
        (t) => t.path === filePath
      );
      let filePreviewTabs = session.filePreviewTabs;
      if (!existingTab) {
        filePreviewTabs = [
          ...session.filePreviewTabs,
          { path: filePath, fileName },
        ];
      }

      // Push to history (truncate forward history if navigating from middle)
      const { tabHistory } = session;
      const newEntry: TabHistoryEntry = { type: "file", path: filePath };
      const newEntries = [
        ...tabHistory.entries.slice(0, tabHistory.currentIndex + 1),
        newEntry,
      ];

      const updatedSession: BuildSessionData = {
        ...session,
        outputPanelOpen: true,
        filePreviewTabs,
        activeFilePreviewPath: filePath,
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

      // Remove the tab
      const filePreviewTabs = session.filePreviewTabs.filter(
        (tab) => tab.path !== path
      );

      // If closing the active preview tab, switch to Files tab
      const activeFilePreviewPath =
        session.activeFilePreviewPath === path
          ? null
          : session.activeFilePreviewPath;

      // If we closed the active tab, set activeOutputTab to "files"
      const activeOutputTab =
        session.activeFilePreviewPath === path
          ? "files"
          : session.activeOutputTab;

      const updatedSession: BuildSessionData = {
        ...session,
        filePreviewTabs,
        activeFilePreviewPath,
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
        activeFilePreviewPath: null, // Clear file preview when selecting pinned tab
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

  setActiveFilePreviewPath: (sessionId: string, path: string | null) => {
    set((state) => {
      const session = state.sessions.get(sessionId);
      if (!session) return state;

      // Push to history if switching to a file (truncate forward history)
      const { tabHistory } = session;
      let newTabHistory = tabHistory;
      if (path !== null) {
        const newEntry: TabHistoryEntry = { type: "file", path };
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
        activeFilePreviewPath: path,
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

      // Re-open file tab if it was closed
      let filePreviewTabs = session.filePreviewTabs;
      if (entry.type === "file") {
        const tabExists = filePreviewTabs.some(
          (tab) => tab.path === entry.path
        );
        if (!tabExists) {
          // Extract filename from path
          const fileName = entry.path.split("/").pop() || entry.path;
          filePreviewTabs = [
            ...filePreviewTabs,
            { path: entry.path, fileName },
          ];
        }
      }

      const updatedSession: BuildSessionData = {
        ...session,
        tabHistory: { ...tabHistory, currentIndex: newIndex },
        activeOutputTab:
          entry.type === "pinned" ? entry.tab : session.activeOutputTab,
        activeFilePreviewPath: entry.type === "file" ? entry.path : null,
        filePreviewTabs,
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

      // Re-open file tab if it was closed
      let filePreviewTabs = session.filePreviewTabs;
      if (entry.type === "file") {
        const tabExists = filePreviewTabs.some(
          (tab) => tab.path === entry.path
        );
        if (!tabExists) {
          // Extract filename from path
          const fileName = entry.path.split("/").pop() || entry.path;
          filePreviewTabs = [
            ...filePreviewTabs,
            { path: entry.path, fileName },
          ];
        }
      }

      const updatedSession: BuildSessionData = {
        ...session,
        tabHistory: { ...tabHistory, currentIndex: newIndex },
        activeOutputTab:
          entry.type === "pinned" ? entry.tab : session.activeOutputTab,
        activeFilePreviewPath: entry.type === "file" ? entry.path : null,
        filePreviewTabs,
        lastAccessed: new Date(),
      };
      const newSessions = new Map(state.sessions);
      newSessions.set(sessionId, updatedSession);
      return { sessions: newSessions };
    });
  },

  // ===========================================================================
  // Follow-up Suggestion Actions
  // ===========================================================================

  setFollowupSuggestions: (
    sessionId: string,
    suggestions: SuggestionBubble[] | null
  ) => {
    set((state) => {
      const session = state.sessions.get(sessionId);
      if (!session) return state;

      const updatedSession: BuildSessionData = {
        ...session,
        followupSuggestions: suggestions,
        suggestionsLoading: false,
        lastAccessed: new Date(),
      };
      const newSessions = new Map(state.sessions);
      newSessions.set(sessionId, updatedSession);
      return { sessions: newSessions };
    });
  },

  setSuggestionsLoading: (sessionId: string, loading: boolean) => {
    set((state) => {
      const session = state.sessions.get(sessionId);
      if (!session) return state;

      const updatedSession: BuildSessionData = {
        ...session,
        suggestionsLoading: loading,
        lastAccessed: new Date(),
      };
      const newSessions = new Map(state.sessions);
      newSessions.set(sessionId, updatedSession);
      return { sessions: newSessions };
    });
  },

  clearFollowupSuggestions: (sessionId: string) => {
    set((state) => {
      const session = state.sessions.get(sessionId);
      if (!session) return state;

      const updatedSession: BuildSessionData = {
        ...session,
        followupSuggestions: null,
        suggestionsLoading: false,
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
const EMPTY_ARRAY: never[] = [];
const EMPTY_FILE_PREVIEW_TABS: FilePreviewTab[] = [];
const EMPTY_FILES_TAB_STATE: FilesTabState = {
  expandedPaths: [],
  scrollTop: 0,
  directoryCache: {},
};
const EMPTY_TAB_HISTORY: TabNavigationHistory = {
  entries: [],
  currentIndex: 0,
};

export const useCurrentSession = () =>
  useBuildSessionStore((state) => {
    const { currentSessionId, sessions } = state;
    return currentSessionId ? sessions.get(currentSessionId) : null;
  });

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

export const useMessages = () =>
  useBuildSessionStore((state) => {
    const { currentSessionId, sessions } = state;
    if (!currentSessionId) return EMPTY_ARRAY;
    return sessions.get(currentSessionId)?.messages ?? EMPTY_ARRAY;
  });

export const useArtifacts = () =>
  useBuildSessionStore((state) => {
    const { currentSessionId, sessions } = state;
    if (!currentSessionId) return EMPTY_ARRAY;
    return sessions.get(currentSessionId)?.artifacts ?? EMPTY_ARRAY;
  });

export const useToolCalls = () =>
  useBuildSessionStore((state) => {
    const { currentSessionId, sessions } = state;
    if (!currentSessionId) return EMPTY_ARRAY;
    return sessions.get(currentSessionId)?.toolCalls ?? EMPTY_ARRAY;
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

// Demo data selectors
export const useDemoDataEnabled = () =>
  useBuildSessionStore((state) => state.demoDataEnabled);

export const useSetDemoDataEnabled = () =>
  useBuildSessionStore((state) => state.setDemoDataEnabled);

// Stream items selector
export const useStreamItems = () =>
  useBuildSessionStore((state) => {
    const { currentSessionId, sessions } = state;
    if (!currentSessionId) return EMPTY_ARRAY;
    return sessions.get(currentSessionId)?.streamItems ?? EMPTY_ARRAY;
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

// File preview selectors
export const useFilePreviewTabs = () =>
  useBuildSessionStore((state) => {
    const { currentSessionId, sessions } = state;
    if (!currentSessionId) return EMPTY_FILE_PREVIEW_TABS;
    return (
      sessions.get(currentSessionId)?.filePreviewTabs ?? EMPTY_FILE_PREVIEW_TABS
    );
  });

export const useActiveOutputTab = () =>
  useBuildSessionStore((state) => {
    const { currentSessionId, sessions, noSessionActiveOutputTab } = state;
    if (!currentSessionId) return noSessionActiveOutputTab;
    return sessions.get(currentSessionId)?.activeOutputTab ?? "preview";
  });

export const useActiveFilePreviewPath = () =>
  useBuildSessionStore((state) => {
    const { currentSessionId, sessions } = state;
    if (!currentSessionId) return null;
    return sessions.get(currentSessionId)?.activeFilePreviewPath ?? null;
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

// Follow-up suggestion selectors
export const useFollowupSuggestions = () =>
  useBuildSessionStore((state) => {
    const { currentSessionId, sessions } = state;
    if (!currentSessionId) return null;
    return sessions.get(currentSessionId)?.followupSuggestions ?? null;
  });

export const useSuggestionsLoading = () =>
  useBuildSessionStore((state) => {
    const { currentSessionId, sessions } = state;
    if (!currentSessionId) return false;
    return sessions.get(currentSessionId)?.suggestionsLoading ?? false;
  });
