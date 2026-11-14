import { afterEach, describe, expect, it, mock, spyOn } from "bun:test";
import {
  ApiError,
  ApiService,
  type ResumeEnd,
} from "../src/services/api-service";
import {
  APPROVAL_PENDING_ERROR_CODE,
  type ApprovalEntry,
  approvalRecord,
  approvalStatus,
  ARGUMENT_ROWS_SHOWN,
  argumentRows,
  decidedStatus,
  findPendingApproval,
} from "../src/services/approvals";
import { processPacket } from "../src/services/stream-parser";
import type {
  Packet,
  StreamCursor,
  ToolApprovalRequest,
} from "../src/types/api-types";
import type { ChatMessage } from "../src/types/widget-types";
import { OnyxChatWidget } from "../src/widget";

const originalFetch = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = originalFetch;
  mock.restore();
});

function request(id: string, tool = "send_email"): ToolApprovalRequest {
  return {
    type: "tool_approval_request",
    approval_id: id,
    tool_call_id: `call-${id}`,
    tool_name: tool,
    display_name: "Send email",
    arguments: { to: "a@example.com" },
  };
}

function entry(
  id: string,
  outcome: ApprovalEntry["outcome"] = null
): ApprovalEntry {
  return { request: request(id), outcome };
}

function streamingMessage(approvals: ApprovalEntry[]): ChatMessage {
  return {
    id: 7,
    role: "assistant",
    content: "",
    timestamp: 0,
    isStreaming: true,
    approvals,
  };
}

describe("approval packets", () => {
  it("adds a request to the current response, or starts one", () => {
    const first = processPacket({ obj: request("a") }, null).message!;
    expect(first.role).toBe("assistant");
    expect(first.isStreaming).toBe(true);
    expect(first.approvals).toEqual([entry("a")]);

    const started = processPacket({ obj: { type: "message_start" } }, first);
    expect(started.message?.approvals).toEqual([entry("a")]);
  });

  it("records a known outcome and ignores an unknown one", () => {
    const current = streamingMessage([entry("a")]);
    const resolved = processPacket(
      {
        obj: {
          type: "tool_approval_resolved",
          approval_id: "a",
          outcome: "approved",
        },
      },
      current
    );
    expect(resolved.message?.approvals?.[0]?.outcome).toBe("approved");

    const unknown = processPacket(
      {
        obj: {
          type: "tool_approval_resolved",
          approval_id: "a",
          outcome: "deferred",
        },
      },
      current
    );
    expect(unknown.message).toBe(current);
  });
});

describe("approval status", () => {
  it("trusts the server outcome, then the local decision, then the stop", () => {
    expect(approvalStatus(entry("a", "cancelled"), "approved", false)).toBe(
      "closed"
    );
    expect(approvalStatus(entry("a", "rejected"), "approved", false)).toBe(
      "rejected"
    );
    expect(
      approvalStatus(entry("a", "approved_for_chat"), undefined, true)
    ).toBe("approvedForSession");
    expect(approvalStatus(entry("a"), "rejected", true)).toBe("rejected");
    expect(approvalStatus(entry("a"), undefined, true)).toBe("closed");
    expect(approvalStatus(entry("a"), undefined, false)).toBe("pending");
  });

  it("finds the first request that still waits", () => {
    const messages = [
      { ...streamingMessage([entry("old")]), isStreaming: false },
      streamingMessage([entry("a"), entry("b")]),
    ];
    const local = new Map([["a", "approved" as const]]);
    expect(findPendingApproval(messages, local)?.request.approval_id).toBe("b");
    // A response that ended closes what still waits.
    expect(
      findPendingApproval(
        messages.map((message) => ({ ...message, isStreaming: false })),
        local
      )
    ).toBeNull();
  });

  it("keeps requests pending after a stop for decisions, not after other stops", () => {
    const waiting = streamingMessage([entry("a")]);
    const stop = (stop_reason: string | null) =>
      processPacket({ obj: { type: "stop", stop_reason } }, waiting).message!;
    expect(
      findPendingApproval([stop("awaiting_approval")], new Map())?.request
        .approval_id
    ).toBe("a");
    expect(findPendingApproval([stop(null)], new Map())).toBeNull();
    expect(findPendingApproval([stop("user_cancelled")], new Map())).toBeNull();
  });

  it.each([
    ["APPROVED", "USER", "approved"],
    ["APPROVED", "SESSION_GRANT", "approvedForSession"],
    ["REJECTED", "USER", "rejected"],
    ["REJECTED", "POLICY", "disabled"],
  ] as const)(
    "shows the decision %s via %s as %s",
    (decision, decidedVia, status) => {
      expect(decidedStatus({ decision, decided_via: decidedVia })).toBe(status);
    }
  );

  it("writes one-line records", () => {
    expect(approvalRecord("approvedForSession", "Send email")).toBe(
      "Approved for this chat: Send email"
    );
    expect(approvalRecord("closed", "Send email")).toBe(
      "No longer waiting: Send email"
    );
    expect(approvalRecord("disabled", "Send email")).toBe(
      "Disabled: Send email"
    );
    expect(approvalRecord("pending", "Send email")).toBeNull();
  });

  it("truncates long values and shows nested values as JSON", () => {
    const rows = argumentRows({
      short: "hi",
      long: "x".repeat(301),
      list: ["a", 1],
      nested: { a: { b: 1 } },
      skipped: null,
    });
    expect(rows.map((r) => r.key)).toEqual(["short", "long", "list", "nested"]);
    expect(rows[0]!.preview).toBeNull();
    expect(rows[1]!.preview).toHaveLength(301);
    expect(rows[2]!.text).toBe("a, 1");
    expect(rows[3]!.mono).toBe(true);
  });
});

