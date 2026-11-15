import type { BackendChatSession, ChatStream, Message } from "@/app/app/types";
import { resumeStream } from "@/app/app/services/lib";
import {
  getLatestMessageChain,
  getLatestTurn,
  getMessageByMessageId,
} from "@/app/app/services/messageTree";
import { FetchError } from "@/lib/fetcher";
import { mergeLatestChatPage } from "@/lib/chat/pagedSession";
import type { ChatHistoryPage } from "@/lib/chat/types";
import type { Packet } from "@/app/app/services/streamingModels";
import { useChatSessionStore } from "@/app/app/stores/useChatSessionStore";
import {
  CHAT_STATUS_POLL_MS,
  fetchSettledChatSession,
  readChatSessionStatus,
  waitForChatResponseEnd,
} from "@/lib/chat/sessionReadiness";

interface SettleChatSessionOptions {
  sessionId: string;
  controller: AbortController;
  errorMessage: string;
  mode?: "completion" | "recovery";
  refreshHistory?: boolean;
  /** Resume returned 404: the stream has no buffer, so it cannot reattach. */
  streamUnavailable?: boolean;
}

/** The rows a stream writes, in model-index order; null when one is missing. */
function streamResponses(
  tree: Map<number, Message>,
  stream: ChatStream
): Message[] | null {
  const responses: Message[] = [];
  for (const responseId of stream.response_ids) {
    const response = getMessageByMessageId(tree, responseId);
    if (response?.type !== "assistant" && response?.type !== "error")
      return null;
    responses.push(response);
  }
  return responses.length > 0 ? responses : null;
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
      // A finished run waits for nothing, so its local stop is real.
      streamLost:
        node.streamLost &&
        (savedNode.responseStatus === "running" ||
          savedNode.responseStatus === "suspended"),
    });
  }
  return saved;
}

/**
 * Saved history ready to display, with the live stream a reader should replay.
 * Rows that hold a replay cursor of the same stream keep the output this
 * browser already received; other rows replay from the stream's start.
 */
export function prepareSavedChat(
  saved: Map<number, Message>,
  local: Map<number, Message> | undefined,
  stream: ChatStream | null | undefined
): { messageTree: Map<number, Message>; replayStream: ChatStream | null } {
  const responses = stream ? streamResponses(saved, stream) : null;
  if (!stream || !responses) return { messageTree: saved, replayStream: null };
  const localResponses = local ? streamResponses(local, stream) : null;
  const retained = localResponses?.every(
    (response) => response.replay?.streamId === stream.stream_id
  )
    ? localResponses
    : undefined;
  const messageTree = new Map(saved);
  responses.forEach((node, index) => {
    const kept = retained?.[index];
    if (kept)
      messageTree.set(node.nodeId, {
        ...kept,
        nodeId: node.nodeId,
        parentNodeId: node.parentNodeId,
        childrenNodeIds: node.childrenNodeIds,
        latestChildNodeId: node.latestChildNodeId,
      });
    else
      messageTree.set(node.nodeId, {
        ...node,
        // Replay rebuilds a row this client marked failed when its stream dropped.
        ...(node.streamLost && {
          type: "assistant",
          errorMessage: undefined,
          errorCode: undefined,
          stackTrace: undefined,
          isRetryable: undefined,
          errorDetails: undefined,
          streamLost: undefined,
        }),
        message: "",
        packets: [],
        packetCount: 0,
        replay: undefined,
      });
  });
  return { messageTree, replayStream: stream };
}

/**
 * Merge the latest saved page into local history. Local failed turns stay for
 * retry, and the sources panel stays on the selected response.
 */
function mergeSavedHistory(
  saved: BackendChatSession,
  current: ChatHistoryPage & { selectedNodeIdForDocDisplay: number | null }
): ChatHistoryPage & { selectedNodeIdForDocDisplay: number | null } {
  const page = mergeLatestChatPage(saved, current);
  const messageTree = preserveFailedMessages(
    page.messageTree,
    current.messageTree
  );
  const selected = current.selectedNodeIdForDocDisplay;
  if (messageTree === current.messageTree)
    return {
      messageTree,
      hasOlderMessages: current.hasOlderMessages,
      selectedNodeIdForDocDisplay: selected,
    };
  const selectedMessageId =
    selected === null
      ? undefined
      : current.messageTree.get(selected)?.messageId;
  return {
    messageTree,
    hasOlderMessages: page.hasOlderMessages,
    selectedNodeIdForDocDisplay:
      selectedMessageId === undefined
        ? null
        : (messageTree.get(selectedMessageId)?.nodeId ?? null),
  };
}

