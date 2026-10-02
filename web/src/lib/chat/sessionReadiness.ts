import type { BackendChatSession } from "@/app/app/interfaces";

const pendingChecks = new Map<string, Promise<void>>();

/** Confirm that execution and storage have released this session. */
export function waitForChatSessionIdle(sessionId: string): Promise<void> {
  const existing = pendingChecks.get(sessionId);
  if (existing) return existing;

  const pending = pollSession(sessionId).finally(() => {
    pendingChecks.delete(sessionId);
  });
  pendingChecks.set(sessionId, pending);
  return pending;
}

async function pollSession(sessionId: string): Promise<void> {
  const deadline = Date.now() + 120_000;
  while (Date.now() < deadline) {
    const response = await fetch(`/api/chat/chat-session/${sessionId}/status`, {
      cache: "no-store",
      signal: AbortSignal.timeout(10_000),
    });
    if (!response.ok) {
      throw new Error(`Session readiness check failed: ${response.status}`);
    }
    const status: { is_processing: boolean } = await response.json();
    if (!status.is_processing) return;
    await new Promise<void>((resolve) => setTimeout(resolve, 1000));
  }
  throw new Error("Session readiness check timed out");
}

export async function fetchSettledChatSession(
  sessionId: string
): Promise<BackendChatSession> {
  const response = await fetch(`/api/chat/get-chat-session/${sessionId}`, {
    cache: "no-store",
    signal: AbortSignal.timeout(10_000),
  });
  if (!response.ok)
    throw new Error(`Session refresh failed: ${response.status}`);
  return response.json();
}
