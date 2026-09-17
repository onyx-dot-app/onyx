/**
 * Instructor-side Canvas OAuth flow for the LTI tutor.
 *
 * The tutor runs inside a Canvas iframe whose session cookie is Partitioned,
 * so the Canvas consent screen is opened in a popup and the backend callback
 * (`/auth/lti/canvas-oauth/callback`) reports back via `postMessage` instead
 * of relying on a session. This module owns that popup handshake so both the
 * first-time setup wizard and the knowledge tab's Reconnect button share it.
 */

export const CANVAS_OAUTH_MESSAGE_TYPE = "onyx:lti-canvas-oauth";

export type CanvasOAuthPopupStatus = "success" | "cancelled" | "failed";

export interface CanvasOAuthPopupMessage {
  type: typeof CANVAS_OAUTH_MESSAGE_TYPE;
  status: CanvasOAuthPopupStatus;
  credential_id: number | null;
  detail: string | null;
}

export interface LtiCanvasOAuthConnectResponse {
  credential_id: number;
  auth_url: string;
}

export class CanvasOAuthPopupBlockedError extends Error {
  constructor() {
    super("Popup blocked. Allow popups for this site and try again.");
    this.name = "CanvasOAuthPopupBlockedError";
  }
}

export class CanvasOAuthCancelledError extends Error {
  constructor(detail?: string | null) {
    super(
      detail || "Canvas authorization was cancelled. No changes were made."
    );
    this.name = "CanvasOAuthCancelledError";
  }
}

const POPUP_NAME = "onyx-canvas-oauth";
const POPUP_FEATURES = "width=720,height=820";
const POPUP_CLOSED_POLL_MS = 1000;
// Canvas's consent page can take a moment to redirect back after the popup
// closes itself; wait briefly for the message before treating a closed popup
// as a cancellation.
const POPUP_CLOSED_GRACE_MS = 1500;
const POPUP_TIMEOUT_MS = 10 * 60 * 1000;

export function getErrorDetail(payload: unknown, fallback: string): string {
  if (
    payload &&
    typeof payload === "object" &&
    "detail" in payload &&
    typeof payload.detail === "string"
  ) {
    return payload.detail;
  }
  return fallback;
}

function isCanvasOAuthPopupMessage(
  data: unknown
): data is CanvasOAuthPopupMessage {
  return (
    !!data &&
    typeof data === "object" &&
    "type" in data &&
    data.type === CANVAS_OAUTH_MESSAGE_TYPE &&
    "status" in data &&
    typeof data.status === "string"
  );
}

async function requestCanvasAuthorizeUrl(
  courseId: string
): Promise<LtiCanvasOAuthConnectResponse> {
  const response = await fetch(
    `/api/auth/lti/course/${encodeURIComponent(courseId)}/canvas-oauth/connect`,
    { method: "POST" }
  );
  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    throw new Error(
      getErrorDetail(payload, "Could not start the Canvas connection.")
    );
  }
  return (await response.json()) as LtiCanvasOAuthConnectResponse;
}

/**
 * Wait for the popup to report back. Resolves with the connected credential
 * id, rejects with `CanvasOAuthCancelledError` if the instructor cancelled or
 * closed the window, and with a plain `Error` on failure.
 */
function awaitCanvasOAuthPopup(
  popup: Window,
  expectedCredentialId: number
): Promise<number> {
  return new Promise<number>((resolve, reject) => {
    let settled = false;
    let closedPoll: number | null = null;
    let closedGraceTimer: number | null = null;
    let timeoutTimer: number | null = null;

    const cleanup = () => {
      window.removeEventListener("message", handleMessage);
      if (closedPoll !== null) window.clearInterval(closedPoll);
      if (closedGraceTimer !== null) window.clearTimeout(closedGraceTimer);
      if (timeoutTimer !== null) window.clearTimeout(timeoutTimer);
    };
    const settle = (fn: () => void) => {
      if (settled) return;
      settled = true;
      cleanup();
      fn();
    };

    const handleMessage = (event: MessageEvent) => {
      if (event.origin !== window.location.origin) return;
      if (!isCanvasOAuthPopupMessage(event.data)) return;
      const message = event.data;

      if (message.status === "success") {
        settle(() => resolve(message.credential_id ?? expectedCredentialId));
      } else if (message.status === "cancelled") {
        settle(() => reject(new CanvasOAuthCancelledError(message.detail)));
      } else {
        settle(() =>
          reject(
            new Error(message.detail || "Canvas authorization did not finish.")
          )
        );
      }
    };

    window.addEventListener("message", handleMessage);

    closedPoll = window.setInterval(() => {
      if (!popup.closed) return;
      if (closedPoll !== null) {
        window.clearInterval(closedPoll);
        closedPoll = null;
      }
      closedGraceTimer = window.setTimeout(() => {
        settle(() => reject(new CanvasOAuthCancelledError()));
      }, POPUP_CLOSED_GRACE_MS);
    }, POPUP_CLOSED_POLL_MS);

    timeoutTimer = window.setTimeout(() => {
      settle(() => {
        if (!popup.closed) popup.close();
        reject(new Error("Canvas authorization timed out. Try again."));
      });
    }, POPUP_TIMEOUT_MS);
  });
}

/**
 * Run the full Connect Canvas flow for a course. Must be called from a user
 * gesture (button click) so the browser allows the popup.
 *
 * Resolves with the id of the instructor's now-authorized Canvas credential.
 */
export async function startCanvasOAuth(courseId: string): Promise<number> {
  // Open the popup synchronously with the click so it isn't blocked, then
  // point it at Canvas once the backend hands us the authorize URL.
  const popup = window.open("about:blank", POPUP_NAME, POPUP_FEATURES);
  if (!popup) {
    throw new CanvasOAuthPopupBlockedError();
  }

  let connectResponse: LtiCanvasOAuthConnectResponse;
  try {
    connectResponse = await requestCanvasAuthorizeUrl(courseId);
  } catch (e) {
    popup.close();
    throw e;
  }

  popup.location.href = connectResponse.auth_url;
  return awaitCanvasOAuthPopup(popup, connectResponse.credential_id);
}

/**
 * Attach an authorized credential to the course: creates the connector on
 * first setup, or swaps/reactivates it on reconnect.
 */
export async function attachCanvasCredentialToCourse(
  courseId: string,
  credentialId: number
): Promise<void> {
  const response = await fetch(
    `/api/auth/lti/course/${encodeURIComponent(courseId)}/setup-connector`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ credential_id: credentialId }),
    }
  );
  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    throw new Error(
      getErrorDetail(
        payload,
        "Canvas was authorized but the course could not be connected."
      )
    );
  }
}

export async function disconnectCanvasOAuth(courseId: string): Promise<void> {
  const response = await fetch(
    `/api/auth/lti/course/${encodeURIComponent(courseId)}/canvas-oauth`,
    { method: "DELETE" }
  );
  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    throw new Error(getErrorDetail(payload, "Could not disconnect Canvas."));
  }
}
