import type { Message } from "@/app/app/interfaces";
import { processRawChatHistory } from "@/app/app/services/lib";
import { useChatSessionStore } from "@/app/app/stores/useChatSessionStore";
import {
  fetchSettledChatSession,
  waitForChatSessionIdle,
} from "@/lib/chat/sessionReadiness";

interface SettleChatSessionOptions {
  sessionId: string;
  controller: AbortController;
  errorMessage: string;
  refreshHistory?: boolean;
  completeRendering?: boolean;
}

function preserveFailedMessages(
  saved: Map<number, Message>,
  local: Map<number, Message>
): Map<number, Message> {
  for (const node of local.values()) {
    if (node.type !== "error") continue;
    const savedNode =
      node.messageId === undefined ? undefined : saved.get(node.messageId);
    // A rejected send has no saved row. Keep its local turn available for retry.
    if (!savedNode) return local;
    saved.set(savedNode.nodeId, {
      ...savedNode,
      type: "error",
      message: node.message,
      errorCode: node.errorCode,
      stackTrace: node.stackTrace,
      isRetryable: node.isRetryable,
      errorDetails: node.errorDetails,
      packets: [],
      packetCount: 0,
    });
  }
  return saved;
}

/** Release input only after the same request has finished execution and storage. */
export async function settleChatSession({
  sessionId,
  controller,
  errorMessage,
  refreshHistory = true,
  completeRendering = true,
}: SettleChatSessionOptions): Promise<void> {
  const ownsSettlement = () => {
    const session = useChatSessionStore.getState().sessions.get(sessionId);
    return (
      session?.abortController === controller && session.chatState !== "input"
    );
  };
  if (!ownsSettlement()) return;
  try {
    const sendAcknowledged = useChatSessionStore
      .getState()
      .sessions.get(sessionId)?.sendAcknowledged;
    if (sendAcknowledged) {
      await sendAcknowledged;
      if (!ownsSettlement()) return;
    }
    await waitForChatSessionIdle(sessionId);
    if (!ownsSettlement()) return;
    if (refreshHistory) {
      const settled = await fetchSettledChatSession(sessionId);
      if (!ownsSettlement()) return;
      if (settled.is_processing || settled.current_stream)
        throw new Error("Session became busy during refresh");
      const store = useChatSessionStore.getState();
      const local = store.sessions.get(sessionId)?.messageTree;
      const saved = processRawChatHistory(settled.messages, settled.packets);
      store.updateSessionMessageTree(
        sessionId,
        local ? preserveFailedMessages(saved, local) : saved
      );
    }
    const store = useChatSessionStore.getState();
    if (store.sessions.get(sessionId)?.uncaughtError === errorMessage) {
      store.setUncaughtError(sessionId, null);
    }
    store.updateSessionData(sessionId, {
      chatState: "input",
      regenerationState: null,
      streamingStartTime: undefined,
      sendAcknowledged: undefined,
    });
    if (completeRendering)
      store.setLatestMessageRenderComplete(sessionId, true);
  } catch (error) {
    if (!ownsSettlement()) return;
    console.error("Could not confirm chat completion", error);
    const store = useChatSessionStore.getState();
    store.updateSessionData(sessionId, { queuedMessagesPaused: true });
    store.updateChatState(sessionId, "unconfirmed");
    store.setUncaughtError(sessionId, errorMessage);
  }
}
