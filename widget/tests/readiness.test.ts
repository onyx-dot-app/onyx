import { afterEach, describe, expect, it, mock, spyOn } from "bun:test";
import { ApiService } from "../src/services/api-service";
import { OnyxChatWidget } from "../src/widget";

const originalFetch = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = originalFetch;
  mock.restore();
});

describe("widget readiness", () => {
  it("waits through server cleanup and uses the current credential for polls", async () => {
    const tokens = ["first", "renewed"];
    const headers: string[] = [];
    globalThis.fetch = mock(
      async (_input: RequestInfo | URL, init?: RequestInit) => {
        headers.push(new Headers(init?.headers).get("Authorization") ?? "");
        return Response.json({ is_processing: headers.length === 1 });
      }
    ) as typeof fetch;
    const api = new ApiService("https://onyx.test/api", async () =>
      tokens.shift()!
    );
    await api.waitForSessionIdle(
      "session",
      new AbortController().signal,
      () => {}
    );
    expect(headers).toEqual(["Bearer first", "Bearer renewed"]);
  });

  it("does not treat failed or malformed status responses as idle", async () => {
    let calls = 0;
    globalThis.fetch = mock(async () => {
      calls++;
      if (calls === 1) return new Response("unavailable", { status: 401 });
      if (calls === 2) return Response.json({});
      return Response.json({ is_processing: false });
    }) as typeof fetch;
    const unconfirmed = mock(() => {});
    const api = new ApiService("https://onyx.test/api", async () => "key");
    await api.waitForSessionIdle(
      "session",
      new AbortController().signal,
      unconfirmed
    );
    expect(unconfirmed).toHaveBeenCalledTimes(2);
    expect(calls).toBe(3);
  });

  it.each([403, 404])(
    "ends readiness polling for unavailable sessions (%s)",
    async (status) => {
      globalThis.fetch = mock(
        async () => new Response("unavailable", { status })
      ) as typeof fetch;
      const api = new ApiService("https://onyx.test/api", async () => "key");
      const unconfirmed = mock(() => {});
      await expect(
        api.waitForSessionIdle(
          "session",
          new AbortController().signal,
          unconfirmed
        )
      ).rejects.toThrow("no longer available");
      expect(globalThis.fetch).toHaveBeenCalledTimes(1);
      expect(unconfirmed).not.toHaveBeenCalled();
    }
  );

  it("retries a stalled status request without releasing Send early", async () => {
    const setTimer = globalThis.setTimeout;
    const timeout = spyOn(globalThis, "setTimeout").mockImplementation(
      (callback, delay, ...args) =>
        setTimer(callback, delay === 10_000 ? 0 : delay, ...args)
    );
    let calls = 0;
    globalThis.fetch = mock(
      async (_input: RequestInfo | URL, init?: RequestInit) => {
        calls++;
        if (calls > 1) return Response.json({ is_processing: false });
        return new Promise<Response>((_resolve, reject) => {
          init?.signal?.addEventListener(
            "abort",
            () => reject(init.signal?.reason),
            { once: true }
          );
        });
      }
    ) as typeof fetch;
    const unconfirmed = mock(() => {});
    const api = new ApiService("https://onyx.test/api", async () => "key");
    await api.waitForSessionIdle(
      "session",
      new AbortController().signal,
      unconfirmed
    );
    expect(timeout).toHaveBeenCalledWith(expect.any(Function), 10_000);
    expect(unconfirmed).toHaveBeenCalledTimes(1);
    expect(calls).toBe(2);
  });

  it("supports browsers without AbortSignal composition methods", async () => {
    spyOn(AbortSignal, "any").mockImplementation(() => {
      throw new TypeError("AbortSignal.any is unavailable");
    });
    spyOn(AbortSignal, "timeout").mockImplementation(() => {
      throw new TypeError("AbortSignal.timeout is unavailable");
    });
    globalThis.fetch = mock(async () =>
      Response.json({ is_processing: false })
    ) as typeof fetch;
    const controller = new AbortController();
    const api = new ApiService("https://onyx.test/api", async () => "key");

    await api.waitForSessionIdle("session", controller.signal, () =>
      controller.abort()
    );
    expect(globalThis.fetch).toHaveBeenCalledTimes(1);
  });

  it("cancels polling when a reset replaces the conversation", async () => {
    const controller = new AbortController();
    globalThis.fetch = mock(async () => {
      controller.abort();
      return Response.json({ is_processing: true });
    }) as typeof fetch;
    const api = new ApiService("https://onyx.test/api", async () => "key");
    await expect(
      api.waitForSessionIdle("session", controller.signal, () => {})
    ).rejects.toThrow("Request cancelled");
  });

  it("keeps sends blocked after STOP until saving completes", async () => {
    const widget = new OnyxChatWidget();
    widget["config"] = { backendUrl: "https://onyx.test/api", apiKey: "key" };
    widget["inputValue"] = "hello";
    const api = new ApiService("https://onyx.test/api", async () => "key");
    api.createChatSession = mock(async () => "session");
    api.streamMessage = mock(async function* () {
      yield { obj: { type: "overall_stop" as const } };
    });
    let resolveIdle!: () => void;
    api.waitForSessionIdle = mock(
      () =>
        new Promise<void>((resolve) => {
          resolveIdle = resolve;
        })
    );
    widget["apiService"] = api;
    const pending = widget["sendMessage"]();
    await Bun.sleep(10);
    expect(widget["isStreaming"]).toBe(true);
    widget["inputValue"] = "next";
    await widget["sendMessage"]();
    expect(api.streamMessage).toHaveBeenCalledTimes(1);
    resolveIdle();
    await pending;
    expect(widget["isStreaming"]).toBe(false);
    expect(widget["inputValue"]).toBe("next");
  });

  it("does not release a new request when an old request finishes after reset", async () => {
    const widget = new OnyxChatWidget();
    widget["config"] = { backendUrl: "https://onyx.test/api", apiKey: "key" };
    widget["inputValue"] = "hello";
    const api = new ApiService("https://onyx.test/api", async () => "key");
    api.createChatSession = mock(async () => "old");
    api.streamMessage = mock(async function* () {});
    let resolveIdle!: () => void;
    api.waitForSessionIdle = mock(
      () =>
        new Promise<void>((resolve) => {
          resolveIdle = resolve;
        })
    );
    widget["apiService"] = api;
    const pending = widget["sendMessage"]();
    await Bun.sleep(10);
    widget.resetConversation();
    const newer = new AbortController();
    widget["abortController"] = newer;
    widget["isStreaming"] = true;
    widget["chatSessionId"] = "new";
    resolveIdle();
    await pending;
    expect(widget["abortController"]).toBe(newer);
    expect(widget["isStreaming"]).toBe(true);
    expect(widget["chatSessionId"]).toBe("new");
  });

  it("keeps a failed draft available for retry", async () => {
    const widget = new OnyxChatWidget();
    widget["config"] = { backendUrl: "https://onyx.test/api", apiKey: "key" };
    widget["inputValue"] = "retry me";
    const api = new ApiService("https://onyx.test/api", async () => "key");
    api.createChatSession = mock(async () => {
      throw new Error("offline");
    });
    widget["apiService"] = api;
    await widget["sendMessage"]();
    expect(widget["inputValue"]).toBe("retry me");
    expect(widget["isStreaming"]).toBe(false);
  });
  it("removes an unacknowledged optimistic prompt before retrying", async () => {
    const widget = new OnyxChatWidget();
    widget["config"] = { backendUrl: "https://onyx.test/api", apiKey: "key" };
    widget["inputValue"] = "retry me";
    const api = new ApiService("https://onyx.test/api", async () => "key");
    api.createChatSession = mock(async () => "session");
    api.waitForSessionIdle = mock(async () => {});
    api.streamMessage = mock(async function* () {
      throw new Error("offline");
    });
    widget["apiService"] = api;
    await widget["sendMessage"]();
    expect(widget["messages"]).toHaveLength(0);
    expect(widget["inputValue"]).toBe("retry me");
    api.streamMessage = mock(async function* () {
      yield { obj: { user_message_id: 1, reserved_assistant_message_id: 2 } };
    });
    await widget["sendMessage"]();
    expect(widget["messages"]).toHaveLength(1);
    expect(widget["messages"][0]).toMatchObject({ id: 1, content: "retry me" });
    expect(widget["inputValue"]).toBe("");
  });

  it("keeps an acknowledged prompt without restoring it as a duplicate draft", async () => {
    const widget = new OnyxChatWidget();
    widget["config"] = { backendUrl: "https://onyx.test/api", apiKey: "key" };
    widget["inputValue"] = "accepted question";
    const api = new ApiService("https://onyx.test/api", async () => "key");
    api.createChatSession = mock(async () => "session");
    api.waitForSessionIdle = mock(
      async (_sessionId, _signal, onUnconfirmed) => {
        onUnconfirmed();
        expect(widget["error"]).toBe("delivery failed");
        expect(widget["streamingStatus"]).toContain("Waiting to confirm");
      }
    );
    api.streamMessage = mock(async function* () {
      yield { obj: { user_message_id: 1, reserved_assistant_message_id: 2 } };
      throw new Error("delivery failed");
    });
    widget["apiService"] = api;
    await widget["sendMessage"]();
    expect(widget["messages"]).toHaveLength(1);
    expect(widget["messages"][0]).toMatchObject({
      id: 1,
      content: "accepted question",
    });
    expect(widget["inputValue"]).toBe("");
    expect(widget["error"]).toBe("delivery failed");
    expect(widget["streamingStatus"]).toBe("");
    expect(widget["isStreaming"]).toBe(false);
  });

  it.each([false, true])(
    "releases Send when a session is unavailable after sending=%s",
    async (afterSending) => {
      const widget = new OnyxChatWidget();
      widget["config"] = { backendUrl: "https://onyx.test/api", apiKey: "key" };
      widget["inputValue"] = "hello";
      const api = new ApiService("https://onyx.test/api", async () => "key");
      api.createChatSession = mock(async () => "session");
      if (!afterSending) widget["chatSessionId"] = "session";
      api.streamMessage = mock(async function* () {
        yield { obj: { user_message_id: 1, reserved_assistant_message_id: 2 } };
      });
      api.waitForSessionIdle = mock(async () => {
        throw new Error("Session unavailable");
      });
      widget["apiService"] = api;
      await widget["sendMessage"]();
      expect(widget["error"]).toBe("Session unavailable");
      expect(widget["isStreaming"]).toBe(false);
      expect(widget["abortController"]).toBeUndefined();
      expect(widget["inputValue"]).toBe(afterSending ? "" : "hello");
      expect(api.streamMessage).toHaveBeenCalledTimes(afterSending ? 1 : 0);
    }
  );
});
