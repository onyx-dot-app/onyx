// Shared default-builder for a ChatSessionData so the store and persist.ts build
// fresh sessions from the same defaults. Type-only imports ChatSessionData (erased
// at runtime), so the store can value-import this without a runtime import cycle.
import { ChatState, ChatSessionSharedStatus, Message } from "@/lib/types";
import type { ChatSessionData } from "./chatSessionStore";

export const createInitialSessionData = (
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
  queuedMessages: [],
  latestMessageRenderComplete: true,
  isStreamDraining: false,
  ...initialData,
});
