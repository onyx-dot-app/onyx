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
  isStreamError,
  resumeChatMessage,
  StreamHttpError,
} from "@/api/chat/stream";
import { waitForSessionIdle } from "@/chat/sessionReadiness";
import { processRawChatHistory } from "@/chat/chatHistory";
import { FLUSH_INTERVAL_MS } from "@/chat/constants";
import { BackendChatSession } from "@/chat/interfaces";
import { getMessageByMessageId, upsertMessages } from "@/chat/messageTree";
import { Packet } from "@/chat/streamingModels";
import { useChatSessionStore } from "@/state/chatSessionStore";
import { useSession } from "@/state/session";
import { toast } from "@/hooks/useToast";

async function runResumeStream(
  sessionId: string,
  runId: number,
  serverUrl: string | null,
  queryClient: QueryClient,
  controller: AbortController,
): Promise<void> {
  const store = useChatSessionStore;
  const data = store.getState().sessions.get(sessionId);
  const node = data
    ? getMessageByMessageId(data.messageTree, runId)
    : undefined;
  // Single-model only: a multi-model stream_id is the user message, not an assistant node.
  if (!data || !node || (node.type !== "assistant" && node.type !== "error"))
    return;
  // A local send or another reader already owns this session.
  if (data.abortController) return;

  const nodeId = node.nodeId;
  store.getState().setAbortController(sessionId, controller);
  store.getState().setStreamId(sessionId, runId);
  store
    .getState()
    .updateChatState(
      sessionId,
      node.type === "error" ? "settling" : "streaming",
    );
  // clear the reserved placeholder so it doesn't render above the replayed stream. The timer
  // restarts from here: this client never saw the run's true start (web shows no timer at all here).
  if (node.type === "assistant") {
    store.getState().patchNode(sessionId, nodeId, {
      message: "",
      packets: [],
      streamingStartedAt: Date.now(),
    });
  }

  // writes are safe only while this session stays focused and unaborted
  const stillCurrent = () =>
    store.getState().currentSessionId === sessionId &&
    !controller.signal.aborted &&
    store.getState().sessions.get(sessionId)?.abortController === controller;

  let pending: Packet[] = [];
  let flushTimer: ReturnType<typeof setTimeout> | null = null;

  function flush() {
    if (pending.length === 0) return;
    if (!stillCurrent()) {
      pending = [];
      return;
    }
    const current = store.getState().sessions.get(sessionId);
    const target = current?.messageTree.get(nodeId);
    if (!current || !target) {
      pending = [];
      return;
    }
    const updated = { ...target, packets: [...target.packets, ...pending] };
    pending = [];
    store
      .getState()
      .updateSessionTree(
        sessionId,
        upsertMessages(current.messageTree, [updated], false),
      );
  }

  function scheduleFlush() {
    if (flushTimer) return;
    flushTimer = setTimeout(() => {
      flushTimer = null;
      flush();
    }, FLUSH_INTERVAL_MS);
  }

  try {
    // An error already ended local delivery; reopening still needs to confirm server readiness.
    const stream =
      node.type === "error"
        ? []
        : resumeChatMessage(sessionId, 0, controller.signal);
    for await (const event of stream) {
      // re-check focus/abort on every event (heartbeats included) so navigate-away unwinds during quiet phases
      if (!stillCurrent()) break;
      if (isStreamError(event)) {
        // Errored run: show it immediately rather than waiting on (or getting stuck if it fails)
        // the snapshot settle below. Matches the live-send path in useChatController.
        console.warn("resume-stream received a backend error", {
          sessionId,
          errorCode: event.error_code ?? null,
          error: event.error,
        });
        pending = [];
        if (flushTimer) {
          clearTimeout(flushTimer);
          flushTimer = null;
        }
        store.getState().patchNode(sessionId, nodeId, {
          type: "error",
          message: event.error,
          errorCode: event.error_code ?? null,
        });
        break;
      }
      if (isPacket(event) && !isHeartbeat(event)) {
        pending.push(event);
        scheduleFlush();
      }
    }
  } catch (error) {
    // 404 = nothing to resume (finished/evicted run) — expected, stay quiet. Anything else is a
    // real failure worth surfacing. Either way we settle from the snapshot below.
    if (
      !controller.signal.aborted &&
      !(error instanceof StreamHttpError && error.status === 404)
    ) {
      console.warn("resume-stream failed; settling from snapshot", error);
    }
  } finally {
    if (flushTimer) clearTimeout(flushTimer);
    flush();
  }
  const stillOurs = () =>
    store.getState().sessions.get(sessionId)?.abortController === controller;
  const stillOpen = () =>
    stillOurs() && store.getState().currentSessionId === sessionId;
  if (!stillOurs()) return;
  store.getState().updateChatState(sessionId, "settling");
  try {
    const idle = await waitForSessionIdle(sessionId, stillOpen, () => {
      store.getState().updateChatState(sessionId, "unconfirmed");
    });
    if (!idle || !stillOpen()) return;

    try {
      const settled = await getChatSession(sessionId);
      if (!stillOpen()) return;
      const current = store
        .getState()
        .sessions.get(sessionId)
        ?.messageTree.get(nodeId);
      const messages = processRawChatHistory(settled.messages, settled.packets);
      const saved = getMessageByMessageId(messages, runId);
      const hasSavedAnswer =
        saved?.type === "assistant" &&
        (saved.message.length > 0 || saved.files.length > 0);
      // Final saved answers are authoritative; partial packets alone do not prove a successful save.
      if (current?.type === "error" && saved && !hasSavedAnswer) {
        messages.set(saved.nodeId, {
          ...saved,
          type: "error",
          message: current.message,
          errorCode: current.errorCode,
        });
      }
      store.getState().hydrateSession(sessionId, messages);
      queryClient.setQueryData(
        QUERY_KEYS.chatSession(serverUrl, sessionId),
        settled,
      );
    } catch (error) {
      console.warn("resume-stream could not load saved history", error);
      if (stillOpen())
        toast.error(
          "Could not refresh saved messages. Reopen this conversation to retry.",
        );
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

// Observes the snapshot useChatController fetches (same key → RQ dedups) and re-attaches on a live run.
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

  const runId = data?.current_stream?.stream_id ?? null;

  useEffect(() => {
    if (sessionId == null || runId == null) return;
    const controller = new AbortController();
    void runResumeStream(sessionId, runId, serverUrl, queryClient, controller);
    return () => {
      controller.abort();
      const store = useChatSessionStore.getState();
      if (store.sessions.get(sessionId)?.abortController !== controller) return;
      // Release the reader immediately; reopening must not wait for a blocked read or status call.
      store.updateChatState(sessionId, "settling");
      store.setAbortController(sessionId, null);
    };
  }, [sessionId, runId, serverUrl, queryClient]);
}
