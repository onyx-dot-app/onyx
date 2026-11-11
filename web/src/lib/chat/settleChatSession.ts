import type { BackendChatSession, Message } from "@/app/app/types";
import { processRawChatHistory, resumeStream } from "@/app/app/services/lib";
import {
  getLatestMessageChain,
  getMessageByMessageId,
} from "@/app/app/services/messageTree";
import { mergeLatestChatPage } from "@/lib/chat/pagedSession";
import type { Packet } from "@/app/app/services/streamingModels";
import { useChatSessionStore } from "@/app/app/stores/useChatSessionStore";
import {
  fetchSettledChatSession,
  waitForChatResponseEnd,
} from "@/lib/chat/sessionReadiness";

interface SettleChatSessionOptions {
  sessionId: string;
  controller: AbortController;
  errorMessage: string;
  mode?: "completion" | "recovery";
  refreshHistory?: boolean;
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
    // A reserved row can contain fallback text without a saved execution outcome.
    const hasSavedAnswer =
      savedNode.type === "assistant" &&
      (savedNode.responseStatus === undefined
        ? Boolean(savedNode.message || savedNode.files.length > 0)
        : savedNode.responseStatus === "complete" ||
          savedNode.responseStatus === "limit" ||
          savedNode.responseStatus === "cancelled");
    if (savedNode.type === "error" || hasSavedAnswer) {
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

/** Reconcile server-started turns without replacing a reader's live output. */
export async function refreshChatSession(
  sessionId: string,
  errorMessage: string,
  savedSession?: BackendChatSession
): Promise<void> {
  const session = useChatSessionStore.getState().sessions.get(sessionId);
  if (!session || session.incognito) return;
  const {
    abortController: controller,
    readerFinished,
    sendAcknowledged,
  } = session;
  const selectedNodeId = getLatestMessageChain(session.messageTree).at(
    -1
  )?.nodeId;
  const ownsRefresh = () => {
    const current = useChatSessionStore.getState().sessions.get(sessionId);
    return (
      current?.abortController === controller &&
      current.readerFinished === readerFinished &&
      getLatestMessageChain(current.messageTree).at(-1)?.nodeId ===
        selectedNodeId
    );
  };
  try {
    let saved = savedSession ?? (await fetchSettledChatSession(sessionId));
    if (!ownsRefresh()) return;
    let streamId: number | null | undefined;
    try {
      streamId = await sendAcknowledged;
    } catch {
      // A lost acknowledgement can still have a saved response to recover.
    }
    if (!ownsRefresh()) return;
    const nextStreamId = saved.current_stream?.stream_id;
    if (
      readerFinished &&
      streamId === nextStreamId &&
      nextStreamId !== undefined
    ) {
      return;
    }
    await readerFinished;
    if (!ownsRefresh()) return;
    // The original page can predate the old reader's final packets and save.
    if (readerFinished && savedSession === undefined) {
      saved = await fetchSettledChatSession(sessionId);
      if (!ownsRefresh()) return;
    }
    const store = useChatSessionStore.getState();
    const current = store.sessions.get(sessionId);
    if (!current) return;
    const page = mergeLatestChatPage(saved, current);
    const messages = preserveFailedMessages(
      page.messageTree,
      current.messageTree
    );
    const currentStreamId = saved.current_stream?.stream_id;
    const response =
      currentStreamId === undefined
        ? undefined
        : getMessageByMessageId(messages, currentStreamId);
    if (currentStreamId !== undefined && response?.type === "assistant") {
      const retained = getMessageByMessageId(
        current.messageTree,
        currentStreamId
      );
      messages.set(
        response.nodeId,
        retained?.replayCursor !== undefined
          ? {
              ...response,
              ...retained,
              nodeId: response.nodeId,
              parentNodeId: response.parentNodeId,
              childrenNodeIds: response.childrenNodeIds,
              latestChildNodeId: response.latestChildNodeId,
            }
          : { ...response, message: "", packets: [], packetCount: 0 }
      );
    }
    const busy = Boolean(saved.is_processing || saved.current_stream);
    const selectedMessageId =
      current.selectedNodeIdForDocDisplay === null
        ? undefined
        : current.messageTree.get(current.selectedNodeIdForDocDisplay)
            ?.messageId;
    store.updateSessionData(sessionId, {
      messageTree: messages,
      hasActiveSubagents: saved.has_active_subagents ?? false,
      hasOlderMessages:
        messages === current.messageTree
          ? current.hasOlderMessages
          : page.hasOlderMessages,
      chatState: busy ? "streaming" : "input",
      sendAcknowledged:
        currentStreamId === undefined
          ? undefined
          : Promise.resolve(currentStreamId),
      readerFinished: undefined,
      regenerationState: null,
      streamingStartTime: busy ? Date.now() : undefined,
      selectedNodeIdForDocDisplay:
        selectedMessageId === undefined
          ? null
          : (messages.get(selectedMessageId)?.nodeId ?? null),
      uncaughtError:
        current.uncaughtError === errorMessage ? null : current.uncaughtError,
    });
    if (currentStreamId !== undefined && response?.type === "assistant") {
      void resumeChatSession({
        sessionId,
        streamId: currentStreamId,
        messageMap: messages,
        controller,
        errorMessage,
      });
    } else if (busy) {
      void settleChatSession({
        sessionId,
        controller,
        errorMessage,
        mode: "recovery",
      });
    }
  } catch (error) {
    if (!ownsRefresh()) return;
    console.error("Could not refresh pending chat messages", {
      sessionId,
      error,
    });
    // Let a live reader finish before offering recovery; it still owns Stop.
    await readerFinished;
    if (!ownsRefresh()) return;
    useChatSessionStore.getState().updateSessionData(sessionId, {
      chatState: "unconfirmed",
      uncaughtError: errorMessage,
    });
  }
}

/** Release input only after the same request has finished execution and storage. */
export async function settleChatSession({
  sessionId,
  controller,
  errorMessage,
  mode = "completion",
  refreshHistory = true,
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
    let streamId: number | null | undefined;
    if (sendAcknowledged) {
      try {
        streamId = await sendAcknowledged;
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
    let nextStreamId = await waitForChatResponseEnd(sessionId, streamId);
    if (!ownsSettlement()) return;
    // Incognito keeps output locally, so follow execution without replaying history.
    while (nextStreamId != null && session?.incognito) {
      nextStreamId = await waitForChatResponseEnd(sessionId, nextStreamId);
      if (!ownsSettlement()) return;
    }
    if (nextStreamId != null) {
      await refreshChatSession(sessionId, errorMessage);
      return;
    }
    if (refreshHistory || mode === "recovery") {
      const settled = session?.incognito
        ? undefined
        : await fetchSettledChatSession(sessionId);
      if (!ownsSettlement()) return;
      if (settled?.is_processing || settled?.current_stream) {
        await refreshChatSession(sessionId, errorMessage, settled);
        return;
      }
      const store = useChatSessionStore.getState();
      const current = store.sessions.get(sessionId);
      if (!current) return;
      // Incognito history can contain only usage metadata. Live content stays local.
      if (settled && !settled.incognito) {
        const local = current.messageTree;
        const page = mergeLatestChatPage(settled, current);
        const messageTree = preserveFailedMessages(page.messageTree, local);
        const selectedNodeId = current.selectedNodeIdForDocDisplay;
        const selectedMessageId =
          selectedNodeId == null
            ? undefined
            : local.get(selectedNodeId)?.messageId;
        const latestType = getLatestMessageChain(messageTree).at(-1)?.type;
        store.updateSessionData(sessionId, {
          messageTree,
          hasActiveSubagents: settled.has_active_subagents ?? false,
          hasOlderMessages:
            messageTree === local
              ? current.hasOlderMessages
              : page.hasOlderMessages,
          uncaughtError:
            latestType === "assistant" || latestType === "error"
              ? null
              : current.uncaughtError,
          selectedNodeIdForDocDisplay:
            messageTree === local
              ? (selectedNodeId ?? null)
              : selectedMessageId === undefined
                ? null
                : (messageTree.get(selectedMessageId)?.nodeId ?? null),
        });
      } else {
        // Content-free history cannot close a lost stream. Confirmed idle can.
        const latest = getLatestMessageChain(current.messageTree).at(-1);
        if (
          (latest?.type === "assistant" ||
            (latest?.type === "error" && latest.packets.length > 0)) &&
          !latest.packets.some((packet) => packet.obj.type === "stop")
        ) {
          const packets: Message["packets"] = [
            ...latest.packets,
            {
              placement: { turn_index: 0, tab_index: 0 },
              obj: { type: "stop" },
            },
          ];
          const messageTree = new Map(current.messageTree);
          messageTree.set(latest.nodeId, {
            ...latest,
            packets,
            packetCount: packets.length,
          });
          store.updateSessionMessageTree(sessionId, messageTree);
        }
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
  } catch (error) {
    if (!ownsSettlement()) return;
    console.error("Could not confirm chat completion", error);
    const store = useChatSessionStore.getState();
    store.updateChatState(sessionId, "unconfirmed");
    store.setUncaughtError(sessionId, errorMessage);
  }
}

// A stream has one replay reader even if navigation and queue refresh overlap.
const resumingStreams = new Set<number>();

interface ResumeChatSessionOptions {
  sessionId: string;
  controller: AbortController;
  errorMessage: string;
  mode?: "completion" | "recovery";
  streamId: number;
  messageMap: Map<number, Message>;
}

/** Attach to output produced without this browser's original send request. */
export async function resumeChatSession({
  sessionId,
  streamId,
  messageMap,
  controller,
  errorMessage,
  mode = "completion",
}: ResumeChatSessionOptions): Promise<void> {
  const retained = getMessageByMessageId(messageMap, streamId);
  if (!retained || resumingStreams.has(streamId)) {
    return;
  }
  const node = { ...retained };
  // Added and deleted in this function only, so an entry can never
  // outlive its tail.
  resumingStreams.add(streamId);
  let resolveReaderFinished: () => void = () => {};
  const readerFinished = new Promise<void>((resolve) => {
    resolveReaderFinished = resolve;
  });
  useChatSessionStore.getState().updateSessionData(sessionId, {
    readerFinished,
    sendAcknowledged: Promise.resolve(streamId),
  });
  const accumulated: Packet[] = [...node.packets];
  let restoring = true;
  let pendingRestore: Message | undefined;
  // Keep replay attached across navigation without changing the selected chat.
  const ownsStream = () => {
    const session = useChatSessionStore.getState().sessions.get(sessionId);
    return (
      session !== undefined &&
      session.abortController === controller &&
      session.chatState !== "input"
    );
  };
  const publishResponse = (response: Message) => {
    if (!ownsStream()) return;
    messageMap.set(response.nodeId, response);
    useChatSessionStore
      .getState()
      .updateSessionMessageTree(sessionId, new Map(messageMap));
  };
  const abortController = new AbortController();
  try {
    for await (const rawPacket of resumeStream(
      sessionId,
      streamId,
      node.replayCursor ?? 0,
      abortController.signal
    )) {
      if (!ownsStream()) {
        return;
      }
      if ("next_cursor" in rawPacket) {
        if (rawPacket.stream_id !== streamId) {
          throw new Error("Replay cursor belongs to another response");
        }
        if (restoring) {
          node.restoredPacketCount = accumulated.length;
          restoring = !rawPacket.replay_complete;
        }
        // Store content and cursor together, only after a complete batch.
        node.replayCursor = rawPacket.next_cursor;
        const response: Message = {
          ...node,
          packets: [...accumulated],
          packetCount: accumulated.length,
        };
        if (restoring) {
          pendingRestore = response;
          continue;
        }
        pendingRestore = undefined;
        publishResponse(response);
        continue;
      }
      if ("error" in rawPacket && rawPacket.error) {
        // Keep the error on its reserved row through readiness retries.
        node.type = "error";
        node.errorMessage = rawPacket.error;
        if (!("message_id" in rawPacket)) {
          node.errorCode = rawPacket.error_code;
          node.stackTrace = rawPacket.stack_trace;
          node.isRetryable = rawPacket.is_retryable ?? true;
          node.errorDetails = rawPacket.details;
        }
        node.is_generating = false;
      }
      if (!("obj" in rawPacket)) {
        continue;
      }
      const packet = rawPacket;
      // Heartbeats are liveness ticks for the ownership check above,
      // not run state — never render them.
      if (packet.obj.type === "chat_heartbeat") {
        continue;
      }
      accumulated.push(packet);
    }
  } catch (error) {
    console.error("Failed to resume in-flight run", { streamId, error });
  } finally {
    abortController.abort();
    try {
      // A lost tail must not discard earlier acknowledged cache batches.
      if (pendingRestore) publishResponse(pendingRestore);
    } finally {
      resumingStreams.delete(streamId);
      resolveReaderFinished();
      void settleChatSession({ sessionId, controller, errorMessage, mode });
    }
  }
}
