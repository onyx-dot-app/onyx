// Shared default-builder for a ChatSessionData.
//
// Extracted out of chatSessionStore.ts so BOTH the store and persist.ts can build
// a fresh ChatSessionData from the exact same field-by-field defaults, instead of
// hand-maintaining two parallel copies that must be kept in sync. This module
// type-only imports ChatSessionData from the store (erased at runtime), so the
// store can value-import this without creating a runtime import cycle.
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
