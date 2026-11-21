import { afterEach, describe, expect, it, mock, spyOn } from "bun:test";
import {
  ApiError,
  ApiService,
  type ResumeEnd,
} from "../src/services/api-service";
import {
  isTemplateResult,
  TemplateResultType,
} from "lit/directive-helpers.js";
import type {
  ChatSessionDetail,
  ChatSessionStatus,
  ChatStream,
  Packet,
  StreamCursor,
} from "../src/types/api-types";
import { mockFetch, mockTimeouts } from "./mocks";
import { pendingApproval } from "./widget-helpers";
import { chatStream, idle, offer, runs } from "./session-status";
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
    mockFetch(
      async (_input: RequestInfo | URL, init?: RequestInit) => {
        headers.push(new Headers(init?.headers).get("Authorization") ?? "");
        return Response.json({ is_processing: headers.length === 1 });
      }
    );
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
    mockFetch(async () => {
      calls++;
      if (calls === 1) return new Response("unavailable", { status: 401 });
      if (calls === 2) return Response.json({});
      return Response.json({ is_processing: false });
    });
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
      mockFetch(
        async () => new Response("unavailable", { status })
      );
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
    const timeout = mockTimeouts((ms) => (ms === 10_000 ? 0 : ms));
    let calls = 0;
    mockFetch(
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
    );
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
    mockFetch(async () =>
      Response.json({ is_processing: false })
    );
    const controller = new AbortController();
    const api = new ApiService("https://onyx.test/api", async () => "key");

    await api.waitForSessionIdle("session", controller.signal, () =>
      controller.abort()
    );
    expect(globalThis.fetch).toHaveBeenCalledTimes(1);
  });

  it("retries credential resolution after the readiness deadline", async () => {
    mockTimeouts((ms) => (ms === 10_000 ? 0 : ms));
    let resolveToken!: (token: string) => void;
    const firstToken = new Promise<string>((resolve) => {
      resolveToken = resolve;
    });
    const tokenProvider = mock(async () => "renewed").mockImplementationOnce(
      () => firstToken
    );
    mockFetch(async () =>
      Response.json({ is_processing: false })
    );
    const unconfirmed = mock(() => {});
    const api = new ApiService("https://onyx.test/api", tokenProvider);
    await api.waitForSessionIdle(
      "session",
      new AbortController().signal,
      unconfirmed
    );
    resolveToken("expired");
    await Bun.sleep(0);
    expect(unconfirmed).toHaveBeenCalledTimes(1);
    expect(tokenProvider).toHaveBeenCalledTimes(2);
    expect(globalThis.fetch).toHaveBeenCalledTimes(1);
    expect(globalThis.fetch).toHaveBeenCalledWith(expect.any(String), {
      headers: {
        "Content-Type": "application/json",
        Authorization: "Bearer renewed",
      },
      signal: expect.any(AbortSignal),
    });
  });

  it("aborts readiness while the credential provider is pending", async () => {
    let resolveToken!: (token: string) => void;
    const token = new Promise<string>((resolve) => {
      resolveToken = resolve;
    });
    mockFetch(async () =>
      Response.json({ is_processing: false })
    );
    const controller = new AbortController();
    const unconfirmed = mock(() => {});
    const api = new ApiService("https://onyx.test/api", () => token);
    const pending = api.waitForSessionIdle(
      "session",
      controller.signal,
      unconfirmed
    );
    controller.abort();
    await expect(pending).rejects.toThrow("Request cancelled");
    resolveToken("late");
    await Bun.sleep(0);
    expect(globalThis.fetch).not.toHaveBeenCalled();
    expect(unconfirmed).not.toHaveBeenCalled();
  });

  it("cancels polling when a reset replaces the conversation", async () => {
    const controller = new AbortController();
    mockFetch(async () => {
      controller.abort();
      return Response.json({ is_processing: true });
    });
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
    let reads = 0;
    // The new chat's baseline read returns at once; the idle wait after the
    // stop holds the send.
    api.waitForSessionIdle = mock(() =>
      reads++ === 1
        ? new Promise<ChatSessionStatus>((resolve) => {
            resolveIdle = () => resolve(idle());
          })
        : Promise.resolve(idle())
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
        new Promise<ChatSessionStatus>((resolve) => {
          resolveIdle = () => resolve(idle());
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
    widget["config"] = {
      backendUrl: "https://onyx.test/api",
      apiKey: "key",
      mode: "inline",
    };
    widget["inputValue"] = "retry me";
    const api = new ApiService("https://onyx.test/api", async () => "key");
    api.createChatSession = mock(async () => "session");
    api.waitForSessionIdle = mock(async () => idle());
    api.streamMessage = mock(async function* () {
      throw new Error("offline");
    });
    widget["apiService"] = api;
    await widget["sendMessage"]();
    expect(widget["messages"]).toHaveLength(0);
    expect(widget["inputValue"]).toBe("retry me");
    expect(widget["error"]).toBe("offline");
    // The static markup of the rendered template and the ones in it
    const markup = (value: unknown): string =>
      isTemplateResult(value, TemplateResultType.HTML)
        ? value.strings.join("") + value.values.map(markup).join("")
        : Array.isArray(value)
          ? value.map(markup).join("")
          : "";
    const shown = markup(widget.render());
    expect(shown).not.toContain("compact-input-container");
    expect(shown).toContain('class="messages"');
    api.streamMessage = mock(async function* () {
      yield { obj: { user_message_id: 1, reserved_assistant_message_id: 2 } };
    });
    api.resumeStream = mock(async function* (): AsyncGenerator<
      Packet | StreamCursor,
      ResumeEnd
    > {
      return "ended";
    });
    api.getChatSession = mock(async (): Promise<ChatSessionDetail> => ({
      messages: [
        { message_id: 1, message_type: "user", latest_child_message: 2 },
        { message_id: 2, message_type: "assistant", parent_message: 1 },
      ],
      packets: [[]],
    }));
    await widget["sendMessage"]();
    expect(widget["messages"]).toHaveLength(1);
    expect(widget["messages"][0]).toMatchObject({ id: 1, content: "retry me" });
    expect(widget["inputValue"]).toBe("");
  });

  it("keeps an acknowledged prompt and finishes its response from the saved session", async () => {
    mockTimeouts((ms) => (ms === 1_000 ? 0 : ms));
    const widget = new OnyxChatWidget();
    widget["config"] = { backendUrl: "https://onyx.test/api", apiKey: "key" };
    widget["inputValue"] = "accepted question";
    const api = new ApiService("https://onyx.test/api", async () => "key");
    api.createChatSession = mock(async () => "session");
    // The server ran the turn on and is idle; nothing is left to replay.
    api.waitForSessionIdle = mock(async () => idle());
    api.streamMessage = mock(async function* () {
      yield { obj: { user_message_id: 1, reserved_assistant_message_id: 2 } };
      throw new Error("delivery failed");
    });
    api.resumeStream = mock(async function* (): AsyncGenerator<
      Packet | StreamCursor,
      ResumeEnd
    > {
      return "ended";
    });
    api.getChatSession = mock(async (): Promise<ChatSessionDetail> => ({
      messages: [
        { message_id: 1, message_type: "user", latest_child_message: 2 },
        { message_id: 2, message_type: "assistant", parent_message: 1 },
      ],
      packets: [
        [
          { obj: { type: "message_start" as const } },
          { obj: { type: "message_delta" as const, content: "Saved answer" } },
          { obj: { type: "stop" as const } },
        ],
      ],
    }));
    const stored = new Map<string, string>();
    globalThis.sessionStorage = {
      getItem: (key: string) => stored.get(key) ?? null,
      setItem: (key: string, value: string) => void stored.set(key, value),
      removeItem: (key: string) => void stored.delete(key),
    } as Storage;
    widget["apiService"] = api;
    try {
      await widget["sendMessage"]();
    } finally {
      Reflect.deleteProperty(globalThis, "sessionStorage");
    }
    expect(api.resumeStream).not.toHaveBeenCalled();
    expect(widget["messages"]).toHaveLength(2);
    expect(widget["messages"][0]).toMatchObject({
      id: 1,
      content: "accepted question",
    });
    expect(widget["messages"][1]).toMatchObject({
      id: 2,
      role: "assistant",
      content: "Saved answer",
      isStreaming: false,
    });
    const saved = JSON.parse(stored.get("onyx-widget-session") ?? "null");
    expect(saved.messages.map((m: { content: string }) => m.content)).toEqual([
      "accepted question",
      "Saved answer",
    ]);
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
      let reads = 0;
      // A new chat's baseline read passes; the read after the send fails.
      api.waitForSessionIdle = mock(async () => {
        if (afterSending && reads++ === 0) return idle();
        throw new Error("Session unavailable");
      });
      api.resumeStream = mock(async function* (): AsyncGenerator<
      Packet | StreamCursor,
      ResumeEnd
    > {
      return "ended";
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

  describe("a stream that ends before its response", () => {
    function followingWidget() {
      const widget = new OnyxChatWidget();
      widget["config"] = { backendUrl: "https://onyx.test/api", apiKey: "key" };
      widget["currentIdentity"] = async () => "user";
      const api = new ApiService("https://onyx.test/api", async () => "key");
      api.getChatSession = mock(
        async (): Promise<ChatSessionDetail> => ({ messages: [], packets: [] })
      );
      widget["apiService"] = api;
      return { widget, api };
    }

    /** Pauses of the poll interval end at once and are logged. */
    function logPauses(log: string[]) {
      mockTimeouts((ms) => {
        if (ms === 1_000) log.push("pause");
        return ms === 1_000 ? 0 : ms;
      });
    }

    it("waits the poll interval before each status read, also after progress", async () => {
      const { widget, api } = followingWidget();
      const log: string[] = [];
      logPauses(log);
      let attempt = 0;
      // A proxy cuts each stream after one batch.
      api.resumeStream = mock(async function* (): AsyncGenerator<
        Packet | StreamCursor
      > {
        attempt += 1;
        log.push(`attempt ${attempt}`);
        if (attempt === 1) {
          yield {
            obj: { user_message_id: 1, reserved_assistant_message_id: 2 },
          };
          yield { obj: { type: "message_start" } };
        }
        yield { obj: { type: "message_delta", content: `${attempt}` } };
        yield { stream_id: 5, next_cursor: attempt + 1, replay_complete: true };
        if (attempt === 3) {
          yield { obj: { type: "stop" } };
          return;
        }
        throw new TypeError("network error");
      });
      api.waitForSessionIdle = mock(
        async (
          _session: string,
          _signal: AbortSignal,
          _onUnconfirmed: () => void,
          attachable: (stream: ChatStream) => boolean = () => false
        ) => {
          log.push("status");
          return offer(attachable, 5);
        }
      );

      await widget["resumeStream"]("session", { streamId: null });

      expect(log).toEqual([
        "attempt 1",
        "pause",
        "status",
        "attempt 2",
        "pause",
        "status",
        "attempt 3",
        "status",
      ]);
      expect(widget["messages"][0]).toMatchObject({ content: "123" });
    });

    it("keeps following a stream after a 401, a 429 or a clean end before its first cursor", async () => {
      const { widget, api } = followingWidget();
      logPauses([]);
      const attempts: unknown[] = [];
      api.resumeStream = mock(async function* (
        _session: string,
        _signal: AbortSignal,
        from: { streamId: number; cursor: number } | null = null
      ): AsyncGenerator<Packet | StreamCursor, ResumeEnd> {
        attempts.push(from);
        switch (attempts.length) {
          case 1:
            yield {
              obj: { user_message_id: 1, reserved_assistant_message_id: 2 },
            };
            yield { obj: { type: "message_start" } };
            yield { stream_id: 5, next_cursor: 2, replay_complete: true };
            throw new TypeError("network error");
          case 2:
            throw new ApiError("Unauthorized", 401);
          case 3:
            throw new ApiError("Too many requests", 429);
          case 4:
            return "ended";
          default:
            yield { obj: { type: "message_delta", content: "Done" } };
            yield { obj: { type: "stop" } };
            return "ended";
        }
      });
      api.waitForSessionIdle = mock(
        async (
          _session: string,
          _signal: AbortSignal,
          _onUnconfirmed: () => void,
          attachable: (stream: ChatStream) => boolean = () => false
        ) => (offer(attachable, 5))
      );

      await widget["resumeStream"]("session", { streamId: null });

      const from = { streamId: 5, cursor: 2 };
      expect(attempts).toEqual([null, from, from, from, from]);
      expect(widget["messages"][0]).toMatchObject({
        id: 2,
        content: "Done",
        isStreaming: false,
      });
    });

    it("follows a new response that starts while the ended one is saved", async () => {
      const { widget, api } = followingWidget();
      const attempts: unknown[] = [];
      let pendingOnNewStream: string | undefined;
      api.resumeStream = mock(async function* (
        _session: string,
        _signal: AbortSignal,
        from: { streamId: number; cursor: number } | null = null
      ): AsyncGenerator<Packet | StreamCursor, ResumeEnd> {
        attempts.push(from);
        if (from === null) {
          yield {
            obj: { user_message_id: 1, reserved_assistant_message_id: 2 },
          };
          yield { stream_id: 5, next_cursor: 1, replay_complete: true };
          yield { obj: { type: "message_start" } };
          yield { obj: { type: "message_delta", content: "First" } };
          yield { obj: { type: "stop" } };
          return "ended";
        }
        yield {
          obj: { user_message_id: 3, reserved_assistant_message_id: 4 },
        };
        yield {
          obj: { type: "user_message", id: "sdk-3", message: "Other tab" },
        };
        yield { obj: approval("b") };
        pendingOnNewStream = pendingApproval(widget)?.request.approval_id;
        yield { stream_id: 6, next_cursor: 3, replay_complete: true };
        yield { obj: { type: "stop" } };
        return "ended";
      });
      const offered: boolean[] = [];
      api.waitForSessionIdle = mock(
        async (
          _session: string,
          _signal: AbortSignal,
          _onUnconfirmed: () => void,
          attachable: (stream: ChatStream) => boolean = () => false
        ) => {
          if (attempts.length > 1) return idle();
          // Stream 5 still saves; another client started stream 6.
          offered.push(attachable(chatStream(5)));
          return offer(attachable, 6);
        }
      );

      await widget["resumeStream"]("session", { streamId: null });

      expect(offered).toEqual([false]);
      expect(attempts).toEqual([null, { streamId: 6, cursor: 0 }]);
      expect(pendingOnNewStream).toBe("b");
      expect(widget["messages"].map((m) => [m.id, m.content])).toEqual([
        [2, "First"],
        [3, "Other tab"],
        [4, ""],
      ]);
    });

    it("follows a new response that starts while a sent one is saved", async () => {
      const { widget, api } = followingWidget();
      widget["inputValue"] = "send it";
      api.createChatSession = mock(async () => "session");
      api.streamMessage = mock(async function* (): AsyncGenerator<Packet> {
        yield {
          obj: { user_message_id: 1, reserved_assistant_message_id: 2 },
        };
        yield { obj: { type: "message_start" } };
        yield { obj: { type: "message_delta", content: "First" } };
        yield { obj: { type: "stop" } };
      });
      const attempts: unknown[] = [];
      let pendingOnNewStream: string | undefined;
      api.resumeStream = mock(async function* (
        _session: string,
        _signal: AbortSignal,
        from: { streamId: number; cursor: number } | null = null
      ): AsyncGenerator<Packet | StreamCursor, ResumeEnd> {
        attempts.push(from);
        yield {
          obj: { user_message_id: 3, reserved_assistant_message_id: 4 },
        };
        yield {
          obj: { type: "user_message", id: "sdk-3", message: "Other tab" },
        };
        yield { obj: approval("b") };
        pendingOnNewStream = pendingApproval(widget)?.request.approval_id;
        yield { stream_id: 4, next_cursor: 3, replay_complete: true };
        yield { obj: { type: "stop" } };
        return "ended";
      });
      const offered: boolean[] = [];
      api.waitForSessionIdle = mock(
        async (
          _session: string,
          _signal: AbortSignal,
          _onUnconfirmed: () => void,
          attachable?: (stream: ChatStream) => boolean
        ) => {
          // The new chat's baseline read offers no stream.
          if (!attachable || attempts.length > 0) return idle();
          // The sent response's stream 2 still saves; another client
          // started stream 4.
          offered.push(attachable(chatStream(2)));
          return offer(attachable, 4);
        }
      );

      await widget["sendMessage"]();

      expect(offered).toEqual([false]);
      expect(attempts).toEqual([{ streamId: 4, cursor: 0 }]);
      expect(pendingOnNewStream).toBe("b");
      expect(widget["messages"].map((m) => [m.id, m.content])).toEqual([
        [1, "send it"],
        [2, "First"],
        [3, "Other tab"],
        [4, ""],
      ]);
    });

    const approval = (id: string) => ({
      type: "tool_approval_request" as const,
      approval_id: id,
      tool_call_id: `call-${id}`,
      tool_name: "send_email",
      display_name: "Send email",
      arguments: {},
    });

    it("is attached again from its last cursor without repeating packets", async () => {
      const { widget, api } = followingWidget();
      logPauses([]);
      const attempts: unknown[] = [];
      let pendingAfterReattach: string | undefined;
      api.resumeStream = mock(async function* (
        _session: string,
        _signal: AbortSignal,
        from: { streamId: number; cursor: number } | null = null
      ): AsyncGenerator<Packet | StreamCursor> {
        attempts.push(from);
        if (from === null) {
          yield {
            obj: { user_message_id: 1, reserved_assistant_message_id: 2 },
          };
          yield { obj: { type: "message_start" } };
          yield { obj: { type: "message_delta", content: "Hel" } };
          yield { stream_id: 5, next_cursor: 3, replay_complete: true };
          yield { obj: { type: "message_delta", content: "lo" } };
          throw new TypeError("network error");
        }
        // Packets after the cursor arrive again.
        yield { obj: { type: "message_delta", content: "lo" } };
        yield { stream_id: 5, next_cursor: 4, replay_complete: true };
        yield { obj: approval("later") };
        pendingAfterReattach = pendingApproval(widget)?.request.approval_id;
        yield { stream_id: 5, next_cursor: 5, replay_complete: true };
        yield { obj: { type: "message_delta", content: " world" } };
        yield { obj: { type: "stop" } };
      });
      api.waitForSessionIdle = mock(
        async (
          _session: string,
          _signal: AbortSignal,
          _onUnconfirmed: () => void,
          attachable: (stream: ChatStream) => boolean = () => false
        ) => (offer(attachable, 5))
      );

      await widget["resumeStream"]("session", { streamId: null });

      expect(attempts).toEqual([null, { streamId: 5, cursor: 3 }]);
      expect(pendingAfterReattach).toBe("later");
      expect(widget["messages"]).toHaveLength(1);
      expect(widget["messages"][0]).toMatchObject({
        id: 2,
        content: "Hello world",
        approvals: [{ request: { approval_id: "later" } }],
      });
      expect(widget["isStreaming"]).toBe(false);
      expect(widget["error"]).toBeUndefined();
    });

    it("never requests a stream again after it has no buffer, and follows a new stream from its start", async () => {
      const { widget, api } = followingWidget();
      logPauses([]);
      const attempts: unknown[] = [];
      api.resumeStream = mock(async function* (
        _session: string,
        _signal: AbortSignal,
        from: { streamId: number; cursor: number } | null = null
      ): AsyncGenerator<Packet | StreamCursor> {
        attempts.push(from);
        if (from === null) {
          yield {
            obj: { user_message_id: 1, reserved_assistant_message_id: 2 },
          };
          yield { stream_id: 5, next_cursor: 1, replay_complete: true };
          yield { obj: approval("a") };
          throw new TypeError("network error");
        }
        // Stream 5 is gone (404).
        if (from.streamId === 5) return "noBuffer" as const;
        yield { obj: { user_message_id: 1, reserved_assistant_message_id: 2 } };
        yield { obj: approval("a") };
        yield {
          obj: {
            type: "tool_approval_resolved",
            approval_id: "a",
            outcome: "approved",
          },
        };
        yield { obj: { type: "message_start" } };
        yield { obj: { type: "message_delta", content: "Done" } };
        yield { obj: { type: "stop" } };
        yield { stream_id: 6, next_cursor: 6, replay_complete: true };
      });
      const offered: boolean[] = [];
      api.waitForSessionIdle = mock(
        async (
          _session: string,
          _signal: AbortSignal,
          _onUnconfirmed: () => void,
          attachable: (stream: ChatStream) => boolean = () => false
        ) => {
          // The status reports stream 5 until it reports stream 6.
          if (attempts.length < 3) {
            offered.push(attachable(chatStream(5)));
            if (attachable(chatStream(5))) return runs(chatStream(5));
          }
          return offer(attachable, 6);
        }
      );

      await widget["resumeStream"]("session", { streamId: null });

      expect(attempts).toEqual([
        null,
        { streamId: 5, cursor: 1 },
        { streamId: 6, cursor: 0 },
      ]);
      expect(offered).toEqual([true, false]);
      expect(widget["messages"]).toHaveLength(1);
      expect(widget["messages"][0]).toMatchObject({
        id: 2,
        content: "Done",
        isStreaming: false,
        approvals: [{ outcome: "approved" }],
      });
    });
  });
});

it.each([401, 405])("reports permanent readiness failure (%s)", async (status) => {
  mockFetch(async () => new Response(null, {status}));
  const api = new ApiService("https://onyx.test/api", async () => "key");
  await expect(api.waitForSessionIdle("session", new AbortController().signal, () => {})).rejects.toThrow(
    status === 401 ? "Authentication failed" : "does not support"
  );
  expect(globalThis.fetch).toHaveBeenCalledTimes(status === 401 ? 3 : 1);
});
