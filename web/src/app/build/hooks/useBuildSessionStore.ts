"use client";

import { create } from "zustand";

import {
  Artifact,
  ArtifactType,
  BuildMessage,
  Session,
  SessionHistoryItem,
  SessionStatus,
  ToolCall,
  ToolCallStatus,
} from "@/app/build/services/buildStreamingModels";

import {
  createSession as apiCreateSession,
  fetchSession,
  fetchSessionHistory,
  generateSessionName,
  updateSessionName,
  deleteSession as apiDeleteSession,
  fetchMessages,
  fetchArtifacts,
} from "@/app/build/services/apiServices";

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

export interface BuildSessionData {
  id: string;
  status: SessionStatus;
  messages: BuildMessage[];
  artifacts: Artifact[];
  /** Active tool calls for the current response */
  toolCalls: ToolCall[];
  error: string | null;
  webappUrl: string | null;
  abortController: AbortController;
  lastAccessed: Date;
  isLoaded: boolean;
  outputPanelOpen: boolean;
}

interface BuildSessionStore {
  // Session management (mirrors chat)
  currentSessionId: string | null;
  sessions: Map<string, BuildSessionData>;
  sessionHistory: SessionHistoryItem[];

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
  addArtifactToSession: (sessionId: string, artifact: Artifact) => void;

  // Actions - Tool Call Management
  addToolCallToSession: (sessionId: string, toolCall: ToolCall) => void;
  updateToolCallInSession: (
    sessionId: string,
    toolCallId: string,
    updates: Partial<ToolCall>
  ) => void;
  clearToolCallsInSession: (sessionId: string) => void;

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
  error: null,
  webappUrl: null,
  abortController: new AbortController(),
  lastAccessed: new Date(),
  isLoaded: false,
  outputPanelOpen: false,
  ...initialData,
});

// =============================================================================
// Store
// =============================================================================

export const useBuildSessionStore = create<BuildSessionStore>()((set, get) => ({
  currentSessionId: null,
  sessions: new Map<string, BuildSessionData>(),
  sessionHistory: [],

  // ===========================================================================
  // Session Management (mirrors chat's pattern)
  // ===========================================================================

  setCurrentSession: (sessionId: string | null) => {
    set((state) => {
      // If setting to null, just clear current session
      if (sessionId === null) {
        return { currentSessionId: null };
      }

      // If session doesn't exist, create it
      if (!state.sessions.has(sessionId)) {
        const newSession = createInitialSessionData(sessionId);
        const newSessions = new Map(state.sessions);
        newSessions.set(sessionId, newSession);
        return {
          currentSessionId: sessionId,
          sessions: newSessions,
        };
      }

      // Update last accessed for existing session
      const session = state.sessions.get(sessionId)!;
      const updatedSession = { ...session, lastAccessed: new Date() };
      const newSessions = new Map(state.sessions);
      newSessions.set(sessionId, updatedSession);

      return {
        currentSessionId: sessionId,
        sessions: newSessions,
      };
    });
  },

  createSession: (
    sessionId: string,
    initialData?: Partial<BuildSessionData>
  ) => {
    set((state) => {
      const newSession = createInitialSessionData(sessionId, initialData);
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
    }
  },

  toggleCurrentOutputPanel: () => {
    const { currentSessionId, sessions, updateSessionData } = get();
    if (currentSessionId) {
      const session = sessions.get(currentSessionId);
      if (session) {
        updateSessionData(currentSessionId, {
          outputPanelOpen: !session.outputPanelOpen,
        });
      }
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
    } = get();

    // Create a temporary session ID for optimistic UI
    const tempId = `temp-${Date.now()}`;
    setCurrentSession(tempId);
    updateSessionData(tempId, { status: "creating" });

    try {
      const sessionData = await apiCreateSession(prompt.slice(0, 50));
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
      const [sessionData, messages, artifacts] = await Promise.all([
        fetchSession(sessionId),
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

      updateSessionData(sessionId, {
        status: sessionData.status === "active" ? "completed" : "idle",
        messages,
        artifacts,
        webappUrl,
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
      // Update session with the generated name
      await updateSessionName(sessionId, generatedName);
      await get().refreshSessionHistory();
    } catch (err) {
      console.error("Failed to auto-name session:", err);
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
      // Abort any ongoing requests for this session
      abortSession(sessionId);

      // Call the API to delete the session
      await apiDeleteSession(sessionId);

      // Remove session from local state
      set((state) => {
        const newSessions = new Map(state.sessions);
        newSessions.delete(sessionId);

        return {
          sessions: newSessions,
          // Clear current session if it's the one being deleted
          currentSessionId:
            currentSessionId === sessionId ? null : state.currentSessionId,
        };
      });

      // Refresh session history to reflect the deletion
      await refreshSessionHistory();
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
}));

// =============================================================================
// Selector Hooks (mirrors chat's pattern)
// =============================================================================

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
    if (!currentSessionId) return [];
    return sessions.get(currentSessionId)?.messages ?? [];
  });

export const useArtifacts = () =>
  useBuildSessionStore((state) => {
    const { currentSessionId, sessions } = state;
    if (!currentSessionId) return [];
    return sessions.get(currentSessionId)?.artifacts ?? [];
  });

export const useToolCalls = () =>
  useBuildSessionStore((state) => {
    const { currentSessionId, sessions } = state;
    if (!currentSessionId) return [];
    return sessions.get(currentSessionId)?.toolCalls ?? [];
  });

export const useSessionHistory = () =>
  useBuildSessionStore((state) => state.sessionHistory);

/**
 * Returns the output panel open state for the current session.
 * Returns false when no session exists (welcome page).
 */
export const useOutputPanelOpen = () =>
  useBuildSessionStore((state) => {
    const { currentSessionId, sessions } = state;
    if (!currentSessionId) return false;
    return sessions.get(currentSessionId)?.outputPanelOpen ?? false;
  });

export const useToggleOutputPanel = () =>
  useBuildSessionStore((state) => state.toggleCurrentOutputPanel);
