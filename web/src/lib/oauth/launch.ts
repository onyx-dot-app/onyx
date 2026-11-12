import * as yup from "yup";
import { loadPage } from "@opal/navigation";
import { DESKTOP_STATE_SUFFIX } from "@/lib/oauth/desktopCallback";
import { isSkillLimitNotice, type SkillLimitNotice } from "@/lib/skills/limits";

export type OAuthLaunchFailure =
  | "popup_blocked"
  | "cancelled"
  | "timed_out"
  | "failed"
  | "request_failed";

/** What the callback page showed for a failed attempt, so the waiting page can show it too. */
export interface OAuthFailureDetail {
  title: string;
  description: string;
}

export class OAuthLaunchError extends Error {
  constructor(
    readonly reason: OAuthLaunchFailure,
    readonly detail?: OAuthFailureDetail
  ) {
    super(reason);
    this.name = "OAuthLaunchError";
  }
}

export interface OAuthLaunchOptions {
  signal?: AbortSignal;
  /** Runs once the provider page is open, before the flow completes. */
  onOpened?: () => void;
}

export { DESKTOP_STATE_SUFFIX };
export const DESKTOP_OAUTH_RETURN_URL = "onyx://oauth-callback";
const LAUNCH_TIMEOUT_MS = 10 * 60 * 1000;
// A claimed callback that never reports must not leave a spinner running.
const CLAIMED_CALLBACK_TIMEOUT_MS = 60 * 1000;
// Marks a tab that `launchOAuth` opened, so only its callback closes itself.
const LAUNCHED_TAB_KEY = "onyx:oauth-launch";
const completionType = "onyx:oauth-complete";
const completionSchema = yup.object({
  type: yup.mixed<typeof completionType>().oneOf([completionType]).defined(),
  state: yup.string().defined(),
  ok: yup.boolean().defined(),
  redirectPath: yup.string().optional(),
  skillsLeftOff: yup.mixed().optional(),
  error: yup
    .object({
      title: yup.string().defined(),
      description: yup.string().defined(),
    })
    .optional()
    .default(undefined),
});

/** What the callback page reported; `redirectPath` is where it would have redirected. */
export interface OAuthCompletion {
  redirectPath?: string;
  /** The app skills the connect left off for the skill limit. */
  skillsLeftOff?: SkillLimitNotice;
}