/** The text a template shows, without its markup or event handlers. */
function shownText(value: unknown): string {
  if (Array.isArray(value)) return value.map(shownText).join("");
  if (typeof value === "string" || typeof value === "number")
    return String(value);
  if (typeof value === "object" && value !== null && "values" in value)
    return shownText((value as { values: unknown[] }).values);
  return "";
}

describe("approval arguments from the model", () => {
  it("are kept in full and shown collapsed until the user expands them", () => {
    const body = "x".repeat(50_000);
    const items = Array.from({ length: 5_000 }, (_, i) => i);
    const message = processPacket(
      {
        obj: {
          ...request("a"),
          arguments: { body, items, ["__proto__"]: "kept as data" },
        },
      },
      null
    ).message!;
    const args = message.approvals![0]!.request.arguments;
    expect(args.body).toBe(body);
    expect(args.items).toEqual(items);
    expect(Object.hasOwn(args, "__proto__")).toBe(true);
    expect(Object.getPrototypeOf(args)).toBe(Object.prototype);

    const widget = new OnyxChatWidget();
    const card = () =>
      shownText(widget["renderApproval"](message.approvals![0]!, "pending"));
    expect(card().length).toBeLessThan(2_000);
    expect(card()).toContain("Show more");

    widget["toggleExpanded"](JSON.stringify(["a", "body"]));
    expect(card()).toContain(body);
    expect(card()).toContain("Show less");
    expect(card()).not.toContain(items.join(", "));
  });

  it("show a bounded number of rows until the user shows all", () => {
    const args = Object.fromEntries(
      Array.from({ length: ARGUMENT_ROWS_SHOWN + 5 }, (_, i) => [`k${i}`, i])
    );
    const approval: ApprovalEntry = {
      request: { ...request("a"), arguments: args },
      outcome: null,
    };
    const widget = new OnyxChatWidget();
    const card = () => shownText(widget["renderApproval"](approval, "pending"));
    const last = `k${ARGUMENT_ROWS_SHOWN + 4}`;
    expect(card()).not.toContain(last);
    expect(card()).toContain(`Show all ${ARGUMENT_ROWS_SHOWN + 5} arguments`);

    widget["toggleExpanded"](JSON.stringify(["a"]));
    expect(card()).toContain(last);
  });

  it("preview a large JSON value by lines and characters", () => {
    const [row] = argumentRows({ nested: { text: "y".repeat(5_000) } });
    expect(row!.text).toContain("y".repeat(5_000));
    expect(row!.preview!.length).toBeLessThan(1_100);
  });
});

