import { getChatSessionStatus } from "@/api/chat/sessions";
import { isApiError, isAuthError } from "@/api/errors";

export const SESSION_POLL_INTERVAL_MS = 1000;

export type SessionWait =
  | { kind: "idle" }
  // A running stream that the caller follows.
  | { kind: "stream"; streamId: number }
  // The caller no longer owns the session.
  | { kind: "released" };

// Delivery can end before saving completes. Only the server can confirm readiness.
// Returns early when the server runs a stream that `follows` accepts.
export async function waitForSessionIdle(
  sessionId: string,
  stillOurs: () => boolean,
  onUnconfirmed: () => void,
  follows: (streamId: number) => boolean = () => false,
): Promise<SessionWait> {
  while (stillOurs()) {
    try {
      const status = await getChatSessionStatus(sessionId);
      if (!stillOurs()) return { kind: "released" };
      if (status.is_processing === false) return { kind: "idle" };
      if (status.is_processing !== true) {
        onUnconfirmed();
      } else {
        const streamId = status.current_stream?.stream_id;
        if (streamId !== undefined && follows(streamId)) {
          return { kind: "stream", streamId };
        }
      }
    } catch (error) {
      if (!stillOurs()) return { kind: "released" };
      if (isAuthError(error) || (isApiError(error) && error.status === 404)) {
        throw error;
      }
      onUnconfirmed();
    }
    await new Promise((resolve) =>
      setTimeout(resolve, SESSION_POLL_INTERVAL_MS),
    );
  }
  return { kind: "released" };
}
