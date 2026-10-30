import * as yup from "yup";

export type OAuthLaunchFailure =
  | "popup_blocked"
  | "cancelled"
  | "timed_out"
  | "failed"
  | "request_failed";

export class OAuthLaunchError extends Error {
  constructor(readonly reason: OAuthLaunchFailure) {
    super(reason);
    this.name = "OAuthLaunchError";
  }
}

export interface OAuthLaunchOptions {
  signal?: AbortSignal;
}

// "." is outside the base64url alphabet every state generator uses.
export const DESKTOP_STATE_SUFFIX = ".desktop";
export const DESKTOP_OAUTH_RETURN_URL = "onyx://oauth-callback";
const LAUNCH_TIMEOUT_MS = 10 * 60 * 1000;
const completionType = "onyx:oauth-complete";
const completionSchema = yup.object({
  type: yup.mixed<typeof completionType>().oneOf([completionType]).defined(),
  state: yup.string().defined(),
  ok: yup.boolean().defined(),
});

interface DesktopBridge {
  oauthInBrowser?: boolean;
  oauthCallbackWindow?: boolean;
}

interface TauriInternals {
  invoke: (cmd: string, args: Record<string, string>) => Promise<void>;
}

declare global {
  interface Window {
    __ONYX_DESKTOP__?: DesktopBridge;
    __TAURI_INTERNALS__?: TauriInternals;
  }
}

function tauriInternals(): TauriInternals | null {
  if (typeof window === "undefined") return null;
  return window.__TAURI_INTERNALS__ ?? null;
}

/** Desktop builds that hand OAuth to the system browser set this flag. */
export function opensOAuthInSystemBrowser(): boolean {
  return (
    tauriInternals() !== null &&
    window.__ONYX_DESKTOP__?.oauthInBrowser === true
  );
}

export function isDesktopOAuthState(state: string): boolean {
  return state.endsWith(DESKTOP_STATE_SUFFIX);
}

export function stripDesktopOAuthState(state: string): string {
  return isDesktopOAuthState(state)
    ? state.slice(0, -DESKTOP_STATE_SUFFIX.length)
    : state;
}

/** The URL that hands a browser-side callback back to the desktop app. */
export function desktopOAuthReturnUrl(callback: URL): string {
  const query = new URLSearchParams({
    origin: callback.origin,
    path: callback.pathname + callback.search,
  });
  return `${DESKTOP_OAUTH_RETURN_URL}?${query.toString()}`;
}

function openCompletionChannel(state: string): BroadcastChannel | null {
  if (typeof BroadcastChannel === "undefined") return null;
  try {
    return new BroadcastChannel(`${completionType}:${state}`);
  } catch {
    return null;
  }
}

/** Tells the page that launched this OAuth attempt that it finished. */
export function notifyOAuthComplete(state: string, ok = true): void {
  const message = { type: completionType, state, ok };
  try {
    window.opener?.postMessage(message, window.location.origin);
  } catch {}
  const channel = openCompletionChannel(state);
  if (!channel) return;
  try {
    channel.postMessage(message);
  } catch {
  } finally {
    channel.close();
  }
}

/**
 * Closes a callback tab that a waiting Onyx page opened. Returns false when
 * nothing is waiting, so the caller keeps its redirect fallback.
 */
export function closeOAuthCallbackWindow(): boolean {
  if (!window.opener && !window.__ONYX_DESKTOP__?.oauthCallbackWindow)
    return false;
  window.close();
  return true;
}

function parseAuthorizationUrl(raw: string): URL | null {
  try {
    const url = new URL(raw);
    return url.protocol === "https:" || url.protocol === "http:" ? url : null;
  } catch {
    return null;
  }
}

/**
 * Opens an OAuth authorization URL outside the current page and resolves when
 * the callback page reports completion. On the web this is a new tab; in the
 * desktop app it is the system browser. `start` returns the provider URL, or
 * null when no authorization is needed.
 */