describe("approval decisions", () => {
  it("posts the decision with the widget credential", async () => {
    const calls: { url: string; init?: RequestInit }[] = [];
    globalThis.fetch = mock(
      async (input: RequestInfo | URL, init?: RequestInit) => {
        calls.push({ url: String(input), init });
        return Response.json({
          approval_id: "a/b",
          decision: "APPROVED",
          decided_via: "SESSION_GRANT",
        });
      }
    ) as typeof fetch;
    const api = new ApiService("https://onyx.test/api", async () => "key");
    expect(await api.submitApprovalDecision("a/b", "approve_session")).toEqual(
      { decision: "APPROVED", decided_via: "SESSION_GRANT" }
    );
    expect(calls).toHaveLength(1);
    expect(calls[0]!.url).toBe(
      "https://onyx.test/api/chat/approvals/a%2Fb/decision"
    );
    expect(calls[0]!.init?.method).toBe("POST");
    expect(JSON.parse(String(calls[0]!.init?.body))).toEqual({
      decision: "approve_session",
    });
    expect(new Headers(calls[0]!.init?.headers).get("Authorization")).toBe(
      "Bearer key"
    );
  });

  it.each([404, 409])("reports a request that no longer waits (%s)", async (status) => {
    globalThis.fetch = mock(
      async () => new Response("gone", { status })
    ) as typeof fetch;
    const api = new ApiService("https://onyx.test/api", async () => "key");
    expect(await api.submitApprovalDecision("a", "reject")).toBe("closed");
  });

  it("throws other failures so the card can show an error", async () => {
    globalThis.fetch = mock(
      async () => new Response("boom", { status: 500 })
    ) as typeof fetch;
    const api = new ApiService("https://onyx.test/api", async () => "key");
    await expect(api.submitApprovalDecision("a", "reject")).rejects.toThrow();
  });

  it("replays a running response with its cursors", async () => {
    const urls: string[] = [];
    globalThis.fetch = mock(async (input: RequestInfo | URL) => {
      urls.push(String(input));
      return new Response(
        [
          JSON.stringify({ stream_id: 1, next_cursor: 2, replay_complete: true }),
          JSON.stringify({ placement: { turn_index: 0 }, obj: request("a") }),
          "",
        ].join("\n")
      );
    }) as typeof fetch;
    const api = new ApiService("https://onyx.test/api", async () => "key");
    const packets: (Packet | StreamCursor)[] = [];
    for await (const packet of api.resumeStream(
      "s",
      new AbortController().signal
    )) {
      packets.push(packet);
    }
    for await (const _ of api.resumeStream("s", new AbortController().signal, {
      streamId: 1,
      cursor: 2,
    })) {
      // drained
    }
    expect(urls).toEqual([
      "https://onyx.test/api/chat/chat-session/s/resume-stream?cursor=0",
      "https://onyx.test/api/chat/chat-session/s/resume-stream?stream_id=1&cursor=2",
    ]);
    expect(packets).toEqual([
      { stream_id: 1, next_cursor: 2, replay_complete: true },
      { placement: { turn_index: 0 }, obj: request("a") },
    ]);
  });

  it("ends a resume with noBuffer only on a 404, and ended on a body end", async () => {
    const statuses = [404, 200];
    globalThis.fetch = mock(
      async () => new Response("", { status: statuses.shift() })
    ) as typeof fetch;
    const api = new ApiService("https://onyx.test/api", async () => "key");
    const signal = new AbortController().signal;
    expect(await api.resumeStream("s", signal).next()).toEqual({
      done: true,
      value: "noBuffer",
    });
    expect(await api.resumeStream("s", signal).next()).toEqual({
      done: true,
      value: "ended",
    });
  });

  it.each([401, 403, 429])(
    "throws a resume failure the widget can retry (%s)",
    async (status) => {
      globalThis.fetch = mock(
        async () => new Response("denied", { status })
      ) as typeof fetch;
      const api = new ApiService("https://onyx.test/api", async () => "key");
      const error = await api
        .resumeStream("s", new AbortController().signal)
        .next()
        .catch((e: unknown) => e);
      expect(error).toBeInstanceOf(ApiError);
      expect((error as ApiError).status).toBe(status);
      expect(globalThis.fetch).toHaveBeenCalledTimes(1);
    }
  );

  it("surfaces the pending-approval code of a blocked send", async () => {
    globalThis.fetch = mock(async () =>
      Response.json(
        { error_code: APPROVAL_PENDING_ERROR_CODE, detail: "waiting" },
        { status: 409 }
      )
    ) as typeof fetch;
    const api = new ApiService("https://onyx.test/api", async () => "key");
    const stream = api.streamMessage({ message: "hi", chatSessionId: "s" });
    const error = await stream.next().catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).status).toBe(409);
    expect((error as ApiError).errorCode).toBe(APPROVAL_PENDING_ERROR_CODE);
  });
});

