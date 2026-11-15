// Reconnect to server output while the session is open. Server readiness gates the next send.
import { useEffect } from "react";
import {
  QueryClient,
  skipToken,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

import { QUERY_KEYS } from "@/api/query-keys";
import { getChatSession } from "@/api/chat/sessions";
import {
  isHeartbeat,
  isPacket,
  isStreamCursor,
  isStreamError,
  resumeChatMessage,
  StreamHttpError,
} from "@/api/chat/stream";
import {
  SESSION_POLL_INTERVAL_MS,
  waitForSessionIdle,
} from "@/chat/sessionReadiness";
import { processRawChatHistory } from "@/chat/chatHistory";
import { FLUSH_INTERVAL_MS } from "@/chat/constants";
import { BackendChatSession, ChatStream } from "@/chat/interfaces";
import {
  getLatestMessageChain,
  getMessageByMessageId,
  upsertMessages,
} from "@/chat/messageTree";
import { Packet, PacketType, StopReason } from "@/chat/streamingModels";
import { useChatSessionStore } from "@/state/chatSessionStore";
import { useSession } from "@/state/session";
import { toast } from "@/hooks/useToast";

// Controllers of running recoveries, whoever started them. The open chat's
// useChatSessionController aborts and releases them when the user leaves.
const recoveries = new WeakSet<AbortController>();

// Follows a live run until the server is idle, then settles from the saved session. With no
// stream, it reads status for one and otherwise settles.
export async function recoverChatSession(
  sessionId: string,
  initialStream: ChatStream | null,
  serverUrl: string | null,
  queryClient: QueryClient,
  controller: AbortController,
): Promise<void> {
  const store = useChatSessionStore;
  const data = store.getState().sessions.get(sessionId);
  if (!data || data.abortController) return;
  if (initialStream === null && data.chatState === "input") return;

  store.getState().setAbortController(sessionId, controller);
  recoveries.add(controller);
  // Stop targets the stream this recovery follows.
  if (initialStream !== null)
    store.getState().setStreamId(sessionId, initialStream.stream_id);
  const stillOurs = () =>
    store.getState().sessions.get(sessionId)?.abortController === controller;
  const stillOpen = () =>
    stillOurs() && store.getState().currentSessionId === sessionId;
  // writes are safe only while this session stays focused and unaborted
  const stillCurrent = () => stillOpen() && !controller.signal.aborted;
  const onUnconfirmed = () =>
    store.getState().updateChatState(sessionId, "unconfirmed");
  // The one response a stream writes. A multi-model turn settles from the saved session.
  const responseOf = (stream: ChatStream | null) =>
    stream?.response_ids.length === 1 ? stream.response_ids[0] : undefined;
  // The response whose local failure the settle keeps.
  const initialResponse = responseOf(initialStream);
  let node =
    initialResponse !== undefined
      ? getMessageByMessageId(data.messageTree, initialResponse)
      : getLatestMessageChain(data.messageTree).at(-1);
  let stream = initialStream;
  // Where a reattach to `stream` continues, so no packet arrives twice. It belongs to that stream id.
  let cursor = 0;
  // A replay from the start holds its packets until it reaches the end of the output that
  // existed when it began, so a replay that fails partway keeps what this device shows.
  let restored = false;
  let replay: Packet[] = [];
  try {
    while (true) {
      // "lost": delivery ended before the run's stop, so a paced reattach follows. "noBuffer":
      // resume-stream answered 404, so only a new stream is followed.
      let end: "finished" | "lost" | "noBuffer" = "noBuffer";
      // The stream ended while the response waits for approval decisions.
      let paused = false;
      const responseId = responseOf(stream);
      if (stream !== null && responseId !== undefined && stillCurrent()) {
        const streamId = stream.stream_id;
        let target = getMessageByMessageId(
          store.getState().sessions.get(sessionId)?.messageTree ?? new Map(),
          responseId,
        );
        if (!target) {
          // A response this device has not seen: load it, so its output and requests show.
          try {
            const saved = await getChatSession(sessionId);
            if (stillCurrent()) {
              const messages = processRawChatHistory(
                saved.messages,
                saved.packets,
              );
              store.getState().hydrateSession(sessionId, messages);
              target = getMessageByMessageId(messages, responseId);
            }
          } catch (error) {
            console.warn("Could not load the running response", error);
            end = "lost";
          }
        }
        // An error already ended local delivery; reopening still needs to confirm server readiness.
        if (target?.type === "error") {
          node = target;
          end = "finished";
        }
        if (target?.type === "assistant" && stillCurrent()) {
          node = target;
          const nodeId = target.nodeId;
          store.getState().updateChatState(sessionId, "streaming");
          // A client that never saw the run's start times it from here (web shows no timer at all here).
          if (target.streamingStartedAt === undefined) {
            store
              .getState()
              .patchNode(sessionId, nodeId, { streamingStartedAt: Date.now() });
          }
          // Packets after the last cursor. A reattach delivers them again, so they wait for it.
          let batch: Packet[] = [];
          let batchStop: Packet | null = null;
          let pending: Packet[] = [];
          // The finished replay replaces the node's packets instead of extending them.
          let replacing = false;
          let flushTimer: ReturnType<typeof setTimeout> | null = null;
          let stopped = false;
          let errored = false;
          let missing = false;

          const flush = () => {
            if (pending.length === 0 && !replacing) return;
            const current = store.getState().sessions.get(sessionId);
            const latest = current?.messageTree.get(nodeId);
            if (!stillCurrent() || !current || !latest) {
              pending = [];
              return;
            }
            const updated = replacing
              ? { ...latest, message: "", packets: pending }
              : { ...latest, packets: [...latest.packets, ...pending] };
            replacing = false;
            pending = [];
            store
              .getState()
              .updateSessionTree(
                sessionId,
                upsertMessages(current.messageTree, [updated], false),
              );
          };

          try {
            for await (const event of resumeChatMessage(
              sessionId,
              streamId,
              cursor,
              controller.signal,
            )) {
              // re-check focus/abort on every event (heartbeats included) so navigate-away unwinds during quiet phases
              if (!stillCurrent()) break;
              if (isStreamCursor(event)) {
                cursor = event.next_cursor;
                if (batchStop?.obj.type === PacketType.STOP) {
                  stopped = true;
                  paused =
                    batchStop.obj.stop_reason === StopReason.AWAITING_APPROVAL;
                }
                batchStop = null;
                if (restored) {
                  pending.push(...batch);
                } else {
                  replay.push(...batch);
                  if (event.replay_complete) {
                    restored = true;
                    replacing = true;
                    pending = replay;
                    replay = [];
                  }
                }
                batch = [];
                if (restored && !flushTimer) {
                  flushTimer = setTimeout(() => {
                    flushTimer = null;
                    flush();
                  }, FLUSH_INTERVAL_MS);
                }
                continue;
              }
              if (isStreamError(event)) {
                // Errored run: show it immediately rather than waiting on (or getting stuck if it fails)
                // the snapshot settle below. Matches the live-send path in useChatController.
                console.warn("resume-stream received a backend error", {
                  sessionId,
                  errorCode: event.error_code ?? null,
                  error: event.error,
                });
                errored = true;
                if (restored) pending.push(...batch);
                flush();
                store.getState().patchNode(sessionId, nodeId, {
                  type: "error",
                  message: event.error,
                  errorCode: event.error_code ?? null,
                });
                break;
              }
              if (isPacket(event) && !isHeartbeat(event)) {
                batch.push(event);
                if (event.obj.type === PacketType.STOP) batchStop = event;
              }
            }
          } catch (error) {
            // 404 = this stream has no buffer (finished/evicted run): expected, stay quiet.
            if (!controller.signal.aborted) {
              if (error instanceof StreamHttpError && error.status === 404) {
                missing = true;
              } else {
                console.warn("resume-stream failed", error);
              }
            }
          } finally {
            if (flushTimer) clearTimeout(flushTimer);
            flush();
          }
          // Only a 404 means no buffer. A clean end before the stop, a network error, a 5xx or a
          // 429 reattach; the status poll reports an auth failure.
          end = errored || stopped ? "finished" : missing ? "noBuffer" : "lost";
          // The wait is not stream time; a continuation restarts the timer.
          if (paused && stillCurrent()) {
            store
              .getState()
              .patchNode(sessionId, nodeId, { streamingStartedAt: undefined });
          }
        }
      }
      if (!stillOurs()) return;
      store.getState().updateChatState(sessionId, "settling");
      const followed = stream?.stream_id;
      const wait = await waitForSessionIdle(
        sessionId,
        stillOpen,
        onUnconfirmed,
        // After a confirmed Stop only idle ends the wait.
        (next) =>
          !controller.signal.aborted && (end === "lost" || next !== followed),
      );
      if (wait.kind === "released") return;
      if (wait.kind === "idle") break;
      if (wait.stream.stream_id === followed) {
        // Paces reattaching to a stream whose connection keeps failing.
        await new Promise((resolve) =>
          setTimeout(resolve, SESSION_POLL_INTERVAL_MS),
        );
      } else {
        store.getState().setStreamId(sessionId, wait.stream.stream_id);
        cursor = 0;
        restored = false;
        replay = [];
      }
      stream = wait.stream;
    }
    if (!stillOpen()) return;

    try {
      const settled = await getChatSession(sessionId);
      if (!stillOpen()) return;
      const current = node
        ? store.getState().sessions.get(sessionId)?.messageTree.get(node.nodeId)
        : undefined;
      const messages = processRawChatHistory(settled.messages, settled.packets);
      const saved =
        node?.messageId !== undefined
          ? getMessageByMessageId(messages, node.messageId)
          : undefined;
      const hasSavedAnswer =
        saved?.type === "assistant" &&
        (saved.responseStatus === undefined
          ? saved.message.length > 0 || saved.files.length > 0
          : saved.responseStatus === "complete" ||
            saved.responseStatus === "limit" ||
            saved.responseStatus === "cancelled");
      // Reserved fallback text is not a saved answer; saved failures remain authoritative.
      if (
        current?.type === "error" &&
        saved &&
        saved.type !== "error" &&
        !hasSavedAnswer
      ) {
        messages.set(saved.nodeId, {
          ...saved,
          type: "error",
          message: current.message,
          errorCode: current.errorCode,
        });
      }
      // A failed send without a saved response must retain its question and error for retry.
      if (current?.type !== "error" || saved) {
        store.getState().hydrateSession(sessionId, messages);
      }
      queryClient.setQueryData(
        QUERY_KEYS.chatSession(serverUrl, sessionId),
        settled,
      );
    } catch (error) {
      console.warn("resume-stream could not load saved history", error);
      if (!stillOpen()) return;
      store.getState().updateChatState(sessionId, "unconfirmed");
      toast.error(
        "Could not refresh saved messages. Reopen this conversation to retry.",
      );
      return;
    }
    if (!stillOpen()) return;
    store.getState().updateChatState(sessionId, "input");
    void queryClient.invalidateQueries({
      queryKey: QUERY_KEYS.chatSessions(serverUrl),
    });
  } catch (error) {
    if (!stillOpen()) return;
    console.warn("Could not confirm chat readiness", error);
    store.getState().updateChatState(sessionId, "unconfirmed");
    toast.error(
      error instanceof Error
        ? error.message
        : "This conversation is unavailable.",
    );
  } finally {
    if (stillOurs()) store.getState().setAbortController(sessionId, null);
  }
}

// Reopening retries unresolved readiness even when the server has no stream left to replay.
export function useChatSessionController(sessionId: string | null): void {
  const serverUrl = useSession((state) => state.serverUrl);
  const queryClient = useQueryClient();

  const { data } = useQuery<BackendChatSession>({
    queryKey: QUERY_KEYS.chatSession(serverUrl, sessionId ?? "new"),
    // read-only observer: useChatController owns the fetch + hydration. skipToken keeps this
    // type-safe (no non-null assertion) when there's no session.
    queryFn: sessionId ? () => getChatSession(sessionId) : skipToken,
    enabled: false,
  });

  // Structural sharing keeps this reference while the stream stays the same.
  const currentStream = data?.current_stream ?? null;

  useEffect(() => {
    if (sessionId == null) return;
    void recoverChatSession(
      sessionId,
      currentStream,
      serverUrl,
      queryClient,
      new AbortController(),
    );
    return () => {
      // The session's recovery may be one a send started; a send itself keeps running.
      const store = useChatSessionStore.getState();
      const owner = store.sessions.get(sessionId)?.abortController;
      if (!owner || !recoveries.has(owner)) return;
      owner.abort();
      // Release the reader immediately; reopening must not wait for a blocked read or status call.
      store.updateChatState(sessionId, "settling");
      store.setAbortController(sessionId, null);
    };
  }, [sessionId, currentStream, serverUrl, queryClient]);
}