// One refresh per session, so overlapping status checks share it.
const refreshingSessions = new Map<string, Promise<void>>();

/** Load and follow a turn the server started while this session had no reader. */
export function refreshChatSession(
  sessionId: string,
  errorMessage: string,
  savedSession?: BackendChatSession
): Promise<void> {
  const existing = refreshingSessions.get(sessionId);
  if (existing) return existing;
  const refresh = (async () => {
    const session = useChatSessionStore.getState().sessions.get(sessionId);
    if (!session || session.incognito) return;
    const controller = session.abortController;
    // A send that starts during the fetch owns the session.
    const ownsRefresh = () =>
      useChatSessionStore.getState().sessions.get(sessionId)
        ?.abortController === controller;
    try {
      const saved = savedSession ?? (await fetchSettledChatSession(sessionId));
      const store = useChatSessionStore.getState();
      const current = store.sessions.get(sessionId);
      if (!current || !ownsRefresh()) return;
      const merged = mergeSavedHistory(saved, current);
      const stream = saved.current_stream ?? null;
      const { messageTree, replayStream } = prepareSavedChat(
        merged.messageTree,
        current.messageTree,
        stream
      );
      const busy = Boolean(saved.is_processing || saved.current_stream);
      store.updateSessionData(sessionId, {
        messageTree,
        hasOlderMessages: merged.hasOlderMessages,
        selectedNodeIdForDocDisplay: merged.selectedNodeIdForDocDisplay,
        approvalsVersion: saved.approvals_version,
        chatState: busy ? "streaming" : "input",
        sendAcknowledged: stream ? Promise.resolve(stream) : undefined,
        readerFinished: undefined,
        regenerationState: null,
        streamingStartTime: busy ? Date.now() : undefined,
        uncaughtError:
          current.uncaughtError?.error === errorMessage
            ? null
            : current.uncaughtError,
      });
      if (busy)
        void followChatSession({
          sessionId,
          controller,
          errorMessage,
          stream: replayStream,
          messageMap: messageTree,
        });
    } catch (error) {
      if (!ownsRefresh()) return;
      console.error("Could not refresh the chat session", { sessionId, error });
      useChatSessionStore.getState().updateSessionData(sessionId, {
        chatState: "unconfirmed",
        uncaughtError: { error: errorMessage },
      });
    }
  })().finally(() => refreshingSessions.delete(sessionId));
  refreshingSessions.set(sessionId, refresh);
  return refresh;
}

