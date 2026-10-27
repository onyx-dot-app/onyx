import {
  afterEach,
  beforeEach,
  describe,
  expect,
  it,
  jest,
} from "@jest/globals";
import { fetch as expoFetch } from "expo/fetch";

import { apiFetch } from "@/api/client";
import { setInFlightRefresh } from "@/api/auth/refreshState";
import { getToken } from "@/api/auth/tokenStore";
import { getChatSessionStatus, stopChatSession } from "@/api/chat/sessions";
import {
  resumeChatMessage,
  streamChatMessage,
  type SendMessageBody,
} from "@/api/chat/stream";

jest.mock("expo/fetch", () => ({ fetch: jest.fn() }));
jest.mock("@/api/auth/tokenStore", () => ({ getToken: jest.fn() }));
jest.mock("@/state/session", () => ({
  getStoredServerUrl: () => "https://onyx.test",
}));

const body: SendMessageBody = {
  message: "hello",
  chat_session_id: "s1",
  parent_message_id: null,
  file_descriptors: [],
  deep_research: false,
  origin: "mobile",
};
const requests = [
  {
    name: "API",
    request: (signal: AbortSignal) => apiFetch("/me", { signal }),
  },
  {
    name: "send",
    request: (signal: AbortSignal) => streamChatMessage(body, signal).next(),
  },
  {
    name: "resume",
    request: (signal: AbortSignal) => resumeChatMessage("s1", 0, signal).next(),
  },
];

beforeEach(() => {
  jest.clearAllMocks();
  jest.mocked(getToken).mockReset().mockResolvedValue("stored-test-token");
  jest.spyOn(globalThis, "fetch").mockResolvedValue(new Response("{}"));
});

afterEach(() => {
  setInFlightRefresh(null);
  jest.restoreAllMocks();
  jest.useRealTimers();
});

describe("request cancellation during authentication", () => {
  it.each(requests)(
    "does not resolve credentials for an already cancelled $name request",
    async ({ request }) => {
      const controller = new AbortController();
      controller.abort();
      await expect(request(controller.signal)).rejects.toMatchObject({
        name: "AbortError",
      });
      expect(getToken).not.toHaveBeenCalled();
      expect(globalThis.fetch).not.toHaveBeenCalled();
      expect(expoFetch).not.toHaveBeenCalled();
    },
  );

  it.each(requests)(
    "cancels a $name request before shared refresh resolves",
    async ({ request }) => {
      const refresh = Promise.withResolvers<string | null>();
      setInFlightRefresh(refresh.promise);
      const controller = new AbortController();
      const pending = request(controller.signal);
      controller.abort();
      await expect(pending).rejects.toMatchObject({ name: "AbortError" });
      refresh.resolve("late-test-token");
      await Promise.resolve();
      expect(globalThis.fetch).not.toHaveBeenCalled();
      expect(expoFetch).not.toHaveBeenCalled();
    },
  );

  it("keeps another request waiting on the shared refresh and removes its listener after success", async () => {
    const refresh = Promise.withResolvers<string | null>();
    setInFlightRefresh(refresh.promise);
    const cancelled = new AbortController();
    const surviving = new AbortController();
    const removeListener = jest.spyOn(surviving.signal, "removeEventListener");
    const first = apiFetch("/me", { signal: cancelled.signal });
    const second = apiFetch("/me", { signal: surviving.signal });
    cancelled.abort();
    await expect(first).rejects.toMatchObject({ name: "AbortError" });
    refresh.resolve("fresh-test-token");
    await expect(second).resolves.toEqual({});
    expect(globalThis.fetch).toHaveBeenCalledTimes(1);
    expect(jest.mocked(globalThis.fetch).mock.calls[0]?.[1]?.headers).toEqual(
      new Headers({
        Accept: "application/json",
        Authorization: "Bearer fresh-test-token",
      }),
    );
    expect(removeListener).toHaveBeenCalledWith("abort", expect.any(Function));
  });

  it("cancels a stored-token wait without waiting on the keychain", async () => {
    const stored = Promise.withResolvers<string | null>();
    jest.mocked(getToken).mockReturnValue(stored.promise);
    const controller = new AbortController();
    const pending = apiFetch("/me", {
      signal: controller.signal,
      auth: "stored",
    });
    controller.abort();
    await expect(pending).rejects.toMatchObject({ name: "AbortError" });
    stored.resolve("late-test-token");
    await Promise.resolve();
    expect(globalThis.fetch).not.toHaveBeenCalled();
  });

  it("removes the listener when credential resolution fails", async () => {
    jest.mocked(getToken).mockRejectedValueOnce(new Error("keychain failed"));
    const controller = new AbortController();
    const removeListener = jest.spyOn(controller.signal, "removeEventListener");
    await expect(
      apiFetch("/me", { signal: controller.signal }),
    ).rejects.toThrow("keychain failed");
    expect(removeListener).toHaveBeenCalledWith("abort", expect.any(Function));
    expect(globalThis.fetch).not.toHaveBeenCalled();
  });

  it.each([
    { name: "readiness", request: () => getChatSessionStatus("s1") },
    { name: "Stop", request: () => stopChatSession("s1", 11) },
  ])(
    "applies the $name deadline while authentication is pending",
    async ({ request }) => {
      jest.useFakeTimers();
      const refresh = Promise.withResolvers<string | null>();
      setInFlightRefresh(refresh.promise);
      const pending = expect(request()).rejects.toMatchObject({
        name: "AbortError",
      });
      await jest.advanceTimersByTimeAsync(10_000);
      await pending;
      refresh.resolve("late-test-token");
      await Promise.resolve();
      expect(globalThis.fetch).not.toHaveBeenCalled();
      expect(jest.getTimerCount()).toBe(0);
    },
  );
});
