import { create } from "zustand";
import {
  ChatState,
  RegenerationState,
  Message,
  ChatSessionSharedStatus,
  BackendChatSession,
  FeedbackType,
} from "@/app/app/types";
import {
  getLatestMessageChain,
  getMessageByMessageId,
  MessageTreeState,
} from "../services/messageTree";
import { useMemo } from "react";
import type { ChatToolSelection } from "@/lib/tools/types";

/** An error that belongs to the session, not to a saved message. */
export interface SessionError {
  error: string;
  errorCode?: string;
  isRetryable?: boolean;
  details?: Record<string, any>;
  stackTrace?: string | null;
}

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
  sendAcknowledged?: Promise<number | null>;
  // Resolves after the reader applies its final packets and message state.
  readerFinished?: Promise<void>;
  hasPerformedInitialScroll: boolean;
  documentSidebarVisible: boolean;
  hasSentLocalUserMessage: boolean;

  // Session-specific state (previously global)
  isFetchingChatMessages: boolean;
  // Paged loading: the current branch has messages above the loaded ones.
  hasOlderMessages: boolean;
  isLoadingOlderMessages: boolean;
  uncaughtError: SessionError | null;
  loadingError: string | null;
  isReady: boolean;

  // Session metadata
  lastAccessed: Date;
  isLoaded: boolean;
  description?: string;
  personaId?: number;
  // Pinned at creation server-side, so it outlives the live UI toggle.
  incognito?: boolean;
  // The chat's saved tools and search filters, owned by the server; the tab's
  // only copy for a chat that stores no content. Undefined until known.
  toolSelection?: ChatToolSelection | null;
  // The user's changes to that selection that the server has not confirmed;
  // the composer shows them over the server's copy.
  toolSelectionEdits?: Partial<ChatToolSelection>;
  // Counts the server's confirmations of that selection; a chat load that
  // started before the latest one carries an older copy.
  toolSelectionVersion?: number;

  // Streaming duration tracking
  streamingStartTime?: number;

  // True while the smooth-streaming typewriter is running its post-finish
  // adaptive drain. Auto-scroll pauses during this window so the page
  // doesn't yank as the typewriter speeds up — the user is reading at
  // this point, not watching new content arrive.
  isStreamDraining: boolean;
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
  updateMessageFeedback: (
    sessionId: string,
    messageId: number,
    feedback: string | null
  ) => void;
  updateCurrentMessageFeedback: (
    messageId: number,
    feedback: string | null
  ) => void;
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
  setUncaughtError: (sessionId: string, error: SessionError | null) => void;
  setLoadingError: (sessionId: string, error: string | null) => void;
  setIsReady: (sessionId: string, ready: boolean) => void;

  // Actions - Streaming Duration
  setStreamingStartTime: (sessionId: string, time: number | null) => void;
  getStreamingStartTime: (sessionId: string) => number | undefined;

  setIsStreamDraining: (sessionId: string, draining: boolean) => void;

  // Actions - Abort Controllers
  setAbortController: (sessionId: string, controller: AbortController) => void;
  abortSession: (sessionId: string) => void;
  abortAllSessions: () => void;

  // Utilities
  initializeSession: (
    sessionId: string,
    backendSession?: BackendChatSession,
    toolSelectionVersion?: number
  ) => void;
  cleanupOldSessions: (maxSessions?: number) => void;
}

const createInitialSessionData = (
  sessionId: string,
  initialData?: Partial<ChatSessionData>
): ChatSessionData => ({
  sessionId,
  messageTree: new Map<number, Message>(),
  chatState: "input",
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
  hasOlderMessages: false,
  isLoadingOlderMessages: false,
  uncaughtError: null,
  loadingError: null,
  isReady: true,

  lastAccessed: new Date(),
  isLoaded: false,
  isStreamDraining: false,
  ...initialData,
});

