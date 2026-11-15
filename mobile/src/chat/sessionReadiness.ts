import { getChatSessionStatus } from "@/api/chat/sessions";
import { isApiError, isAuthError } from "@/api/errors";
import { ChatStream } from "@/chat/interfaces";

export const SESSION_POLL_INTERVAL_MS = 1000;

export type SessionWait =
  // `approvalsChanged`: a tool approval request opened or resolved since the last status read,
  // so only a reload of the saved session shows it.
  | { kind: "idle"; approvalsChanged: boolean }
  // A running stream that the caller follows.
  | { kind: "stream"; stream: ChatStream }
  // The caller no longer owns the session.
  | { kind: "released" };

// The last `approvals_version` each session's status reported.
const approvalsVersions = new Map<string, string>();

// Delivery can end before saving completes. Only the server can confirm readiness.
// Returns early when the server runs a stream that `follows` accepts.
export async function waitForSessionIdle(
  sessionId: string,
  stillOurs: () => boolean,
  onUnconfirmed: () => void,
  follows: (streamId: number) => boolean = () => false,
): Promise<SessionWait> {
  let approvalsChanged = false;
  while (stillOurs()) {
    try {
      const status = await getChatSessionStatus(sessionId);
      if (!stillOurs()) return { kind: "released" };
      if (status.approvals_version !== undefined) {
        const seen = approvalsVersions.get(sessionId);
        approvalsChanged ||=
          seen !== undefined && seen !== status.approvals_version;
        approvalsVersions.set(sessionId, status.approvals_version);
      }
      if (status.is_processing === false)
        return { kind: "idle", approvalsChanged };
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
