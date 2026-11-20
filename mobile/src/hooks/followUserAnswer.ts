import type { QueryClient } from "@tanstack/react-query";

import type { ChatStream } from "@/chat/interfaces";
import { recoverChatSession } from "@/hooks/useChatSessionController";
import { useChatSessionStore } from "@/state/chatSessionStore";

// After the user answers a waiting response (an approval decision, or answers to its questions),
// follow the `continuation` that the server names. The server names one only for a suspended
// response that resumes at once; a live response goes on in the stream a reader already follows.
// Otherwise, as when another turn holds the chat or the request no longer waits, recovery follows
// the session's streams while it processes and then reloads the saved outcome. `sessionId` is the
// chat that answered; the user can open another one while the answer is in flight, and reopening
// the chat recovers it. `followWithoutStream` replaces that recovery when the answer names no
// continuation and no reader owns the chat.
export function followUserAnswer(
  sessionId: string | null,
  continuation: ChatStream | null,
  serverUrl: string | null,
  queryClient: QueryClient,
  followWithoutStream?: (sessionId: string) => void,
): void {
  const store = useChatSessionStore.getState();
  if (!sessionId || store.currentSessionId !== sessionId) return;
  // A reader that owns the chat can be past its last status read; it follows the continuation,
  // or reads status again, before it releases the chat.
  if (store.sessions.get(sessionId)?.abortController) {
    store.queueFollow(sessionId, continuation);
    return;
  }
  if (continuation === null && followWithoutStream) {
    followWithoutStream(sessionId);
    return;
  }
  if (continuation === null) store.updateChatState(sessionId, "settling");
  void recoverChatSession(
    sessionId,
    continuation,
    serverUrl,
    queryClient,
    new AbortController(),
  );
}