interface DesktopBridge {
  oauthInBrowser?: boolean;
  oauthCallbackWindow?: boolean;
  /** Called by the shell with a deep-linked callback URL; true when this page completes it. */
  claimOAuthCallback?: (callbackUrl: string) => boolean;
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
export function notifyOAuthComplete(
  state: string,
  ok = true,
  redirectPath?: string,
  error?: OAuthFailureDetail,
  skillsLeftOff?: SkillLimitNotice
): void {
  // Copy only the fields: callers may pass objects with functions, which
  // postMessage cannot clone.
  const failure = error && {
    title: error.title,
    description: error.description,
  };
  const message = {
    type: completionType,
    state,
    ok,
    redirectPath,
    error: failure,
    skillsLeftOff,
  };
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
 * nothing is waiting, so the caller keeps its redirect fallback. A desktop
 * callback window stays open on failure, since the waiting page may be gone.
 */
export function closeOAuthCallbackWindow(state: string, ok = true): boolean {
  let launched = false;
  try {
    launched = window.sessionStorage.getItem(LAUNCHED_TAB_KEY) === state;
    if (launched) window.sessionStorage.removeItem(LAUNCHED_TAB_KEY);
  } catch {}
  if (!launched && !(ok && window.__ONYX_DESKTOP__?.oauthCallbackWindow)) {
    return false;
  }
  window.close();
  return true;
}

// Desktop attempts waiting in this page, keyed by state.
const pendingDesktopCallbacks = new Map<string, (callback: URL) => void>();

function claimDesktopOAuthCallback(callbackUrl: string): boolean {
  let url: URL;
  try {
    url = new URL(callbackUrl);
  } catch {
    return false;
  }
  if (url.origin !== window.location.origin) return false;
  const state = url.searchParams.get("state");
  const complete =
    state === null ? undefined : pendingDesktopCallbacks.get(state);
  if (state === null || !complete) return false;
  pendingDesktopCallbacks.delete(state);
  complete(url);
  return true;
}

/**
 * Lets the desktop shell complete this attempt in a hidden frame of the
 * waiting page instead of a separate window. Returns the unregister function.
 */
function awaitDesktopCallback(
  state: string,
  complete: (callback: URL) => void
): () => void {
  pendingDesktopCallbacks.set(state, complete);
  window.__ONYX_DESKTOP__ = Object.assign(window.__ONYX_DESKTOP__ ?? {}, {
    claimOAuthCallback: claimDesktopOAuthCallback,
  });
  return () => {
    if (pendingDesktopCallbacks.get(state) === complete) {
      pendingDesktopCallbacks.delete(state);
    }
  };
}

/**
 * Leaves a callback page. A desktop callback window closes, because the app's
 * main window already holds the page the user came from.
 */
export function leaveOAuthCallback(navigate: () => void): void {
  if (window.__ONYX_DESKTOP__?.oauthCallbackWindow) window.close();
  else navigate();
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
  { signal, onOpened }: OAuthLaunchOptions = {}
): Promise<OAuthCompletion> {
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
    let callbackFrame: HTMLIFrameElement | null = null;
    let claimTimeout: number | undefined;
    let releaseDesktopCallback: (() => void) | null = null;
    function finish(error?: Error, completion: OAuthCompletion = {}) {
      if (settled) return;
      settled = true;
      releaseDesktopCallback?.();
      callbackFrame?.remove();
      window.clearTimeout(claimTimeout);
      window.removeEventListener("message", receiveCompletion);
      signal?.removeEventListener("abort", cancel);
      channel?.removeEventListener("message", receiveBroadcastCompletion);
      channel?.close();
      window.clearTimeout(timeout);
      if (error || !inBrowser) popup?.close();
      if (error) reject(error);
      else resolve(completion);
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
        if (message.ok)
          finish(undefined, {
            redirectPath: message.redirectPath,
            skillsLeftOff: isSkillLimitNotice(message.skillsLeftOff)
              ? message.skillsLeftOff
              : undefined,
          });
        else finish(new OAuthLaunchError("failed", message.error));
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
          try {
            popup.sessionStorage.setItem(LAUNCHED_TAB_KEY, rawState);
          } catch {}
          // The provider page must not reach back into this tab. Completion
          // comes over the channel; the desktop in-app popup still needs the
          // opener for postMessage.
          if (channel && tauriInternals() === null) popup.opener = null;
          popup.location.href = url.href;
          onOpened?.();
          return;
        }
        releaseDesktopCallback = awaitDesktopCallback(rawState, (callback) => {
          if (settled) return;
          // Same origin, so the frame runs the callback page with this
          // session and reports through the completion channel.
          callbackFrame = document.createElement("iframe");
          callbackFrame.hidden = true;
          callbackFrame.src = callback.href;
          document.body.appendChild(callbackFrame);
          claimTimeout = window.setTimeout(
            () => finish(new OAuthLaunchError("failed")),
            CLAIMED_CALLBACK_TIMEOUT_MS
          );
        });
        url.searchParams.set("state", rawState + DESKTOP_STATE_SUFFIX);
        try {
          await tauriInternals()?.invoke("plugin:shell|open", {
            path: url.href,
          });
          onOpened?.();
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
export function reportOAuthCallback(
  state: string,
  ok: boolean,
  redirectPath?: string,
  error?: OAuthFailureDetail,
  skillsLeftOff?: SkillLimitNotice
): boolean {
  const attemptState = stripDesktopOAuthState(state);
  notifyOAuthComplete(attemptState, ok, redirectPath, error, skillsLeftOff);
  return closeOAuthCallbackWindow(attemptState, ok);
}

/**
 * Opens an authorization URL that is already known. Falls back to the
 * current-tab redirect when the browser blocks the new tab.
 */
export function openOAuthAuthorization(
  authorizationUrl: string,
  options: OAuthLaunchOptions = {}
): Promise<OAuthCompletion> {
  return launchOAuth(async () => authorizationUrl, options).catch(
    (error: unknown) => {
      if (
        error instanceof OAuthLaunchError &&
        error.reason === "popup_blocked"
      ) {
        const url = parseAuthorizationUrl(authorizationUrl);
        if (!url) throw new OAuthLaunchError("request_failed");
        loadPage(url.href);
        return new Promise<OAuthCompletion>(() => {});
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

/** The callback page's own explanation of a failed attempt, when it sent one. */
export function oauthFailureDetail(error: unknown): OAuthFailureDetail | null {
  return error instanceof OAuthLaunchError ? (error.detail ?? null) : null;
}
