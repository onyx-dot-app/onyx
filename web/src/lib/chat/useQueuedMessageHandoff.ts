"use client";

import useSWR from "swr";
import { useChatSessionStore } from "@/app/app/stores/useChatSessionStore";
import { getLatestMessageChain } from "@/app/app/services/messageTree";
import { getUnresolvedMultiModelTurn } from "@/app/app/message/multiModel";
import { SWR_KEYS } from "@/lib/swr-keys";
import type { PendingChatMessage } from "@/lib/chat/types";

/** Preview the next turn during handoff; the server still owns its queue entry. */
export function useQueuedMessageHandoff(
  sessionId: string | null
): PendingChatMessage | null {
  const { data: pending } = useSWR<PendingChatMessage[]>(
    sessionId ? SWR_KEYS.pendingChatMessages(sessionId) : null,
    null
  );
  return useChatSessionStore((state) => {
    const session = sessionId ? state.sessions.get(sessionId) : undefined;
    if (
      !pending?.length ||
      !session ||
      session.incognito ||
      session.uncaughtError ||
      (session.chatState !== "streaming" &&
        session.chatState !== "loading" &&
        session.chatState !== "cancelling")
    ) {
      return null;
    }

    const history = getLatestMessageChain(session.messageTree);
    const response = history.at(-1);
    if (
      response?.type !== "assistant" ||
      getUnresolvedMultiModelTurn(history, session.messageTree)
    ) {
      return null;
    }
    const lastPacket = response.packets?.at(-1)?.obj;
    const status =
      lastPacket?.type === "stop"
        ? lastPacket.response_status
        : response.responseStatus;
    const eligible = pending.filter(
      (message) =>
        !message.id.startsWith("local:") &&
        message.target_response_id === response.messageId
    );
    const next =
      eligible.find((message) => message.delivery === "interrupt") ??
      eligible.find((message) => message.delivery === "queue");
    if (session.chatState === "cancelling" && next?.delivery !== "interrupt") {
      return null;
    }
    if (
      status !== "complete" &&
      !(status === "cancelled" && next?.delivery === "interrupt")
    ) {
      return null;
    }
    return next ?? null;
  });
}
