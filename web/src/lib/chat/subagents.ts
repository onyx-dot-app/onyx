"use client";

import { createContext, useContext, useEffect, useMemo, useState } from "react";
import useSWR from "swr";
import type { BackendMessage, Message } from "@/app/app/types";
import type { Packet, StreamCursor } from "@/app/app/services/streamingModels";
import { processRawChatHistory } from "@/app/app/services/lib";
import { getLatestMessageChain } from "@/app/app/services/messageTree";
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

/**
 * The path of the agent whose conversation renders: the root in the chat, a
 * subagent in its tab. A spawn names its agent relative to it.
 */
export const SubagentPathContext = createContext("/root");

/**
 * The open chat's agents that the rendering agent spawned with these names,
 * once the agents list holds them; undefined for a name it does not hold,
 * such as in a shared chat.
 */
export function useSpawnedSubagents(
  names: readonly string[]
): (ChatSubagent | undefined)[] {
  const base = useContext(SubagentPathContext);
  const sessionId = useChatSessionStore((state) => state.currentSessionId);
  const { agents } = useChatSubagents(sessionId, false);
  return names.map((name) =>
    sessionId === null
      ? undefined
      : agents.find((agent) => agent.path === `${base}/${name}`)
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

interface SubagentTranscript {
  /** The conversation's latest chain, oldest first. */
  messages: Message[];
  /** The response that streams live, if any. */
  liveResponseId: number | null;
  loading: boolean;
  failed: boolean;
}

/**
 * A subagent's conversation: its saved history, and its running response's
 * packets from the live stream, which the saved packets lag. `streamId` is
 * the agents list's live stream for the agent: a new one reloads the history,
 * which names the stream to follow. The history reloads when the stream ends.
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

  // The agents list names a stream that this history predates
  useEffect(() => {
    if (streamId !== null && streamId !== followed) void mutate();
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
      try {
        for await (const item of followSubagentStream(
          sessionId,
          agentId,
          followed,
          0,
          controller.signal
        )) {
          if (!isPacket(item)) continue;
          const type = item.obj.type;
          if (type === "chat_heartbeat" || type === "replay_end") continue;
          pending.push(item);
          if (frame === null) frame = requestAnimationFrame(flush);
        }
      } catch (failure) {
        if (controller.signal.aborted) return;
        console.warn("The subagent's live stream ended", failure);
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
    const chain = getLatestMessageChain(
      processRawChatHistory(data.messages, data.packets)
    );
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
    liveResponseId,
    loading: isLoading,
    failed: error !== undefined,
  };
}
