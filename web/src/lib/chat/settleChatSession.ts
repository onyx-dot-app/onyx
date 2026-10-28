import type { Message } from "@/app/app/types";
import { processRawChatHistory } from "@/app/app/services/lib";
import { getLatestMessageChain } from "@/app/app/services/messageTree";
import { useChatSessionStore } from "@/app/app/stores/useChatSessionStore";
import {
  fetchSettledChatSession,
  waitForChatSessionIdle,
} from "@/lib/chat/sessionReadiness";

interface SettleChatSessionOptions {
  sessionId: string;
  controller: AbortController;
  errorMessage: string;
  mode?: "completion" | "recovery";
  refreshHistory?: boolean;
  completeRendering?: boolean;
}

export function preserveFailedMessages(
  saved: Map<number, Message>,
  local: Map<number, Message>
): Map<number, Message> {
  const latest = getLatestMessageChain(local).at(-1);
  for (const node of local.values()) {
    if (node.type !== "error") continue;
    const savedNode =
      node.messageId === undefined ? undefined : saved.get(node.messageId);
    if (!savedNode) {
      // Keep the current rejected turn for retry; older rejected attempts are local only.
      if (node.nodeId === latest?.nodeId) return local;
      continue;
    }
    // Persisted failures and final answers are authoritative; packets can precede either save.
    if (
      savedNode.type === "error" ||
      (savedNode.type === "assistant" &&
        (savedNode.message || savedNode.files.length > 0))
    ) {
      continue;
    }
    saved.set(savedNode.nodeId, {
      ...savedNode,
      type: "error",
      message: node.message,
      errorMessage: node.errorMessage,
      errorCode: node.errorCode,
      stackTrace: node.stackTrace,
      isRetryable: node.isRetryable,
      errorDetails: node.errorDetails,
      packets: node.packets,
      packetCount: node.packetCount,
    });
  }
  return saved;
}

/** Release input only after the same request has finished execution and storage. */
export async function settleChatSession({
  sessionId,
  controller,
  errorMessage,
  mode = "completion",
  refreshHistory = true,
  completeRendering = true,
}: SettleChatSessionOptions): Promise<void> {
  const session = useChatSessionStore.getState().sessions.get(sessionId);
  const sendAcknowledged = session?.sendAcknowledged;
  const readerFinished = session?.readerFinished;
  const ownsSettlement = () => {
    const current = useChatSessionStore.getState().sessions.get(sessionId);
    return (
      current?.abortController === controller &&
      current.readerFinished === readerFinished &&
      current.chatState !== "input"
    );
  };
  if (!ownsSettlement()) return;
  try {
    if (sendAcknowledged) {
      try {
        await sendAcknowledged;
      } catch (error) {
        // Explicit recovery checks server state after the original send failed.
        if (mode !== "recovery") throw error;
      }
      if (!ownsSettlement()) return;
    }
    if (readerFinished) {
      await readerFinished;
      if (!ownsSettlement()) return;
    }
    await waitForChatSessionIdle(sessionId);
    if (!ownsSettlement()) return;
    if (refreshHistory || mode === "recovery") {
      const settled = await fetchSettledChatSession(sessionId);
      if (!ownsSettlement()) return;
      if (settled.is_processing || settled.current_stream)
        throw new Error("Session became busy during refresh");
      const store = useChatSessionStore.getState();
      const session = store.sessions.get(sessionId);
      // Incognito history can contain only usage metadata. Live content stays local.
      if (!session?.incognito && !settled.incognito) {
        const local = session?.messageTree;
        const saved = processRawChatHistory(settled.messages, settled.packets);
        const messageTree = local
          ? preserveFailedMessages(saved, local)
          : saved;
        const selectedNodeId = session?.selectedNodeIdForDocDisplay;
        const selectedMessageId =
          selectedNodeId == null
            ? undefined
            : local?.get(selectedNodeId)?.messageId;
        const latestType = getLatestMessageChain(messageTree).at(-1)?.type;
        store.updateSessionData(sessionId, {
          messageTree,
          uncaughtError:
            latestType === "assistant" || latestType === "error"
              ? null
              : (session?.uncaughtError ?? null),
          selectedNodeIdForDocDisplay:
            messageTree === local
              ? (selectedNodeId ?? null)
              : selectedMessageId === undefined
                ? null
                : (messageTree.get(selectedMessageId)?.nodeId ?? null),
        });
      }
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
      readerFinished: undefined,
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