describe("widget while a request waits", () => {
  function waitingWidget() {
    const widget = new OnyxChatWidget();
    widget["config"] = { backendUrl: "https://onyx.test/api", apiKey: "key" };
    const api = new ApiService("https://onyx.test/api", async () => "key");
    widget["apiService"] = api;
    widget["chatSessionId"] = "session";
    widget["isStreaming"] = true;
    widget["messages"] = [streamingMessage([entry("a"), entry("b")])];
    // A decision with no stream attached follows the run again.
    api.resumeStream = mock(async function* (): AsyncGenerator<Packet> {});
    api.waitForSessionIdle = mock(async () => null);
    api.getChatSession = mock(async () => ({ messages: [], packets: [] }));
    return { widget, api };
  }

  it("keeps the draft and does not send", async () => {
    const { widget, api } = waitingWidget();
    api.streamMessage = mock(async function* () {});
    widget["inputValue"] = "next question";
    await widget["sendMessage"]();
    expect(api.streamMessage).not.toHaveBeenCalled();
    expect(widget["inputValue"]).toBe("next question");
  });

  it("closes a request that is gone at once", async () => {
    const { widget, api } = waitingWidget();
    api.submitApprovalDecision = mock(async () => "closed" as const);
    await widget["decideApproval"](request("a"), "approve_once");
    expect(widget["localApprovalStatuses"].get("a")).toBe("closed");
    expect(widget["pendingApproval"]?.request.approval_id).toBe("b");
  });

  it("stops reading at a stop for decisions, then follows the new stream after the decision", async () => {
    const widget = new OnyxChatWidget();
    widget["config"] = { backendUrl: "https://onyx.test/api", apiKey: "key" };
    const api = new ApiService("https://onyx.test/api", async () => "key");
    api.createChatSession = mock(async () => "session");
    api.waitForSessionIdle = mock(async () => null);
    api.submitApprovalDecision = mock(async () => ({
      decision: "APPROVED" as const,
      decided_via: "SESSION_GRANT",
    }));
    api.streamMessage = mock(async function* (): AsyncGenerator<Packet> {
      yield {
        obj: { user_message_id: 1, reserved_assistant_message_id: 2 },
      };
      yield { obj: request("a") };
      yield { obj: { type: "stop", stop_reason: "awaiting_approval" } };
    });
    let resolve!: () => void;
    const resolution = new Promise<void>((done) => (resolve = done));
    // Set once the widget has applied the continuation's replayed request
    let replayed = false;
    api.resumeStream = mock(async function* (): AsyncGenerator<
      Packet | StreamCursor
    > {
      yield { stream_id: 9, next_cursor: 0, replay_complete: false };
      yield {
        obj: { user_message_id: 1, reserved_assistant_message_id: 2 },
      };
      yield { obj: request("a") };
      replayed = true;
      await resolution;
      yield {
        obj: {
          type: "tool_approval_resolved",
          approval_id: "a",
          outcome: "approved_for_chat",
        },
      };
      yield { obj: { type: "message_start" } };
      yield { obj: { type: "message_delta", content: "Sent." } };
      yield { obj: { type: "stop" } };
      return "ended";
    });
    widget["apiService"] = api;
    widget["inputValue"] = "send it";

    await widget["sendMessage"]();
    expect(widget["isStreaming"]).toBe(false);
    expect(widget["pendingApproval"]?.request.approval_id).toBe("a");
    expect(api.waitForSessionIdle).not.toHaveBeenCalled();
    expect(api.resumeStream).not.toHaveBeenCalled();

    const deciding = widget["decideApproval"](request("a"), "approve_session");
    while (!replayed) await Bun.sleep(1);
    expect(api.resumeStream).toHaveBeenCalledWith(
      "session",
      expect.anything(),
      null
    );
    const status = () =>
      approvalStatus(
        widget["messages"].at(-1)!.approvals![0]!,
        widget["localApprovalStatuses"].get("a"),
        false
      );
    expect(widget["pendingApproval"]).toBeNull();
    expect(status()).toBe("approvedForSession");

    resolve();
    await deciding;
    while (widget["isStreaming"]) await Bun.sleep(1);
    expect(widget["localApprovalStatuses"].size).toBe(0);
    expect(status()).toBe("approvedForSession");
    expect(widget["messages"].map((m) => [m.id, m.content])).toEqual([
      [1, "send it"],
      [2, "Sent."],
    ]);
  });

  it("records an approval of a tool disabled meanwhile as disabled", async () => {
    const { widget, api } = waitingWidget();
    api.submitApprovalDecision = mock(async () => ({
      decision: "REJECTED" as const,
      decided_via: "POLICY",
    }));
    await widget["decideApproval"](request("a"), "approve_once");
    expect(widget["localApprovalStatuses"].get("a")).toBe("disabled");
  });

  it("keeps the card actionable after a failed decision", async () => {
    const { widget, api } = waitingWidget();
    api.submitApprovalDecision = mock(async () => {
      throw new Error("offline");
    });
    await widget["decideApproval"](request("a"), "reject");
    expect(widget["failedApprovals"].has("a")).toBe(true);
    expect(widget["submittingApprovals"].size).toBe(0);
    expect(widget["pendingApproval"]?.request.approval_id).toBe("a");
  });

  it("keeps the draft when the server reports a waiting request", async () => {
    const widget = new OnyxChatWidget();
    widget["config"] = { backendUrl: "https://onyx.test/api", apiKey: "key" };
    const api = new ApiService("https://onyx.test/api", async () => "key");
    api.createChatSession = mock(async () => "session");
    api.waitForSessionIdle = mock(async () => {});
    api.streamMessage = mock(async function* () {
      throw new ApiError("waiting", 409, APPROVAL_PENDING_ERROR_CODE);
    });
    api.getChatSession = mock(async () => ({
      messages: [
        { message_id: 1, message_type: "user" },
        { message_id: 2, message_type: "assistant", parent_message: 1 },
      ],
      packets: [
        [
          { obj: request("a") },
          { obj: { type: "stop", stop_reason: "awaiting_approval" } },
        ],
      ],
    }));
    // The waiting response has no running stream.
    api.resumeStream = mock(async function* (): AsyncGenerator<
      Packet,
      ResumeEnd
    > {
      return "noBuffer";
    });
    widget["apiService"] = api;
    widget["inputValue"] = "blocked";
    await widget["sendMessage"]();
    expect(widget["inputValue"]).toBe("blocked");
    expect(widget["error"]).toContain("waits for your decision");
    // The waiting request shows from the saved session, so the user can decide it.
    expect(api.getChatSession).toHaveBeenCalled();
    expect(widget["pendingApproval"]?.request.approval_id).toBe("a");
    expect(widget["messages"].map((message) => message.id)).toEqual([2]);
  });

  it("shows a waiting request that the restored snapshot lacks from the saved session", async () => {
    const widget = new OnyxChatWidget();
    widget["config"] = { backendUrl: "https://onyx.test/api", apiKey: "key" };
    const api = new ApiService("https://onyx.test/api", async () => "key");
    api.resumeStream = mock(async function* (): AsyncGenerator<
      Packet,
      ResumeEnd
    > {
      return "noBuffer";
    });
    api.waitForSessionIdle = mock(async () => null);
    api.getChatSession = mock(async () => ({
      messages: [
        { message_id: 6, message_type: "user" },
        { message_id: 7, message_type: "assistant", parent_message: 6 },
      ],
      packets: [
        [
          { obj: { type: "user_message", id: "sdk-1", message: "Email Bo" } },
          { obj: request("a") },
          { obj: { type: "stop", stop_reason: "awaiting_approval" } },
        ],
      ],
    }));
    widget["apiService"] = api;
    // Saved before the request was
    widget["messages"] = [];

    await widget["resumeStream"]("session", { showLatest: true });

    expect(widget["pendingApproval"]?.request.approval_id).toBe("a");
    expect(widget["messages"].map((m) => [m.id, m.role])).toEqual([
      [6, "user"],
      [7, "assistant"],
    ]);
  });

  /** A sessionStorage stand-in; returns its contents and a cleanup. */
  function fakeSessionStorage() {
    const stored = new Map<string, string>();
    globalThis.sessionStorage = {
      getItem: (key: string) => stored.get(key) ?? null,
      setItem: (key: string, value: string) => void stored.set(key, value),
      removeItem: (key: string) => void stored.delete(key),
    } as Storage;
    return {
      stored,
      restore: () => Reflect.deleteProperty(globalThis, "sessionStorage"),
    };
  }

  function restoredWidget() {
    const widget = new OnyxChatWidget();
    widget["config"] = { backendUrl: "https://onyx.test/api", apiKey: "key" };
    widget["apiService"] = new ApiService(
      "https://onyx.test/api",
      async () => "key"
    );
    // Saved while the request waited
    widget["messages"] = [streamingMessage([entry("a")])];
    return widget;
  }

  it("finishes a restored response from the saved session when replay is gone", async () => {
    const { stored, restore } = fakeSessionStorage();
    const urls: string[] = [];
    globalThis.fetch = mock(async (input: RequestInfo | URL) => {
      const url = String(input);
      urls.push(url);
      if (url.endsWith("/status"))
        return Response.json({ is_processing: false });
      if (url.includes("/get-chat-session/")) {
        return Response.json({
          messages: [
            { message_id: 6, message_type: "user" },
            { message_id: 7, message_type: "assistant" },
          ],
          packets: [
            [
              { obj: request("a") },
              {
                obj: {
                  type: "tool_approval_resolved",
                  approval_id: "a",
                  outcome: "approved",
                },
              },
              { obj: { type: "message_start" } },
              { obj: { type: "message_delta", content: "Sent." } },
              { obj: { type: "stop" } },
            ],
          ],
        });
      }
      return new Response("none", { status: 404 });
    }) as typeof fetch;
    const widget = restoredWidget();

    try {
      await widget["resumeStream"]("session");
    } finally {
      restore();
    }

    expect(urls.at(-1)).toBe(
      "https://onyx.test/api/chat/get-chat-session/session"
    );
    expect(widget["isStreaming"]).toBe(false);
    expect(widget["messages"]).toHaveLength(1);
    expect(widget["messages"][0]).toMatchObject({
      id: 7,
      content: "Sent.",
      isStreaming: false,
      approvals: [{ outcome: "approved" }],
    });
    const saved = JSON.parse(stored.get("onyx-widget-session") ?? "null");
    expect(saved.messages[0]).toMatchObject({
      content: "Sent.",
      isStreaming: false,
    });
  });

  it("restores a missing question from the saved session before its answer", async () => {
    const { stored, restore } = fakeSessionStorage();
    globalThis.fetch = mock(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/status"))
        return Response.json({ is_processing: false });
      if (url.includes("/get-chat-session/")) {
        return Response.json({
          messages: [
            { message_id: 6, message_type: "user" },
            { message_id: 7, message_type: "assistant", parent_message: 6 },
          ],
          packets: [
            [
              {
                obj: { type: "user_message", id: "sdk-1", message: "Email Bo" },
              },
              { obj: request("a") },
              { obj: { type: "message_start" } },
              { obj: { type: "message_delta", content: "Sent." } },
              { obj: { type: "stop" } },
            ],
          ],
        });
      }
      return new Response("none", { status: 404 });
    }) as typeof fetch;
    const widget = restoredWidget();

    try {
      await widget["resumeStream"]("session");
    } finally {
      restore();
    }

    const shown = widget["messages"].map((m) => [m.id, m.role, m.content]);
    expect(shown).toEqual([
      [6, "user", "Email Bo"],
      [7, "assistant", "Sent."],
    ]);
    const saved = JSON.parse(stored.get("onyx-widget-session") ?? "null");
    expect(saved.messages.map((m: ChatMessage) => m.id)).toEqual([6, 7]);
  });

  /** Restores a stored transcript whose last question has no answer. */
  async function restoreUnanswered(session: unknown) {
    const { stored, restore } = fakeSessionStorage();
    const messages: ChatMessage[] = [
      { id: 1, role: "user", content: "first", timestamp: 0 },
      { id: 2, role: "assistant", content: "first answer", timestamp: 0 },
      { id: 3, role: "user", content: "second", timestamp: 0 },
    ];
    stored.set(
      "onyx-widget-session",
      JSON.stringify({
        sessionId: "session",
        messages,
        timestamp: Date.now(),
        identity: "shared",
      })
    );
    globalThis.fetch = mock(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/status"))
        return Response.json({ is_processing: false });
      if (url.includes("/get-chat-session/")) return Response.json(session);
      return new Response("none", { status: 404 });
    }) as typeof fetch;
    const widget = restoredWidget();
    widget["messages"] = [];
    widget["currentIdentity"] = async () => "shared";
    try {
      widget["restoreSession"]();
      while (!widget["sessionRestored"]) await Bun.sleep(1);
      await Bun.sleep(1);
      while (widget["isStreaming"]) await Bun.sleep(1);
    } finally {
      restore();
    }
    const saved = JSON.parse(stored.get("onyx-widget-session") ?? "null");
    return {
      shown: widget["messages"].map((m) => [m.id, m.content]),
      saved: saved.messages.map((m: ChatMessage) => [m.id, m.content]),
    };
  }

  it("answers a stored question from the saved session when its replay is gone", async () => {
    const { shown, saved } = await restoreUnanswered({
      messages: [
        { message_id: 1, message_type: "user" },
        { message_id: 2, message_type: "assistant", parent_message: 1 },
        { message_id: 3, message_type: "user", parent_message: 2 },
        { message_id: 4, message_type: "assistant", parent_message: 3 },
      ],
      packets: [
        [],
        [
          { obj: { type: "message_start" } },
          { obj: { type: "message_delta", content: "second answer" } },
          { obj: { type: "stop" } },
        ],
      ],
    });
    const expected = [
      [1, "first"],
      [2, "first answer"],
      [3, "second"],
      [4, "second answer"],
    ];
    expect(shown).toEqual(expected);
    expect(saved).toEqual(expected);
  });

  it("removes a stored question the saved session has no answer for", async () => {
    const { shown, saved } = await restoreUnanswered({
      messages: [
        { message_id: 1, message_type: "user" },
        { message_id: 2, message_type: "assistant", parent_message: 1 },
      ],
      packets: [[]],
    });
    const expected = [
      [1, "first"],
      [2, "first answer"],
    ];
    expect(shown).toEqual(expected);
    expect(saved).toEqual(expected);
  });

  it("sends a new question under the latest saved answer, not an unanswered question", async () => {
    const widget = restoredWidget();
    widget["chatSessionId"] = "session";
    widget["messages"] = [
      { id: 1, role: "user", content: "first", timestamp: 0 },
      { id: 2, role: "assistant", content: "first answer", timestamp: 0 },
      { id: 3, role: "user", content: "second", timestamp: 0 },
    ];
    widget["inputValue"] = "third";
    const api = widget["apiService"];
    api.waitForSessionIdle = mock(async () => null);
    api.streamMessage = mock(async function* (): AsyncGenerator<Packet> {
      yield { obj: { type: "stop" } };
    });

    await widget["sendMessage"]();

    expect(api.streamMessage).toHaveBeenCalledWith(
      expect.objectContaining({ parentMessageId: 2 })
    );
  });

  it("keeps a restored response unfinished when the saved session cannot load", async () => {
    const { stored, restore } = fakeSessionStorage();
    globalThis.fetch = mock(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/status"))
        return Response.json({ is_processing: false });
      return new Response("none", {
        status: url.includes("/get-chat-session/") ? 403 : 404,
      });
    }) as typeof fetch;
    const widget = restoredWidget();

    try {
      await widget["resumeStream"]("session");
    } finally {
      restore();
    }

    expect(widget["error"]).toBeDefined();
    expect(widget["messages"][0]!.isStreaming).toBe(true);
    expect(stored.has("onyx-widget-session")).toBe(false);
  });

  it("keeps a restored request pending when the resume fails, and follows the run after a decision", async () => {
    const setTimer = globalThis.setTimeout;
    spyOn(globalThis, "setTimeout").mockImplementation(
      (callback, delay, ...args) =>
        setTimer(callback, delay === 1_000 ? 0 : delay, ...args)
    );
    const widget = restoredWidget();
    const api = widget["apiService"];
    api.resumeStream = mock(async function* (): AsyncGenerator<Packet> {
      throw new TypeError("Failed to fetch");
    });
    api.waitForSessionIdle = mock(async () => {
      throw new Error("Cannot reach the server");
    });

    await widget["resumeStream"]("session");

    expect(widget["error"]).toBe("Cannot reach the server");
    expect(widget["isStreaming"]).toBe(false);
    expect(widget["abortController"]).toBeUndefined();
    expect(widget["pendingApproval"]?.request.approval_id).toBe("a");

    widget["chatSessionId"] = "session";
    api.submitApprovalDecision = mock(async () => ({
      decision: "APPROVED" as const,
      decided_via: "USER",
    }));
    api.resumeStream = mock(async function* (): AsyncGenerator<
      Packet | StreamCursor
    > {
      yield { obj: { user_message_id: 6, reserved_assistant_message_id: 7 } };
      yield { obj: request("a") };
      yield {
        obj: {
          type: "tool_approval_resolved",
          approval_id: "a",
          outcome: "approved",
        },
      };
      yield { obj: { type: "message_start" } };
      yield { obj: { type: "message_delta", content: "Sent." } };
      yield { obj: { type: "stop" } };
      yield { stream_id: 4, next_cursor: 6, replay_complete: true };
    });
    api.waitForSessionIdle = mock(async () => null);

    await widget["decideApproval"](request("a"), "approve_once");
    while (widget["isStreaming"] || !api.waitForSessionIdle.mock.calls.length)
      await Bun.sleep(1);

    expect(api.resumeStream).toHaveBeenCalledTimes(1);
    expect(widget["messages"].at(-1)).toMatchObject({
      id: 7,
      content: "Sent.",
      isStreaming: false,
      approvals: [{ outcome: "approved" }],
    });
  });

  it("resumes a running response that no saved message records", async () => {
    const { stored, restore } = fakeSessionStorage();
    stored.set(
      "onyx-widget-session",
      JSON.stringify({
        sessionId: "session",
        messages: [],
        timestamp: Date.now(),
        identity: "shared",
      })
    );
    const widget = restoredWidget();
    widget["messages"] = [];
    const api = widget["apiService"];
    widget["currentIdentity"] = async () => "shared";
    let pending: ApprovalEntry | null = null;
    api.resumeStream = mock(async function* (): AsyncGenerator<Packet> {
      yield { obj: { user_message_id: 1, reserved_assistant_message_id: 7 } };
      yield { obj: request("a") };
      pending = widget["pendingApproval"];
    });
    api.waitForSessionIdle = mock(async () => {});
    api.getChatSession = mock(async () => ({ messages: [], packets: [] }));

    try {
      widget["restoreSession"]();
      while (!widget["sessionRestored"]) await Bun.sleep(1);
      while (widget["isStreaming"]) await Bun.sleep(1);
    } finally {
      restore();
    }

    expect(api.resumeStream).toHaveBeenCalledWith(
      "session",
      expect.anything(),
      null
    );
    expect(pending?.request.approval_id).toBe("a");
  });

  it("restores the question of a turn accepted before the reload saved it", async () => {
    const { stored, restore } = fakeSessionStorage();
    const earlier: ChatMessage[] = [
      { id: 1, role: "user", content: "first", timestamp: 0 },
      { id: 2, role: "assistant", content: "first answer", timestamp: 0 },
    ];
    stored.set(
      "onyx-widget-session",
      JSON.stringify({
        sessionId: "session",
        messages: earlier,
        timestamp: Date.now(),
        identity: "shared",
      })
    );
    const widget = restoredWidget();
    widget["messages"] = [];
    widget["currentIdentity"] = async () => "shared";
    const api = widget["apiService"];
    api.resumeStream = mock(async function* (): AsyncGenerator<
      Packet | StreamCursor
    > {
      yield { obj: { user_message_id: 3, reserved_assistant_message_id: 4 } };
      yield {
        obj: { type: "user_message", id: "sdk-1", message: "second question" },
      };
      yield { obj: request("a") };
      yield { stream_id: 5, next_cursor: 3, replay_complete: true };
    });
    api.waitForSessionIdle = mock(async () => null);
    api.getChatSession = mock(async () => ({ messages: [], packets: [] }));

    try {
      widget["restoreSession"]();
      while (!widget["sessionRestored"]) await Bun.sleep(1);
      await Bun.sleep(1);
      while (widget["isStreaming"]) await Bun.sleep(1);
    } finally {
      restore();
    }

    const shown = widget["messages"].map((m) => [m.id, m.role, m.content]);
    expect(shown).toEqual([
      [1, "user", "first"],
      [2, "assistant", "first answer"],
      [3, "user", "second question"],
      [4, "assistant", ""],
    ]);
    const saved = JSON.parse(stored.get("onyx-widget-session") ?? "null");
    expect(saved.messages.map((m: ChatMessage) => m.id)).toEqual([1, 2, 3, 4]);
  });

  it("follows a response again when its stream ends before it does", async () => {
    const widget = new OnyxChatWidget();
    widget["config"] = { backendUrl: "https://onyx.test/api", apiKey: "key" };
    const api = new ApiService("https://onyx.test/api", async () => "key");
    api.createChatSession = mock(async () => "session");
    api.waitForSessionIdle = mock(async () => {});
    api.streamMessage = mock(async function* (): AsyncGenerator<Packet> {
      yield { obj: { user_message_id: 1, reserved_assistant_message_id: 2 } };
      yield { obj: request("a") };
    });
    api.resumeStream = mock(async function* (): AsyncGenerator<Packet> {
      yield { obj: { user_message_id: 1, reserved_assistant_message_id: 2 } };
      yield { obj: request("a") };
      yield {
        obj: {
          type: "tool_approval_resolved",
          approval_id: "a",
          outcome: "rejected",
        },
      };
      yield { obj: { type: "stop" } };
    });
    widget["apiService"] = api;
    widget["inputValue"] = "send it";

    await widget["sendMessage"]();

    expect(api.resumeStream).toHaveBeenCalledWith(
      "session",
      expect.anything(),
      null
    );
    expect(widget["messages"].at(-1)).toMatchObject({
      id: 2,
      isStreaming: false,
      approvals: [{ outcome: "rejected" }],
    });
  });
});