/** Release input only after the same request has finished execution and storage. */
export async function settleChatSession({
  sessionId,
  controller,
  errorMessage,
  mode = "completion",
  refreshHistory = true,
  streamUnavailable = false,
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
    let stream: ChatStream | null | undefined;
    if (sendAcknowledged) {
      try {
        stream = await sendAcknowledged;
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
    // A reader that lost a running stream reattaches: from its saved cursor,
    // or from the start into reset rows. The received rows stay on screen
    // until the replay delivers its first batch.
    const local = useChatSessionStore.getState().sessions.get(sessionId);
    if (
      stream &&
      !streamUnavailable &&
      local &&
      local.chatState !== "cancelling" &&
      streamResponses(local.messageTree, stream)?.some(
        (response) =>
          response.streamLost ||
          !response.packets.some((packet) => packet.obj.type === "stop")
      )
    ) {
      await new Promise<void>((resolve) =>
        setTimeout(resolve, CHAT_STATUS_POLL_MS)
      );
      const status = await readChatSessionStatus(sessionId);
      const current = useChatSessionStore.getState().sessions.get(sessionId);
      if (!current || !ownsSettlement()) return;
      if (
        status.is_processing &&
        status.current_stream?.stream_id === stream.stream_id &&
        current.chatState !== "cancelling"
      ) {
        const { messageTree, replayStream } = prepareSavedChat(
          current.messageTree,
          current.messageTree,
          stream
        );
        if (replayStream) {
          useChatSessionStore.getState().updateSessionData(sessionId, {
            chatState: "streaming",
            uncaughtError:
              current.uncaughtError?.error === errorMessage
                ? null
                : current.uncaughtError,
          });
          void followChatSession({
            sessionId,
            controller,
            errorMessage,
            mode,
            stream: replayStream,
            messageMap: messageTree,
          });
          return;
        }
      }
    }
    let next = await waitForChatResponseEnd(sessionId, stream?.stream_id);
    if (!ownsSettlement()) return;
    // Incognito keeps output locally, so it replays no history. It follows a
    // later stream of its own answers, such as an approved answer's
    // continuation, and waits through other turns. A Stop waits through it.
    while (next && session?.incognito) {
      const local = useChatSessionStore.getState().sessions.get(sessionId);
      if (
        local &&
        local.chatState !== "cancelling" &&
        streamResponses(local.messageTree, next)
      ) {
        followChatStream(sessionId, next, errorMessage);
        return;
      }
      next = await waitForChatResponseEnd(sessionId, next.stream_id);
      if (!ownsSettlement()) return;
    }
    if (next) {
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
        const merged = mergeSavedHistory(settled, current);
        const latestType = getLatestMessageChain(merged.messageTree).at(
          -1
        )?.type;
        store.updateSessionData(sessionId, {
          ...merged,
          approvalsVersion: settled.approvals_version,
          uncaughtError:
            latestType === "assistant" || latestType === "error"
              ? null
              : current.uncaughtError,
        });
      } else {
        // Content-free history cannot close a lost stream. Confirmed idle can.
        const messageTree = new Map(current.messageTree);
        let closed = false;
        for (const response of getLatestTurn(current.messageTree)) {
          const stopped = response.packets.some(
            (packet) => packet.obj.type === "stop"
          );
          if (
            !(
              response.type === "assistant" ||
              (response.type === "error" && response.packets.length > 0)
            ) ||
            (stopped && !response.streamLost)
          )
            continue;
          const packets: Message["packets"] = stopped
            ? response.packets
            : [
                ...response.packets,
                {
                  placement: { turn_index: 0, tab_index: 0 },
                  obj: { type: "stop" },
                },
              ];
          messageTree.set(response.nodeId, {
            ...response,
            packets,
            packetCount: packets.length,
            streamLost: undefined,
          });
          closed = true;
        }
        if (closed) store.updateSessionMessageTree(sessionId, messageTree);
      }
    }
    const store = useChatSessionStore.getState();
    if (store.sessions.get(sessionId)?.uncaughtError?.error === errorMessage) {
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
    store.setUncaughtError(sessionId, { error: errorMessage });
  }
}

// Streams this browser reads: a send's own stream or a replay. A stream has
// one reader even if a send, navigation, refresh and decisions overlap.
const streamReaders = new Set<number>();

/** Claims the stream for one reader; false when another reader has it. */
export function claimStreamReader(streamId: number): boolean {
  if (streamReaders.has(streamId)) return false;
  streamReaders.add(streamId);
  return true;
}

export function releaseStreamReader(streamId: number): void {
  streamReaders.delete(streamId);
}

/**
 * Follows a stream that the server named, such as the continuation of a
 * response after its approval decisions, from its start into its rows. A
 * stream that this browser already reads keeps its reader.
 */
export function followChatStream(
  sessionId: string,
  stream: ChatStream,
  errorMessage: string
): void {
  const store = useChatSessionStore.getState();
  const session = store.sessions.get(sessionId);
  if (
    !session ||
    session.chatState === "cancelling" ||
    streamReaders.has(stream.stream_id)
  )
    return;
  const { messageTree, replayStream } = prepareSavedChat(
    session.messageTree,
    session.messageTree,
    stream
  );
  // A new reader promise ends the ownership of a settlement that still runs.
  store.updateSessionData(sessionId, {
    chatState: "streaming",
    sendAcknowledged: Promise.resolve(stream),
    readerFinished: Promise.resolve(),
    streamingStartTime: Date.now(),
  });
  void followChatSession({
    sessionId,
    controller: session.abortController,
    errorMessage,
    stream: replayStream,
    messageMap: messageTree,
  });
}

interface FollowChatSessionOptions {
  sessionId: string;
  controller: AbortController;
  errorMessage: string;
  mode?: "completion" | "recovery";
  /** The live stream to replay. Null waits for the server without output. */
  stream: ChatStream | null;
  messageMap: Map<number, Message>;
}

/** Attach to a turn that runs without this browser's original send request. */
export async function followChatSession({
  sessionId,
  stream,
  messageMap,
  controller,
  errorMessage,
  mode = "completion",
}: FollowChatSessionOptions): Promise<void> {
  if (stream === null) {
    await settleChatSession({ sessionId, controller, errorMessage, mode });
    return;
  }
  const streamId = stream.stream_id;
  const responses = streamResponses(messageMap, stream)?.map((response) => ({
    ...response,
  }));
  if (!responses || !claimStreamReader(streamId)) {
    return;
  }
  // Each answer of a multi-model turn has its model index in the packets.
  const multiModel = responses.length > 1;
  let resolveReaderFinished: () => void = () => {};
  const readerFinished = new Promise<void>((resolve) => {
    resolveReaderFinished = resolve;
  });
  useChatSessionStore.getState().updateSessionData(sessionId, {
    readerFinished,
    sendAcknowledged: Promise.resolve(stream),
  });
  const accumulated: Packet[][] = responses.map((response) => [
    ...response.packets,
  ]);
  let restoring = true;
  let pendingRestore: Message[] | undefined;
  // Keep replay attached across navigation without changing the selected chat.
  const ownsStream = () => {
    const session = useChatSessionStore.getState().sessions.get(sessionId);
    return (
      session !== undefined &&
      session.abortController === controller &&
      session.chatState !== "input"
    );
  };
  const publishResponses = (nodes: Message[]) => {
    if (!ownsStream()) return;
    for (const node of nodes) messageMap.set(node.nodeId, node);
    useChatSessionStore
      .getState()
      .updateSessionMessageTree(sessionId, new Map(messageMap));
  };
  const abortController = new AbortController();
  // Only a 404 means the stream has no buffer; a new stream can follow it.
  let streamUnavailable = false;
  try {
    for await (const rawPacket of resumeStream(
      sessionId,
      streamId,
      responses[0]!.replay?.streamId === streamId
        ? responses[0]!.replay.cursor
        : 0,
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
          responses.forEach((response, index) => {
            response.restoredPacketCount = accumulated[index]!.length;
          });
          restoring = !rawPacket.replay_complete;
        }
        // Store content and cursor together, only after a complete batch.
        const replay = { streamId, cursor: rawPacket.next_cursor };
        const nodes: Message[] = responses.map((response, index) => ({
          ...response,
          packets: [...accumulated[index]!],
          packetCount: accumulated[index]!.length,
          replay,
        }));
        if (restoring) {
          pendingRestore = nodes;
          continue;
        }
        pendingRestore = undefined;
        publishResponses(nodes);
        continue;
      }
      if ("error" in rawPacket && rawPacket.error) {
        const details =
          "message_id" in rawPacket ? undefined : rawPacket.details;
        const errorModelIndex: unknown = details?.model_index;
        const node = !multiModel
          ? responses[0]
          : typeof errorModelIndex === "number"
            ? responses[errorModelIndex]
            : undefined;
        if (node) {
          // Keep the error on its reserved row through readiness retries.
          node.type = "error";
          node.errorMessage = rawPacket.error;
          if (!("message_id" in rawPacket)) {
            node.errorCode = rawPacket.error_code;
            node.stackTrace = rawPacket.stack_trace;
            node.isRetryable = rawPacket.is_retryable ?? true;
            node.errorDetails = details;
          }
          node.is_generating = false;
        }
      }
      if (!("obj" in rawPacket)) {
        continue;
      }
      const packet = rawPacket;
      // Heartbeats are liveness ticks for the ownership check above, and the
      // replay end marks a position. Neither is run state, so never render them.
      if (
        packet.obj.type === "chat_heartbeat" ||
        packet.obj.type === "replay_end"
      ) {
        continue;
      }
      const modelIndex = packet.placement.model_index;
      if (!multiModel) accumulated[0]!.push(packet);
      // The overall stop has no model and ends every answer.
      else if (modelIndex == null && packet.obj.type === "stop")
        for (const output of accumulated) output.push(packet);
      else accumulated[modelIndex ?? 0]?.push(packet);
    }
  } catch (error) {
    if (error instanceof FetchError && error.status === 404)
      streamUnavailable = true;
    console.error("Failed to resume in-flight run", { streamId, error });
  } finally {
    abortController.abort();
    try {
      // A lost tail must not discard earlier acknowledged cache batches.
      if (pendingRestore) publishResponses(pendingRestore);
    } finally {
      releaseStreamReader(streamId);
      resolveReaderFinished();
      void settleChatSession({
        sessionId,
        controller,
        errorMessage,
        mode,
        streamUnavailable,
      });
    }
  }
}
