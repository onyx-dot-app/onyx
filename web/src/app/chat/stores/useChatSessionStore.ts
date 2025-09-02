import { create } from "zustand";
import {
  ChatState,
  RegenerationState,
  Message,
  ChatSessionSharedStatus,
  BackendChatSession,
} from "../interfaces";
import {
  getLatestMessageChain,
  MessageTreeState,
} from "../services/messageTree";
import { useMemo } from "react";

interface ChatSessionData {
  sessionId: string;
  messageTree: MessageTreeState;
  chatState: ChatState;
  regenerationState: RegenerationState | null;
  canContinue: boolean;
  submittedMessage: string;
  maxTokens: number;
  chatSessionSharedStatus: ChatSessionSharedStatus;
  selectedNodeIdForDocDisplay: number | null; // should be the node ID, not the message ID
  abortController: AbortController;
  hasPerformedInitialScroll: boolean;
  documentSidebarVisible: boolean;
  hasSentLocalUserMessage: boolean;

  // Session-specific state (previously global)
  isFetchingChatMessages: boolean;
  uncaughtError: string | null;
  loadingError: string | null;
  isReady: boolean;

  // Session metadata
  lastAccessed: Date;
  isLoaded: boolean;
  description?: string;
  personaId?: number;
}

interface ChatSessionStore {
  // Session management
  currentSessionId: string | null;
  sessions: Map<string, ChatSessionData>;

  // Actions - Session Management
  setCurrentSession: (sessionId: string | null) => void;
  createSession: (
    sessionId: string,
    initialData?: Partial<ChatSessionData>
  ) => void;
  updateSessionData: (
    sessionId: string,
    updates: Partial<ChatSessionData>
  ) => void;
  updateSessionMessageTree: (
    sessionId: string,
    messageTree: MessageTreeState
  ) => void;
  updateSessionAndMessageTree: (
    sessionId: string,
    messageTree: MessageTreeState
  ) => void;

  // Actions - Message Management
  updateChatState: (sessionId: string, chatState: ChatState) => void;
  updateRegenerationState: (
    sessionId: string,
    state: RegenerationState | null
  ) => void;
  updateCanContinue: (sessionId: string, canContinue: boolean) => void;
  updateSubmittedMessage: (sessionId: string, message: string) => void;
  updateSelectedNodeForDocDisplay: (
    sessionId: string,
    selectedMessageForDocDisplay: number | null
  ) => void;
  updateHasPerformedInitialScroll: (
    sessionId: string,
    hasPerformedInitialScroll: boolean
  ) => void;
  updateDocumentSidebarVisible: (
    sessionId: string,
    documentSidebarVisible: boolean
  ) => void;
  updateCurrentDocumentSidebarVisible: (
    documentSidebarVisible: boolean
  ) => void;
  updateHasSentLocalUserMessage: (
    sessionId: string,
    hasSentLocalUserMessage: boolean
  ) => void;
  updateCurrentHasSentLocalUserMessage: (
    hasSentLocalUserMessage: boolean
  ) => void;

  // Convenience functions that automatically use current session ID
  updateCurrentSelectedNodeForDocDisplay: (
    selectedNodeForDocDisplay: number | null
  ) => void;
  updateCurrentChatSessionSharedStatus: (
    chatSessionSharedStatus: ChatSessionSharedStatus
  ) => void;
  updateCurrentChatState: (chatState: ChatState) => void;
  updateCurrentRegenerationState: (
    regenerationState: RegenerationState | null
  ) => void;
  updateCurrentCanContinue: (canContinue: boolean) => void;
  updateCurrentSubmittedMessage: (submittedMessage: string) => void;

  // Actions - Session-specific State (previously global)
  setIsFetchingChatMessages: (sessionId: string, fetching: boolean) => void;
  setUncaughtError: (sessionId: string, error: string | null) => void;
  setLoadingError: (sessionId: string, error: string | null) => void;
  setIsReady: (sessionId: string, ready: boolean) => void;

  // Actions - Abort Controllers
  setAbortController: (sessionId: string, controller: AbortController) => void;
  abortSession: (sessionId: string) => void;
  abortAllSessions: () => void;

  // Utilities
  initializeSession: (
    sessionId: string,
    backendSession?: BackendChatSession
  ) => void;
  cleanupOldSessions: (maxSessions?: number) => void;
}

