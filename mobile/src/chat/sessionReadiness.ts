import { getChatSessionStatus, ChatSessionStatus } from "@/api/chat/sessions";
import { isApiError, isAuthError } from "@/api/errors";
import { SESSION_POLL_INTERVAL_MS } from "@/chat/constants";
import { ChatStream } from "@/chat/interfaces";
import { getMessageByMessageId } from "@/chat/messageTree";
import { useChatSessionStore } from "@/state/chatSessionStore";

export type SessionWait =
  // `stale`: the saved session holds what this device does not show, so only a reload shows it.
  // `backgroundWork`: background agents run, or queued input or their results can start a turn;
  // only the saved session shows the requests they open, and the turn starts without a reader.
  | { kind: "idle"; stale: boolean; backgroundWork: boolean }
  // A running stream that the caller follows.
  | { kind: "stream"; stream: ChatStream }
  // The caller no longer owns the session.
  | { kind: "released" };

// Whether the saved session holds what this device does not show: approval requests that opened or
// resolved since the shown load, or a newer response, such as one that started and finished
// between two status reads. The server reports "" while the chat has no approval request, so a
// session with no shown load, such as a chat this device created, has that empty baseline.
export function savedSessionChanged(
  sessionId: string,
  status: ChatSessionStatus,
): boolean {
  const session = useChatSessionStore.getState().sessions.get(sessionId);
  return (
    (status.approvals_version !== undefined &&
      status.approvals_version !== (session?.approvalsVersion ?? "")) ||
    (status.latest_response_id != null &&
      !getMessageByMessageId(
        session?.messageTree ?? new Map(),
        status.latest_response_id,
      ))
  );
}

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
      if (status.is_processing === false)
        return {
          kind: "idle",
          stale: savedSessionChanged(sessionId, status),
          backgroundWork:
            status.has_active_subagents === true ||
            status.has_startable_input === true,
        };
      if (status.is_processing !== true) {
        onUnconfirmed();
      } else if (
        status.current_stream &&
        follows(status.current_stream.stream_id)
      ) {
        return { kind: "stream", stream: status.current_stream };
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
