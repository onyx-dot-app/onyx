import { mutate } from "swr";
import type { BackendChatSession, ChatStream } from "@/app/app/types";
import { chatPageUrl } from "@/lib/chat/pagedSession";
import type { ChatSessionStatus } from "@/lib/chat/types";
import { SWR_KEYS } from "@/lib/swr-keys";

export const CHAT_STATUS_POLL_MS = 1000;

const pendingChecks = new Map<string, Promise<ChatStream | null>>();

/**
 * Wait for this response to release the session; returns the stream of the
 * turn that owns it next, such as a queued turn or a continuation.
 */
export function waitForChatResponseEnd(
  sessionId: string,
  streamId?: number | null
): Promise<ChatStream | null> {
  const key = `${sessionId}:${streamId ?? ""}`;
  const existing = pendingChecks.get(key);
  if (existing) return existing;

  const pending = pollSession(sessionId, streamId).finally(() => {
    pendingChecks.delete(key);
  });
  pendingChecks.set(key, pending);
  return pending;
}

async function pollSession(
  sessionId: string,
  streamId: number | null | undefined
): Promise<ChatStream | null> {
  // A successful busy response confirms live work, regardless of its duration.
  while (true) {
    const status = await readChatSessionStatus(sessionId);
    if (!status.is_processing) return null;
    const next = status.current_stream;
    if (next && next.stream_id !== streamId) return next;
    await new Promise<void>((resolve) =>
      setTimeout(resolve, CHAT_STATUS_POLL_MS)
    );
  }
}

/** One status read, shared with the chat's status subscribers. */
export async function readChatSessionStatus(
  sessionId: string
): Promise<ChatSessionStatus> {
  const response = await fetch(SWR_KEYS.chatSessionStatus(sessionId), {
    cache: "no-store",
    signal: AbortSignal.timeout(10_000),
  });
  if (!response.ok) {
    throw new Error(`Session readiness check failed: ${response.status}`);
  }
  const status: ChatSessionStatus = await response.json();
  void mutate(SWR_KEYS.chatSessionStatus(sessionId), status, {
    revalidate: false,
  });
  if (typeof status.is_processing !== "boolean")
    throw new Error("Session readiness response is invalid");
  return status;
}

/**
 * The chat's latest page, or the page before `beforeMessageId`, read past the
 * HTTP cache. `shared` reads a shared chat (`chatPageUrl`).
 */
export async function fetchSettledChatSession(
  sessionId: string,
  page: { beforeMessageId?: number; shared?: boolean } = {}
): Promise<BackendChatSession> {
  const response = await fetch(chatPageUrl(sessionId, page), {
    cache: "no-store",
    signal: AbortSignal.timeout(10_000),
  });
  if (!response.ok)
    throw new Error(`Session refresh failed: ${response.status}`);
  return response.json();
}
