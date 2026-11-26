"use client";

import { createContext, useContext, useEffect, useMemo, useState } from "react";
import useSWR from "swr";
import type { BackendMessage, Message } from "@/app/app/types";
import type { Packet, StreamCursor } from "@/app/app/services/streamingModels";
import { processRawChatHistory } from "@/app/app/services/lib";
import { useChatSessionStore } from "@/app/app/stores/useChatSessionStore";
import { handleSSEStream } from "@/lib/search/streamingUtils";
import {
  errorHandlingFetcher,
  FetchError,
  skipRetryOnAuthError,
} from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import type { ChatSubagent } from "@/lib/chat/types";
import { useChatSubagents } from "@/lib/chat/hooks";

/** A background agent's saved conversation, with its live stream. */
interface SubagentHistory {
  messages: BackendMessage[];
  packets: Packet[][];
  stream: { stream_id: number; response_ids: number[] } | null;
}

/** An agent's name: the last part of its path. */
export function subagentName(path: string): string {
  return path.slice(path.lastIndexOf("/") + 1);
}

/** Whether the agent's latest run still works or waits. */
export function isLiveSubagent(agent: ChatSubagent): boolean {
  return (
    !agent.stopped_by_user &&
    (agent.status === null ||
      agent.status === "running" ||
      agent.status === "suspended")
  );
}

/** When the agent's latest run started, in epoch milliseconds, if known. */
export function subagentStartedAt(agent: ChatSubagent): number | null {
  const parsed = agent.started_at ? Date.parse(agent.started_at) : NaN;
  return Number.isNaN(parsed) ? null : parsed;
}

/**
 * The path of the agent whose conversation renders: the root in the chat, a
 * subagent in its tab. A spawn names its agent relative to it.
 */
export const SubagentPathContext = createContext("/root");

/**
 * Whether the page shows subagent tabs: the chat page's right panel does; the
 * extension's has only Sources, so it opens no agent. Agent status still
 * loads there.
 */
export const SubagentTabsContext = createContext(true);

/**
 * The open chat's agents that the rendering agent spawned with these names,
 * once the agents list holds them; undefined for an empty name, a name it
 * does not hold (such as in a shared chat).
 */
export function useSpawnedSubagents(
  names: readonly string[]
): (ChatSubagent | undefined)[] {
  const base = useContext(SubagentPathContext);
  const sessionId = useChatSessionStore((state) => state.currentSessionId);
  const { agents } = useChatSubagents(sessionId, false);
  return names.map((name) =>
    name ? agents.find((agent) => agent.path === `${base}/${name}`) : undefined
  );
}

/** Opens a subagent's transcript in the open chat's right panel. */
export function openSubagent(agent: Pick<ChatSubagent, "id" | "path">): void {
  useChatSessionStore.getState().updateCurrentRightPanel({
    type: "openAgent",
    agentId: agent.id,
    name: subagentName(agent.path),
  });
}

function isPacket(item: Packet | StreamCursor): item is Packet {
  return "obj" in item;
}

async function* followSubagentStream(
  sessionId: string,
  agentId: string,
  streamId: number,
  cursor: number,
  signal: AbortSignal
): AsyncGenerator<Packet | StreamCursor, void, unknown> {
  const response = await fetch(
    `/api/chat/chat-session/${sessionId}/agents/${agentId}/stream?stream_id=${streamId}&cursor=${cursor}`,
    { signal }
  );
  if (!response.ok)
    throw new FetchError(
      `HTTP error! status: ${response.status}`,
      response.status,
      null
    );
  yield* handleSSEStream<Packet | StreamCursor>(response, signal);
}

const RECONNECT_DELAY_MS = 1000;

interface SubagentTranscript {
  /** The conversation's messages, oldest first. */
  messages: Message[];
  loading: boolean;
  failed: boolean;
}

