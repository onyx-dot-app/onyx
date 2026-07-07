// Re-attach to a run still generating server-side when a session is opened cold (the store is
// ephemeral, so a backgrounded/killed app loses the live stream). Mirrors web's resume tail;
// runResumeStream is module-scope so it survives re-renders, resumingRuns dedupes across reopens.
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
  resumeChatMessage,
  StreamHttpError,
} from "@/api/chat/stream";
import { processRawChatHistory } from "@/chat/chatHistory";
import { FLUSH_INTERVAL_MS } from "@/chat/constants";
import { BackendChatSession } from "@/chat/interfaces";
import { getMessageByMessageId, upsertMessages } from "@/chat/messageTree";
import { Packet } from "@/chat/streamingModels";
import { useChatSessionStore } from "@/state/chatSessionStore";
import { useSession } from "@/state/session";

const resumingRuns = new Set<number>();

async function runResumeStream(
  sessionId: string,
  runId: number,
  serverUrl: string | null,
  queryClient: QueryClient,
): Promise<void> {
  const store = useChatSessionStore;
  const data = store.getState().sessions.get(sessionId);
  const node = data
    ? getMessageByMessageId(data.messageTree, runId)
    : undefined;
  // Single-model only: a multi-model run_id is the user message, not an assistant node.
  if (!data || !node || node.type !== "assistant") return;
  // local send owns the stream, or another reopen already resumed this run
  if (resumingRuns.has(runId) || data.abortController) return;
  resumingRuns.add(runId);

  const nodeId = node.nodeId;
  const controller = new AbortController();
  store.getState().setAbortController(sessionId, controller);
  store.getState().updateChatState(sessionId, "streaming");
  // clear the reserved placeholder so it doesn't render above the replayed stream
  store.getState().patchNode(sessionId, nodeId, { message: "", packets: [] });

  // writes are safe only while this session stays focused and unaborted
  const stillCurrent = () =>
    store.getState().currentSessionId === sessionId &&
    !controller.signal.aborted;

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
    for await (const event of resumeChatMessage(
      sessionId,
      0,
      controller.signal,
    )) {
      // re-check focus/abort on every event (heartbeats included) so navigate-away unwinds during
      // quiet phases; heartbeats carry no content, so they aren't rendered
      if (!stillCurrent()) break;
      if (isPacket(event) && !isHeartbeat(event)) {
        pending.push(event);
        scheduleFlush();
      }
    }
  } catch (error) {
    // 404 = nothing to resume (finished/evicted run) — expected, stay quiet. Anything else is a
    // real failure worth surfacing. Either way we settle from the snapshot below.
    if (!(error instanceof StreamHttpError && error.status === 404)) {
      console.warn("resume-stream failed; settling from snapshot", error);
    }
  } finally {
    if (flushTimer) clearTimeout(flushTimer);
    flush();
    resumingRuns.delete(runId);
    store.getState().updateChatState(sessionId, "input");
    // Keep `controller` as an ownership token: a new send replaces it via setAbortController, so
    // stillOurs() tells this resume from a raced-in send (a finished send leaves null ≠ token).
    const stillOurs = () =>
      store.getState().sessions.get(sessionId)?.abortController === controller;
    const wasCurrent = store.getState().currentSessionId === sessionId;

    if (wasCurrent && stillOurs()) {
      // settle from the persisted session, but only while we still own the stream — else a
      // raced-in send would be clobbered by this now-stale snapshot
      try {
        const settled = await getChatSession(sessionId);
        if (stillOurs() && store.getState().currentSessionId === sessionId) {
          store
            .getState()
            .hydrateSession(
              sessionId,
              processRawChatHistory(settled.messages, settled.packets),
            );
          // clear the stale current_run so a remount can't re-resume this finished run
          queryClient.setQueryData(
            QUERY_KEYS.chatSession(serverUrl, sessionId),
            settled,
          );
        }
      } catch {
        // keep whatever streamed in
      }
    }
    if (stillOurs()) {
      store.getState().setAbortController(sessionId, null);
    }
    if (wasCurrent) {
      void queryClient.invalidateQueries({
        queryKey: QUERY_KEYS.chatSessions(serverUrl),
      });
    }
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

  const runId = data?.current_run?.run_id ?? null;

  useEffect(() => {
    if (sessionId == null || runId == null) return;
    void runResumeStream(sessionId, runId, serverUrl, queryClient);
  }, [sessionId, runId, serverUrl, queryClient]);
}
