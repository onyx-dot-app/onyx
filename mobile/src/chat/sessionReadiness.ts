import { getChatSession, getChatSessionStatus } from "@/api/chat/sessions";
import { isApiError, isAuthError } from "@/api/errors";
import { SESSION_POLL_INTERVAL_MS } from "@/chat/constants";
import { BackendChatSession, ChatStream } from "@/chat/interfaces";

export type SessionWait =
  // `approvalsChanged`: a tool approval request opened or resolved since the last session load or
  // status read, so only a reload of the saved session shows it. `agentsRunning`: background agents
  // run, and only the saved session shows the requests they open.
  | { kind: "idle"; approvalsChanged: boolean; agentsRunning: boolean }
  // A running stream that the caller follows.
  | { kind: "stream"; stream: ChatStream }
  // The caller no longer owns the session.
  | { kind: "released" };

// The last `approvals_version` each session's load or status reported.
const approvalsVersions = new Map<string, string>();

// Whether approvals changed since the version this device last saw.
export function approvalsChangedSince(
  sessionId: string,
  version: string | undefined,
): boolean {
  if (version === undefined) return false;
  const seen = approvalsVersions.get(sessionId);
  approvalsVersions.set(sessionId, version);
  return seen !== undefined && seen !== version;
}

// A session load is the baseline that later status reads compare against.
export async function loadChatSession(
  sessionId: string,
): Promise<BackendChatSession> {
  const session = await getChatSession(sessionId);
  if (session.approvals_version !== undefined)
    approvalsVersions.set(sessionId, session.approvals_version);
  return session;
}

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
      approvalsChanged ||= approvalsChangedSince(
        sessionId,
        status.approvals_version,
      );
      if (status.is_processing === false)
        return {
          kind: "idle",
          approvalsChanged,
          agentsRunning: status.has_active_subagents === true,
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