/**
 * A subagent's conversation: its saved history, and its running response's
 * packets from the live stream, which the saved packets lag. `streamId` is
 * the agents list's live stream for the agent: a new one reloads the history,
 * which names the stream to follow; its end reloads the history too. The
 * history reloads when the stream ends, and a dropped stream resumes from its
 * last cursor.
 */
export function useSubagentTranscript(
  sessionId: string,
  agentId: string,
  streamId: number | null
): SubagentTranscript {
  const { data, error, isLoading, mutate } = useSWR<SubagentHistory, Error>(
    SWR_KEYS.chatSubagentHistory(sessionId, agentId),
    errorHandlingFetcher,
    { onErrorRetry: skipRetryOnAuthError, revalidateOnFocus: false }
  );
  const stream = data?.stream ?? null;
  const followed = stream?.stream_id ?? null;
  const liveResponseId = stream?.response_ids[0] ?? null;

  // The agents list names another stream, or none once the agent ended
  useEffect(() => {
    if (streamId !== followed) void mutate();
  }, [streamId, followed, mutate]);

  const [live, setLive] = useState<{ streamId: number; packets: Packet[] }>({
    streamId: 0,
    packets: [],
  });
  useEffect(() => {
    if (followed === null) return;
    const controller = new AbortController();
    let pending: Packet[] = [];
    let frame: number | null = null;
    // Packets land once per frame, as the chat's own stream does
    const flush = () => {
      frame = null;
      const batch = pending;
      pending = [];
      setLive((current) =>
        current.streamId === followed
          ? { streamId: followed, packets: [...current.packets, ...batch] }
          : { streamId: followed, packets: batch }
      );
    };
    setLive({ streamId: followed, packets: [] });
    void (async () => {
      let cursor = 0;
      let stopped = false;
      // Until the stream sends its stop, or no longer serves this stream
      while (!stopped && !controller.signal.aborted) {
        // The stream sends a cursor after each batch of packets. A batch
        // lands with its cursor, so a drop before it cannot repeat packets
        let batch: Packet[] = [];
        try {
          for await (const item of followSubagentStream(
            sessionId,
            agentId,
            followed,
            cursor,
            controller.signal
          )) {
            if (!isPacket(item)) {
              cursor = item.next_cursor;
              if (batch.length > 0) {
                pending.push(...batch);
                if (batch.some((packet) => packet.obj.type === "stop"))
                  stopped = true;
                batch = [];
                if (frame === null) frame = requestAnimationFrame(flush);
              }
              continue;
            }
            const type = item.obj.type;
            if (type === "chat_heartbeat" || type === "replay_end") continue;
            batch.push(item);
          }
        } catch (failure) {
          if (controller.signal.aborted) return;
          if (failure instanceof FetchError && failure.status === 404) break;
          console.warn("The subagent's live stream dropped", failure);
        }
        if (!stopped)
          await new Promise((resolve) =>
            setTimeout(resolve, RECONNECT_DELAY_MS)
          );
      }
      if (controller.signal.aborted) return;
      if (frame !== null) cancelAnimationFrame(frame);
      flush();
      // The saved response replaces the stream
      void mutate();
    })();
    return () => {
      controller.abort();
      if (frame !== null) cancelAnimationFrame(frame);
    };
  }, [sessionId, agentId, followed, mutate]);

  const messages = useMemo(() => {
    if (!data) return [];
    // Each message the parent sends starts a reply that no earlier reply
    // links to as its latest child, so the conversation reads in order
    const chain = [
      ...processRawChatHistory(data.messages, data.packets).values(),
    ].sort((a, b) => (a.messageId ?? 0) - (b.messageId ?? 0));
    const streamed = live.streamId === followed ? live.packets : [];
    if (liveResponseId === null || streamed.length === 0) return chain;
    return chain.map((message) =>
      message.messageId === liveResponseId
        ? { ...message, packets: streamed }
        : message
    );
  }, [data, live, followed, liveResponseId]);

  return {
    messages,
    loading: isLoading,
    failed: error !== undefined,
  };
}
