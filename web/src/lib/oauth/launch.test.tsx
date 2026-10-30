import { BroadcastChannel as NativeBroadcastChannel } from "node:worker_threads";
import {
  desktopOAuthReturnUrl,
  launchOAuth,
  notifyOAuthComplete,
  reportOAuthCallback,
  stripDesktopOAuthState,
} from "@/lib/oauth/launch";

const originalBroadcastChannel = window.BroadcastChannel;
const channels: NativeBroadcastChannel[] = [];
const authUrl = "https://provider.example/authorize?client_id=c&state=abc_123";

beforeEach(() => {
  Object.defineProperty(window, "BroadcastChannel", {
    configurable: true,
    value: jest.fn((name: string) => {
      const channel = new NativeBroadcastChannel(name);
      channels.push(channel);
      return channel;
    }),
  });
});

afterEach(() => {
  channels.splice(0).forEach((channel) => channel.close());
  Object.defineProperty(window, "BroadcastChannel", {
    configurable: true,
    value: originalBroadcastChannel,
  });
  delete window.__ONYX_DESKTOP__;
  delete window.__TAURI_INTERNALS__;
  jest.restoreAllMocks();
  jest.useRealTimers();
});

function openPopup() {
  const popup = {
    close: jest.fn(),
    location: { href: "about:blank" },
    sessionStorage: { setItem: jest.fn() },
  };
  const popupWindow = popup as unknown as Window;
  jest.spyOn(window, "open").mockReturnValue(popupWindow);
  return { popup, popupWindow };
}

async function flush() {
  for (let i = 0; i < 5; i++) await Promise.resolve();
}

test("rejects a blocked tab without starting authorization", async () => {
  jest.spyOn(window, "open").mockReturnValue(null);
  const start = jest.fn();
  await expect(launchOAuth(start)).rejects.toMatchObject({
    reason: "popup_blocked",
  });
  expect(start).not.toHaveBeenCalled();
});

test("opens a new tab and resolves on the matching same-origin message", async () => {
  const { popup, popupWindow } = openPopup();
  const promise = launchOAuth(async () => authUrl);
  expect(window.open).toHaveBeenCalledWith("about:blank", "_blank");
  await flush();
  expect(popup.location.href).toBe(authUrl);
  expect(popup.sessionStorage.setItem).toHaveBeenCalledWith(
    "onyx:oauth-launch",
    "abc_123"
  );
  const emit = (origin: string, source: MessageEventSource, state: string) =>
    window.dispatchEvent(
      new MessageEvent("message", {
        origin,
        source,
        data: { type: "onyx:oauth-complete", state, ok: true },
      })
    );
  emit("https://evil.example", popupWindow, "abc_123");
  emit(window.location.origin, window, "abc_123");
  emit(window.location.origin, popupWindow, "other");
  expect(popup.close).not.toHaveBeenCalled();
  emit(window.location.origin, popupWindow, "abc_123");
  await promise;
  expect(popup.close).toHaveBeenCalledTimes(1);
});

test("resolves from a BroadcastChannel completion and rejects a failed one", async () => {
  openPopup();
  const ok = launchOAuth(async () => authUrl);
  await flush();
  notifyOAuthComplete("abc_123");
  await expect(ok).resolves.toBeUndefined();

  openPopup();
  const failed = launchOAuth(async () => authUrl);
  await flush();
  notifyOAuthComplete("abc_123", false);
  await expect(failed).rejects.toMatchObject({ reason: "failed" });
});

test("rejects non-http authorization URLs and URLs without state", async () => {
  const { popup } = openPopup();
  await expect(
    launchOAuth(async () => "javascript:alert(1)")
  ).rejects.toMatchObject({ reason: "request_failed" });
  await expect(
    launchOAuth(async () => "https://provider.example/authorize")
  ).rejects.toMatchObject({ reason: "request_failed" });
  expect(popup.location.href).toBe("about:blank");
});

test("cancels on abort and times out", async () => {
  jest.useFakeTimers();
  const { popup } = openPopup();
  const controller = new AbortController();
  const cancelled = launchOAuth(async () => authUrl, {
    signal: controller.signal,
  });
  controller.abort();
  await expect(cancelled).rejects.toMatchObject({ reason: "cancelled" });

  const timedOut = launchOAuth(() => new Promise(() => {}));
  jest.advanceTimersByTime(10 * 60 * 1000);
  await expect(timedOut).rejects.toMatchObject({ reason: "timed_out" });
  expect(popup.close).toHaveBeenCalledTimes(2);
  expect(jest.getTimerCount()).toBe(0);
});

test("desktop opens the system browser with a marked state", async () => {
  const invoke = jest.fn().mockResolvedValue(undefined);
  window.__TAURI_INTERNALS__ = { invoke };
  window.__ONYX_DESKTOP__ = { oauthInBrowser: true };
  const open = jest.spyOn(window, "open");
  const promise = launchOAuth(async () => authUrl);
  await flush();
  expect(open).not.toHaveBeenCalled();
  expect(invoke).toHaveBeenCalledWith("plugin:shell|open", {
    path: "https://provider.example/authorize?client_id=c&state=abc_123.desktop",
  });
  notifyOAuthComplete("abc_123");
  await promise;
});

test("older desktop builds without the flag keep the in-app tab", async () => {
  window.__TAURI_INTERNALS__ = { invoke: jest.fn() };
  const { popup } = openPopup();
  const promise = launchOAuth(async () => authUrl);
  await flush();
  expect(popup.location.href).toBe(authUrl);
  notifyOAuthComplete("abc_123");
  await promise;
});

test("only a tab that launchOAuth opened closes itself", () => {
  const close = jest.spyOn(window, "close").mockImplementation(() => {});
  expect(reportOAuthCallback("abc_123", true)).toBe(false);
  window.sessionStorage.setItem("onyx:oauth-launch", "other");
  expect(reportOAuthCallback("abc_123", true)).toBe(false);
  window.sessionStorage.setItem("onyx:oauth-launch", "abc_123");
  expect(reportOAuthCallback("abc_123.desktop", true)).toBe(true);
  expect(window.sessionStorage.getItem("onyx:oauth-launch")).toBeNull();
  expect(close).toHaveBeenCalledTimes(1);
  window.__ONYX_DESKTOP__ = { oauthCallbackWindow: true };
  expect(reportOAuthCallback("abc_123", true)).toBe(true);
});

test("desktop state helpers", () => {
  expect(stripDesktopOAuthState("abc.desktop")).toBe("abc");
  expect(stripDesktopOAuthState("abc")).toBe("abc");
  const callback = new URL(
    "https://onyx.example/mcp/oauth/callback?code=x&state=abc.desktop"
  );
  const returnUrl = new URL(desktopOAuthReturnUrl(callback));
  expect(returnUrl.protocol).toBe("onyx:");
  expect(returnUrl.searchParams.get("origin")).toBe("https://onyx.example");
  expect(returnUrl.searchParams.get("path")).toBe(
    "/mcp/oauth/callback?code=x&state=abc.desktop"
  );
});
