import type { BackendChatSession } from "@/app/app/types";
import { chatPageUrl } from "@/lib/chat/pagedSession";

const pendingChecks = new Map<string, Promise<number | null>>();

/** Wait for this response to release the session; another queued turn can own it next. */
export function waitForChatResponseEnd(
  sessionId: string,
  streamId?: number | null
): Promise<number | null> {
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
): Promise<number | null> {
  // A successful busy response confirms live work, regardless of its duration.
  while (true) {
    const response = await fetch(`/api/chat/chat-session/${sessionId}/status`, {
      cache: "no-store",
      signal: AbortSignal.timeout(10_000),
    });
    if (!response.ok) {
      throw new Error(`Session readiness check failed: ${response.status}`);
    }
    const status: Pick<BackendChatSession, "is_processing" | "current_stream"> =
      await response.json();
    if (status.is_processing === false) return null;
    if (status.is_processing !== true)
      throw new Error("Session readiness response is invalid");
    const nextStreamId = status.current_stream?.stream_id;
    if (nextStreamId !== undefined && nextStreamId !== streamId)
      return nextStreamId;
    await new Promise<void>((resolve) => setTimeout(resolve, 1000));
  }
}

export async function fetchSettledChatSession(
  sessionId: string
): Promise<BackendChatSession> {
  const response = await fetch(chatPageUrl(sessionId), {
    cache: "no-store",
    signal: AbortSignal.timeout(10_000),
  });
  if (!response.ok)
    throw new Error(`Session refresh failed: ${response.status}`);
  return response.json();
}