const createInitialSessionData = (
  sessionId: string,
  initialData?: Partial<ChatSessionData>
): ChatSessionData => ({
  sessionId,
  messageTree: new Map<number, Message>(),
  chatState: "input" as ChatState,
  regenerationState: null,
  canContinue: false,
  submittedMessage: "",
  maxTokens: 128_000,
  chatSessionSharedStatus: ChatSessionSharedStatus.Private,
  selectedNodeIdForDocDisplay: null,
  abortController: new AbortController(),
  hasPerformedInitialScroll: true,
  documentSidebarVisible: false,
  hasSentLocalUserMessage: false,

  // Session-specific state defaults
  isFetchingChatMessages: false,
  uncaughtError: null,
  loadingError: null,
  isReady: true,

  lastAccessed: new Date(),
  isLoaded: false,
  ...initialData,
});

export const useChatSessionStore = create<ChatSessionStore>()((set, get) => ({
  // Initial state
  currentSessionId: null,
  sessions: new Map<string, ChatSessionData>(),

  // Session Management Actions
  setCurrentSession: (sessionId: string | null) => {
    set((state) => {
      if (sessionId && !state.sessions.has(sessionId)) {
        // Create new session if it doesn't exist
        const newSession = createInitialSessionData(sessionId);
        const newSessions = new Map(state.sessions);
        newSessions.set(sessionId, newSession);

        return {
          currentSessionId: sessionId,
          sessions: newSessions,
        };
      }

      // Update last accessed for the new current session
      if (sessionId && state.sessions.has(sessionId)) {
        const session = state.sessions.get(sessionId)!;
        const updatedSession = { ...session, lastAccessed: new Date() };
        const newSessions = new Map(state.sessions);
        newSessions.set(sessionId, updatedSession);

        return {
          currentSessionId: sessionId,
          sessions: newSessions,
        };
      }

      return { currentSessionId: sessionId };
    });
  },

  createSession: (
    sessionId: string,
    initialData?: Partial<ChatSessionData>
  ) => {
    set((state) => {
      const newSession = createInitialSessionData(sessionId, initialData);
      const newSessions = new Map(state.sessions);
      newSessions.set(sessionId, newSession);

      return { sessions: newSessions };
    });
  },

  updateSessionData: (sessionId: string, updates: Partial<ChatSessionData>) => {
    set((state) => {
      const session = state.sessions.get(sessionId);
      const updatedSession = {
        ...(session || createInitialSessionData(sessionId)),
        ...updates,
        lastAccessed: new Date(),
      };
      const newSessions = new Map(state.sessions);
      newSessions.set(sessionId, updatedSession);

      return { sessions: newSessions };
    });
  },

  updateSessionMessageTree: (
    sessionId: string,
    messageTree: MessageTreeState
  ) => {
    get().updateSessionData(sessionId, { messageTree });
  },

  updateSessionAndMessageTree: (
    sessionId: string,
    messageTree: MessageTreeState
  ) => {
    set((state) => {
      // Ensure session exists
      const existingSession = state.sessions.get(sessionId);
      const session = existingSession || createInitialSessionData(sessionId);

      // Update session with new message tree
      const updatedSession = {
        ...session,
        messageTree,
        lastAccessed: new Date(),
      };

      const newSessions = new Map(state.sessions);
      newSessions.set(sessionId, updatedSession);

      // Return both updates in a single state change
      return {
        currentSessionId: sessionId,
        sessions: newSessions,
      };
    });
  },

  // Message Management Actions
  updateChatState: (sessionId: string, chatState: ChatState) => {
    get().updateSessionData(sessionId, { chatState });
  },

  updateRegenerationState: (
    sessionId: string,
    regenerationState: RegenerationState | null
  ) => {
    get().updateSessionData(sessionId, { regenerationState });
  },

  updateCanContinue: (sessionId: string, canContinue: boolean) => {
    get().updateSessionData(sessionId, { canContinue });
  },

  updateSubmittedMessage: (sessionId: string, submittedMessage: string) => {
    get().updateSessionData(sessionId, { submittedMessage });
  },

  updateSelectedNodeForDocDisplay: (
    sessionId: string,
    selectedMessageForDocDisplay: number | null
  ) => {
    get().updateSessionData(sessionId, {
      selectedNodeIdForDocDisplay: selectedMessageForDocDisplay,
    });
  },

  updateHasPerformedInitialScroll: (
    sessionId: string,
    hasPerformedInitialScroll: boolean
  ) => {
    get().updateSessionData(sessionId, { hasPerformedInitialScroll });
  },

  updateDocumentSidebarVisible: (
    sessionId: string,
    documentSidebarVisible: boolean
  ) => {
    get().updateSessionData(sessionId, { documentSidebarVisible });
  },

  updateCurrentDocumentSidebarVisible: (documentSidebarVisible: boolean) => {
    const { currentSessionId } = get();
    if (currentSessionId) {
      get().updateDocumentSidebarVisible(
        currentSessionId,
        documentSidebarVisible
      );
    }
  },

  updateHasSentLocalUserMessage: (
    sessionId: string,
    hasSentLocalUserMessage: boolean
  ) => {
    get().updateSessionData(sessionId, { hasSentLocalUserMessage });
  },

  updateCurrentHasSentLocalUserMessage: (hasSentLocalUserMessage: boolean) => {
    const { currentSessionId } = get();
    if (currentSessionId) {
      get().updateHasSentLocalUserMessage(
        currentSessionId,
        hasSentLocalUserMessage
      );
    }
  },

  // Convenience functions that automatically use current session ID
  updateCurrentSelectedNodeForDocDisplay: (
    selectedNodeForDocDisplay: number | null
  ) => {
    const { currentSessionId } = get();
    if (currentSessionId) {
      get().updateSelectedNodeForDocDisplay(
        currentSessionId,
        selectedNodeForDocDisplay
      );
    }
  },

  updateCurrentChatSessionSharedStatus: (
    chatSessionSharedStatus: ChatSessionSharedStatus
  ) => {
    const { currentSessionId } = get();
    if (currentSessionId) {
      get().updateSessionData(currentSessionId, { chatSessionSharedStatus });
    }
  },

  updateCurrentChatState: (chatState: ChatState) => {
    const { currentSessionId } = get();
    if (currentSessionId) {
      get().updateChatState(currentSessionId, chatState);
    }
  },

  updateCurrentRegenerationState: (
    regenerationState: RegenerationState | null
  ) => {
    const { currentSessionId } = get();
    if (currentSessionId) {
      get().updateRegenerationState(currentSessionId, regenerationState);
    }
  },

  updateCurrentCanContinue: (canContinue: boolean) => {
    const { currentSessionId } = get();
    if (currentSessionId) {
      get().updateCanContinue(currentSessionId, canContinue);
    }
  },

  updateCurrentSubmittedMessage: (submittedMessage: string) => {
    const { currentSessionId } = get();
    if (currentSessionId) {
      get().updateSubmittedMessage(currentSessionId, submittedMessage);
    }
  },

  // Session-specific State Actions (previously global)
  setIsFetchingChatMessages: (
    sessionId: string,
    isFetchingChatMessages: boolean
  ) => {
    get().updateSessionData(sessionId, { isFetchingChatMessages });
  },

  setUncaughtError: (sessionId: string, uncaughtError: string | null) => {
    get().updateSessionData(sessionId, { uncaughtError });
  },

  setLoadingError: (sessionId: string, loadingError: string | null) => {
    get().updateSessionData(sessionId, { loadingError });
  },

  setIsReady: (sessionId: string, isReady: boolean) => {
    get().updateSessionData(sessionId, { isReady });
  },

  // Abort Controller Actions
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

  abortAllSessions: () => {
    const { sessions } = get();
    sessions.forEach((session, sessionId) => {
      if (session.abortController) {
        session.abortController.abort();
        get().updateSessionData(sessionId, {
          abortController: new AbortController(),
        });
      }
    });
  },

  // Utilities
  initializeSession: (
    sessionId: string,
    backendSession?: BackendChatSession
  ) => {
    const initialData: Partial<ChatSessionData> = {
      isLoaded: true,
      description: backendSession?.description,
      personaId: backendSession?.persona_id,
    };

    const existingSession = get().sessions.get(sessionId);
    if (existingSession) {
      get().updateSessionData(sessionId, initialData);
    } else {
      get().createSession(sessionId, initialData);
    }
  },

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

      const newSessions = new Map(sessionsToKeep);

      return {
        sessions: newSessions,
      };
    });
  },
}));