export function launchOAuth(
  start: () => Promise<string | null>,
  { signal }: OAuthLaunchOptions = {}
): Promise<void> {
  if (signal?.aborted) {
    return Promise.reject(new OAuthLaunchError("cancelled"));
  }
  const inBrowser = opensOAuthInSystemBrowser();
  // Open the tab inside the click so popup blockers allow it.
  const popup = inBrowser ? null : window.open("about:blank", "_blank");
  if (!inBrowser && !popup) {
    return Promise.reject(new OAuthLaunchError("popup_blocked"));
  }

  return new Promise((resolve, reject) => {
    let settled = false;
    let channel: BroadcastChannel | null = null;
    let state: string | null = null;
    function finish(error?: Error) {
      if (settled) return;
      settled = true;
      window.removeEventListener("message", receiveCompletion);
      signal?.removeEventListener("abort", cancel);
      channel?.removeEventListener("message", receiveBroadcastCompletion);
      channel?.close();
      window.clearTimeout(timeout);
      if (error || !inBrowser) popup?.close();
      if (error) reject(error);
      else resolve();
    }
    function cancel() {
      finish(new OAuthLaunchError("cancelled"));
    }
    function receiveBroadcastCompletion(event: MessageEvent<unknown>) {
      try {
        const message = completionSchema.validateSync(event.data, {
          strict: true,
        });
        if (state === null || message.state !== state) return;
        finish(message.ok ? undefined : new OAuthLaunchError("failed"));
      } catch {}
    }
    function receiveCompletion(event: MessageEvent<unknown>) {
      if (event.origin !== window.location.origin) return;
      if (popup && event.source !== popup) return;
      receiveBroadcastCompletion(event);
    }
    // COOP can mark a live popup closed, so wait for completion, cancel, or timeout.
    const timeout = window.setTimeout(
      () => finish(new OAuthLaunchError("timed_out")),
      LAUNCH_TIMEOUT_MS
    );
    window.addEventListener("message", receiveCompletion);
    signal?.addEventListener("abort", cancel, { once: true });

    start().then(
      async (authorizationUrl) => {
        if (settled) return;
        if (authorizationUrl === null) {
          finish();
          return;
        }
        const url = parseAuthorizationUrl(authorizationUrl);
        const rawState = url?.searchParams.get("state");
        if (!url || !rawState) {
          finish(new OAuthLaunchError("request_failed"));
          return;
        }
        state = rawState;
        channel = openCompletionChannel(state);
        channel?.addEventListener("message", receiveBroadcastCompletion);
        if (popup) {
          popup.location.href = url.href;
          return;
        }
        url.searchParams.set("state", rawState + DESKTOP_STATE_SUFFIX);
        try {
          await tauriInternals()?.invoke("plugin:shell|open", {
            path: url.href,
          });
        } catch {
          finish(new OAuthLaunchError("request_failed"));
        }
      },
      (error: unknown) =>
        finish(
          error instanceof Error
            ? error
            : new OAuthLaunchError("request_failed")
        )
    );
  });
}

/** True when a desktop-started attempt landed in a regular browser tab. */
export function needsDesktopOAuthHandoff(state: string | null): boolean {
  return (
    state !== null && isDesktopOAuthState(state) && tauriInternals() === null
  );
}

/**
 * Reports a finished callback to the waiting page. Returns true when this tab
 * closed itself, so the caller skips its redirect.
 */
export function reportOAuthCallback(state: string, ok: boolean): boolean {
  notifyOAuthComplete(stripDesktopOAuthState(state), ok);
  return closeOAuthCallbackWindow();
}

/**
 * Opens an authorization URL that is already known. Falls back to the
 * current-tab redirect when the browser blocks the new tab.
 */
export function openOAuthAuthorization(
  authorizationUrl: string,
  options: OAuthLaunchOptions = {}
): Promise<void> {
  return launchOAuth(async () => authorizationUrl, options).catch(
    (error: unknown) => {
      if (
        error instanceof OAuthLaunchError &&
        error.reason === "popup_blocked"
      ) {
        window.location.assign(authorizationUrl);
        return new Promise<void>(() => {});
      }
      throw error;
    }
  );
}

/** True for outcomes the user chose, which need no error message. */
export function isSilentOAuthOutcome(error: unknown): boolean {
  return (
    error instanceof OAuthLaunchError &&
    (error.reason === "cancelled" || error.reason === "timed_out")
  );
}
