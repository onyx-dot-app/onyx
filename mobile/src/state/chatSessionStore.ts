// Ephemeral per-session chat state. NEVER persisted: holds live AbortControllers. The Map-per-session
// is what stops one stream writing into another.
import { create } from "zustand";

import { ChatState, Message } from "@/chat/interfaces";
import { MessageTreeState, upsertMessages } from "@/chat/messageTree";

export interface SessionData {
  messageTree: MessageTreeState;
  chatState: ChatState;
  abortController: AbortController | null;
  submittedMessage: string;
}

interface ChatSessionStore {
  currentSessionId: string | null;
  sessions: Map<string, SessionData>;

  setCurrentSession: (sessionId: string | null) => void;
  // Creates an empty session if absent; never clobbers an existing one.
  ensureSession: (sessionId: string) => void;
  hydrateSession: (sessionId: string, messageTree: MessageTreeState) => void;
  updateSessionTree: (sessionId: string, messageTree: MessageTreeState) => void;
  updateChatState: (sessionId: string, chatState: ChatState) => void;
  setSubmittedMessage: (sessionId: string, message: string) => void;
  setAbortController: (
    sessionId: string,
    abortController: AbortController | null,
  ) => void;
  abortSession: (sessionId: string) => void;
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

  hydrateSession: (sessionId, messageTree) =>
    set((state) => ({
      sessions: writeSession(state.sessions, sessionId, {
        messageTree,
        chatState: "input",
      }),
    })),

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
      sessions: writeSession(state.sessions, sessionId, { abortController }),
    })),

  abortSession: (sessionId) => {
    const data = get().sessions.get(sessionId);
    data?.abortController?.abort();
    set((state) => ({
      sessions: writeSession(state.sessions, sessionId, {
        abortController: null,
        chatState: "input",
      }),
    }));
  },

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