// Chats kept in memory per tab. Older idle ones are dropped; opening one
// again fetches it from the server.
const MAX_CACHED_SESSIONS = 10;

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
    // A long-lived tab would otherwise keep every chat it ever opened.
    get().cleanupOldSessions();
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

  updateMessageFeedback: (
    sessionId: string,
    messageId: number,
    feedback: string | null
  ) => {
    set((state) => {
      const session = state.sessions.get(sessionId);
      if (!session) {
        console.warn(`Session ${sessionId} not found`);
        return state;
      }

      const message = getMessageByMessageId(session.messageTree, messageId);
      if (!message) {
        console.warn(`Message ${messageId} not found in session ${sessionId}`);
        return state;
      }

      // Create new message object with updated feedback (immutable update)
      const updatedMessage = {
        ...message,
        currentFeedback: feedback as FeedbackType | null,
      };

      // Create new messageTree Map with updated message
      const newMessageTree = new Map(session.messageTree);
      newMessageTree.set(message.nodeId, updatedMessage);

      // Create new session object with new messageTree
      const updatedSession = {
        ...session,
        messageTree: newMessageTree,
        lastAccessed: new Date(),
      };

      const newSessions = new Map(state.sessions);
      newSessions.set(sessionId, updatedSession);

      return { sessions: newSessions };
    });
  },

  updateCurrentMessageFeedback: (
    messageId: number,
    feedback: string | null
  ) => {
    const { currentSessionId } = get();
    if (currentSessionId) {
      get().updateMessageFeedback(currentSessionId, messageId, feedback);
    }
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

  setUncaughtError: (sessionId: string, uncaughtError: SessionError | null) => {
    get().updateSessionData(sessionId, { uncaughtError });
  },

  setLoadingError: (sessionId: string, loadingError: string | null) => {
    get().updateSessionData(sessionId, { loadingError });
  },

  setIsReady: (sessionId: string, isReady: boolean) => {
    get().updateSessionData(sessionId, { isReady });
  },

  // Streaming Duration Actions
  setStreamingStartTime: (sessionId: string, time: number | null) => {
    get().updateSessionData(sessionId, {
      streamingStartTime: time ?? undefined,
    });
  },

  getStreamingStartTime: (sessionId: string) => {
    return get().sessions.get(sessionId)?.streamingStartTime;
  },

  setIsStreamDraining: (sessionId: string, draining: boolean) => {
    const session = get().sessions.get(sessionId);
    if (!session || session.isStreamDraining === draining) return;
    get().updateSessionData(sessionId, { isStreamDraining: draining });
  },

  // Abort Controller Actions
  setAbortController: (sessionId: string, controller: AbortController) => {
    get().updateSessionData(sessionId, {
      abortController: controller,
      sendAcknowledged: undefined,
      readerFinished: undefined,
    });
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
    backendSession?: BackendChatSession,
    toolSelectionVersion: number = 0
  ) => {
    const existingSession = get().sessions.get(sessionId);
    // A load that started before a save was confirmed holds a stale selection.
    // The server never clears a stored selection, so a load without one keeps
    // the tab's copy: that chat stores none, and the tab holds the only copy.
    const selectionIsCurrent =
      (existingSession?.toolSelectionVersion ?? 0) === toolSelectionVersion &&
      (backendSession?.tool_selection != null ||
        existingSession?.toolSelection == null);
    const initialData: Partial<ChatSessionData> = {
      isLoaded: true,
      description: backendSession?.description,
      personaId: backendSession?.persona_id,
      incognito: backendSession?.incognito ?? false,
      ...(backendSession &&
        selectionIsCurrent && {
          toolSelection: backendSession.tool_selection ?? null,
        }),
    };

    if (existingSession) {
      get().updateSessionData(sessionId, initialData);
    } else {
      get().createSession(sessionId, initialData);
    }
  },

  cleanupOldSessions: (maxSessions: number = MAX_CACHED_SESSIONS) => {
    set((state) => {
      if (state.sessions.size <= maxSessions) {
        return state;
      }

      // Only idle sessions are evicted: the open one, one that is streaming or
      // otherwise busy, and one that may be
      // incognito stay. An incognito chat cannot be rebuilt from the server,
      // so this tab holds its only copy; a session whose incognito state is
      // not known yet (a send can run before its load sets the flag) counts as
      // incognito, unless it holds no messages: a chat left before it loaded
      // is an empty placeholder with nothing to lose. A session still
      // fetching can go: its fetch no longer owns the session and discards
      // the result.
      const isEvictable = (sessionId: string, session: ChatSessionData) =>
        sessionId !== state.currentSessionId &&
        session.chatState === "input" &&
        (session.incognito === false ||
          (session.incognito === undefined && session.messageTree.size === 0));

      const evictable = Array.from(state.sessions.entries())
        .filter(([sessionId, session]) => isEvictable(sessionId, session))
        .sort(
          ([, a], [, b]) => b.lastAccessed.getTime() - a.lastAccessed.getTime()
        );
      const keptBusy = state.sessions.size - evictable.length;
      // The most recently used idle sessions fill the room the busy ones leave.
      const toRemove = evictable.slice(Math.max(maxSessions - keptBusy, 0));
      if (toRemove.length === 0) {
        return state;
      }

      const newSessions = new Map(state.sessions);
      toRemove.forEach(([sessionId]) => newSessions.delete(sessionId));
      return { sessions: newSessions };
    });
  },
}));

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