// Custom hooks for accessing store data
export const useCurrentSession = () =>
  useChatSessionStore((state) => {
    const { currentSessionId, sessions } = state;
    return currentSessionId ? sessions.get(currentSessionId) || null : null;
  });

export const useSession = (sessionId: string) =>
  useChatSessionStore((state) => state.sessions.get(sessionId) || null);

export const useCurrentMessageTree = () =>
  useChatSessionStore((state) => {
    const { currentSessionId, sessions } = state;
    const currentSession = currentSessionId
      ? sessions.get(currentSessionId)
      : null;
    return currentSession?.messageTree;
  });

export const useCurrentMessageHistory = () => {
  const messageTree = useCurrentMessageTree();
  return useMemo(() => {
    if (!messageTree) {
      return [];
    }
    return getLatestMessageChain(messageTree);
  }, [messageTree]);
};

export const useCurrentChatState = () =>
  useChatSessionStore((state) => {
    const { currentSessionId, sessions } = state;
    const currentSession = currentSessionId
      ? sessions.get(currentSessionId)
      : null;
    return currentSession?.chatState || "input";
  });

export const useCurrentRegenerationState = () =>
  useChatSessionStore((state) => {
    const { currentSessionId, sessions } = state;
    const currentSession = currentSessionId
      ? sessions.get(currentSessionId)
      : null;
    return currentSession?.regenerationState || null;
  });

