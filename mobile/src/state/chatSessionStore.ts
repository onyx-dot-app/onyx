// Ephemeral per-session chat state. NEVER persisted: holds live AbortControllers. The Map-per-session
// is what stops one stream writing into another.
import { create } from "zustand";

import { ChatState, ChatStream, Message } from "@/chat/interfaces";
import { MessageTreeState, upsertMessages } from "@/chat/messageTree";

export interface SessionData {
  messageTree: MessageTreeState;
  chatState: ChatState;
  abortController: AbortController | null;
  submittedMessage: string;
  streamId: number | null;
  stopRequested: boolean;
  // The `approvals_version` of the load whose approval requests the chat shows.
  approvalsVersion?: string;
  // A decision's continuation, or a status read (`stream: null`), that came while a reader owned
  // the chat; the reader follows it before it releases the chat.
  queuedFollow: { stream: ChatStream | null } | null;
}

interface ChatSessionStore {
  currentSessionId: string | null;
  sessions: Map<string, SessionData>;

  setCurrentSession: (sessionId: string | null) => void;
  // Creates an empty session if absent; never clobbers an existing one.
  ensureSession: (sessionId: string) => void;
  // `approvalsVersion`: the version of the load that `messageTree` shows.
  hydrateSession: (
    sessionId: string,
    messageTree: MessageTreeState,
    approvalsVersion?: string,
  ) => void;
  queueFollow: (sessionId: string, stream: ChatStream | null) => void;
  // Returns and clears the queued follow.
  takeQueuedFollow: (sessionId: string) => { stream: ChatStream | null } | null;
  updateSessionTree: (sessionId: string, messageTree: MessageTreeState) => void;
  updateChatState: (sessionId: string, chatState: ChatState) => void;
  setSubmittedMessage: (sessionId: string, message: string) => void;
  setAbortController: (
    sessionId: string,
    abortController: AbortController | null,
  ) => void;
  abortSession: (sessionId: string) => void;
  setStreamId: (sessionId: string, streamId: number) => void;
  setStopRequested: (sessionId: string, requested: boolean) => void;
  patchNode: (
    sessionId: string,
    nodeId: number,
    patch: Partial<Message>,
  ) => void;
}

function emptySession(): SessionData {
  return {
    messageTree: new Map(),
    chatState: "input",
    abortController: null,
    submittedMessage: "",
    streamId: null,
    stopRequested: false,
    queuedFollow: null,
  };
}

// New Map + SessionData each write so selectors re-render.
function writeSession(
  sessions: Map<string, SessionData>,
  sessionId: string,
  patch: Partial<SessionData>,
): Map<string, SessionData> {
  const next = new Map(sessions);
  const current = next.get(sessionId) ?? emptySession();
  next.set(sessionId, { ...current, ...patch });
  return next;
}

export const useChatSessionStore = create<ChatSessionStore>((set, get) => ({
  currentSessionId: null,
  sessions: new Map(),

  setCurrentSession: (sessionId) => set({ currentSessionId: sessionId }),

  ensureSession: (sessionId) => {
    if (get().sessions.has(sessionId)) return;
    set((state) => ({ sessions: writeSession(state.sessions, sessionId, {}) }));
  },

  hydrateSession: (sessionId, messageTree, approvalsVersion) =>
    set((state) => ({
      sessions: writeSession(state.sessions, sessionId, {
        messageTree,
        chatState: "input",
        ...(approvalsVersion !== undefined && { approvalsVersion }),
      }),
    })),

  queueFollow: (sessionId, stream) =>
    set((state) => {
      const queued = state.sessions.get(sessionId)?.queuedFollow;
      return {
        sessions: writeSession(state.sessions, sessionId, {
          // A named continuation outranks a status read.
          queuedFollow: { stream: stream ?? queued?.stream ?? null },
        }),
      };
    }),

  takeQueuedFollow: (sessionId) => {
    const queued = get().sessions.get(sessionId)?.queuedFollow ?? null;
    if (queued !== null)
      set((state) => ({
        sessions: writeSession(state.sessions, sessionId, {
          queuedFollow: null,
        }),
      }));
    return queued;
  },

  updateSessionTree: (sessionId, messageTree) =>
    set((state) => ({
      sessions: writeSession(state.sessions, sessionId, { messageTree }),
    })),

  updateChatState: (sessionId, chatState) =>
    set((state) => ({
      sessions: writeSession(state.sessions, sessionId, { chatState }),
    })),

  setSubmittedMessage: (sessionId, message) =>
    set((state) => ({
      sessions: writeSession(state.sessions, sessionId, {
        submittedMessage: message,
      }),
    })),

  setAbortController: (sessionId, abortController) =>
    set((state) => ({
      sessions: writeSession(state.sessions, sessionId, {
        abortController,
        streamId: null,
        stopRequested: false,
      }),
    })),

  abortSession: (sessionId) => {
    const data = get().sessions.get(sessionId);
    data?.abortController?.abort();
  },

  setStreamId: (sessionId, streamId) =>
    set((state) => ({
      sessions: writeSession(state.sessions, sessionId, { streamId }),
    })),
  setStopRequested: (sessionId, requested) =>
    set((state) => ({
      sessions: writeSession(state.sessions, sessionId, {
        stopRequested: requested,
      }),
    })),

  patchNode: (sessionId, nodeId, patch) =>
    set((state) => {
      const data = state.sessions.get(sessionId);
      const node = data?.messageTree.get(nodeId);
      if (!data || !node) return {};
      const messageTree = upsertMessages(
        data.messageTree,
        [{ ...node, ...patch }],
        false,
      );
      return {
        sessions: writeSession(state.sessions, sessionId, { messageTree }),
      };
    }),
}));