/**
 * The reader has the server's stop packet for every response of the open
 * chat's latest turn. Only rendering and settlement remain, so the turn cannot
 * be stopped.
 */
export const useCurrentResponseStopped = () =>
  useChatSessionStore((state) => {
    const { currentSessionId, sessions } = state;
    const currentSession = currentSessionId
      ? sessions.get(currentSessionId)
      : null;
    if (!currentSession) return false;
    const tree = currentSession.messageTree;
    const latest = getLatestMessageChain(tree).at(-1);
    if (!latest) return false;
    // Each model of a multi-model turn is a sibling that ends with its own stop.
    const turn =
      latest.parentNodeId === null
        ? [latest]
        : (tree.get(latest.parentNodeId)?.childrenNodeIds ?? [latest.nodeId])
            .map((nodeId) => tree.get(nodeId))
            .filter((node): node is Message => node !== undefined);
    return (
      turn.length > 0 &&
      turn.every((node) => node.packets.at(-1)?.obj.type === "stop")
    );
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

/** The open chat has older messages to load above the loaded ones. */
export const useHasOlderMessages = () =>
  useChatSessionStore((state) => {
    const { currentSessionId, sessions } = state;
    const currentSession = currentSessionId
      ? sessions.get(currentSessionId)
      : null;
    return currentSession?.hasOlderMessages ?? false;
  });

/** The open chat is loading a page of older messages. */
export const useIsLoadingOlderMessages = () =>
  useChatSessionStore((state) => {
    const { currentSessionId, sessions } = state;
    const currentSession = currentSessionId
      ? sessions.get(currentSessionId)
      : null;
    return currentSession?.isLoadingOlderMessages ?? false;
  });

export const useIsFetchingChatMessages = () =>
  useChatSessionStore((state) => {
    const { currentSessionId, sessions } = state;
    const currentSession = currentSessionId
      ? sessions.get(currentSessionId)
      : null;
    return currentSession?.isFetchingChatMessages ?? false;
  });

export const useDocumentSidebarVisible = () =>
  useChatSessionStore((state) => {
    const { currentSessionId, sessions } = state;
    const currentSession = currentSessionId
      ? sessions.get(currentSessionId)
      : null;
    return currentSession?.documentSidebarVisible || false;
  });

/**
 * The agent the open session was created with, from the session the backend
 * actually returned. `useChatSessions` cannot answer this for every session:
 * it pages 50 at a time, so an older chat is missing from its list.
 */
export const useCurrentSessionPersonaId = () =>
  useChatSessionStore((state) => {
    const { currentSessionId, sessions } = state;
    const currentSession = currentSessionId
      ? sessions.get(currentSessionId)
      : null;
    return currentSession?.personaId ?? null;
  });

export const useSelectedNodeForDocDisplay = () =>
  useChatSessionStore((state) => {
    const { currentSessionId, sessions } = state;
    const currentSession = currentSessionId
      ? sessions.get(currentSessionId)
      : null;
    return currentSession?.selectedNodeIdForDocDisplay || null;
  });

export const useHasSentLocalUserMessage = () =>
  useChatSessionStore((state) => {
    const { currentSessionId, sessions } = state;
    const currentSession = currentSessionId
      ? sessions.get(currentSessionId)
      : null;
    return currentSession?.hasSentLocalUserMessage || false;
  });

export const useStreamingStartTime = () =>
  useChatSessionStore((state) => {
    const { currentSessionId, sessions } = state;
    const currentSession = currentSessionId
      ? sessions.get(currentSessionId)
      : null;
    return currentSession?.streamingStartTime;
  });

export const useCurrentIsStreamDraining = () =>
  useChatSessionStore((state) => {
    const { currentSessionId, sessions } = state;
    const currentSession = currentSessionId
      ? sessions.get(currentSessionId)
      : null;
    return currentSession?.isStreamDraining ?? false;
  });