export const useCanContinue = () =>
  useChatSessionStore((state) => {
    const { currentSessionId, sessions } = state;
    const currentSession = currentSessionId
      ? sessions.get(currentSessionId)
      : null;
    return currentSession?.canContinue || false;
  });

export const useSubmittedMessage = () =>
  useChatSessionStore((state) => {
    const { currentSessionId, sessions } = state;
    const currentSession = currentSessionId
      ? sessions.get(currentSessionId)
      : null;
    return currentSession?.submittedMessage || "";
  });

export const useRegenerationState = (sessionId: string) =>
  useChatSessionStore((state) => {
    const session = state.sessions.get(sessionId);
    return session?.regenerationState || null;
  });

export const useAbortController = (sessionId: string) =>
  useChatSessionStore((state) => {
    const session = state.sessions.get(sessionId);
    return session?.abortController || null;
  });

export const useAbortControllers = () => {
  const sessions = useChatSessionStore((state) => state.sessions);
  return useMemo(() => {
    const controllers = new Map<string, AbortController>();
    sessions.forEach((session: ChatSessionData) => {
      if (session.abortController) {
        controllers.set(session.sessionId, session.abortController);
      }
    });
    return controllers;
  }, [sessions]);
};

// Session-specific state hooks (previously global)
export const useIsFetching = () =>
  useChatSessionStore((state) => {
    const { currentSessionId, sessions } = state;
    const currentSession = currentSessionId
      ? sessions.get(currentSessionId)
      : null;
    return currentSession?.isFetchingChatMessages || false;
  });

export const useUncaughtError = () =>
  useChatSessionStore((state) => {
    const { currentSessionId, sessions } = state;
    const currentSession = currentSessionId
      ? sessions.get(currentSessionId)
      : null;
    return currentSession?.uncaughtError || null;
  });

export const useLoadingError = () =>
  useChatSessionStore((state) => {
    const { currentSessionId, sessions } = state;
    const currentSession = currentSessionId
      ? sessions.get(currentSessionId)
      : null;
    return currentSession?.loadingError || null;
  });

export const useIsReady = () =>
  useChatSessionStore((state) => {
    const { currentSessionId, sessions } = state;
    const currentSession = currentSessionId
      ? sessions.get(currentSessionId)
      : null;
    return currentSession?.isReady ?? true;
  });

export const useMaxTokens = () =>
  useChatSessionStore((state) => {
    const { currentSessionId, sessions } = state;
    const currentSession = currentSessionId
      ? sessions.get(currentSessionId)
      : null;
    return currentSession?.maxTokens || 128_000;
  });

export const useHasPerformedInitialScroll = () =>
  useChatSessionStore((state) => {
    const { currentSessionId, sessions } = state;
    const currentSession = currentSessionId
      ? sessions.get(currentSessionId)
      : null;
    return currentSession?.hasPerformedInitialScroll || true;
  });

export const useDocumentSidebarVisible = () =>
  useChatSessionStore((state) => {
    const { currentSessionId, sessions } = state;
    const currentSession = currentSessionId
      ? sessions.get(currentSessionId)
      : null;
    return currentSession?.documentSidebarVisible || false;
  });

export const useSelectedNodeForDocDisplay = () =>
  useChatSessionStore((state) => {
    const { currentSessionId, sessions } = state;
    const currentSession = currentSessionId
      ? sessions.get(currentSessionId)
      : null;
    return currentSession?.selectedNodeIdForDocDisplay || null;
  });

export const useChatSessionSharedStatus = () =>
  useChatSessionStore((state) => {
    const { currentSessionId, sessions } = state;
    const currentSession = currentSessionId
      ? sessions.get(currentSessionId)
      : null;
    return (
      currentSession?.chatSessionSharedStatus || ChatSessionSharedStatus.Private
    );
  });

export const useHasSentLocalUserMessage = () =>
  useChatSessionStore((state) => {
    const { currentSessionId, sessions } = state;
    const currentSession = currentSessionId
      ? sessions.get(currentSessionId)
      : null;
    return currentSession?.hasSentLocalUserMessage || false;
  });
