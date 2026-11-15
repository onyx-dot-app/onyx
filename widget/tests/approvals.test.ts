import { afterEach, describe, expect, it, mock } from "bun:test";
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
import {
  type ApprovalCardView,
  renderApprovalCard,
} from "../src/services/approval-card";
import { processPacket } from "../src/services/stream-parser";
import type {
  ChatSessionDetail,
  ChatStream,
  Packet,
  StreamCursor,
  ToolApprovalRequest,
} from "../src/types/api-types";
import { mockFetch, mockTimeouts } from "./mocks";
import { chatStream, idle, offer, runs } from "./session-status";
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

  it("applies a resolution that arrives again, as a continuation sends it, once", () => {
    const resolution: Packet = {
      obj: {
        type: "tool_approval_resolved",
        approval_id: "a",
        outcome: "approved",
      },
    };
    const replayed = processPacket(
      resolution,
      streamingMessage([entry("a"), entry("b")])
    ).message;
    const live = processPacket(resolution, replayed).message;
    expect(live).toEqual(replayed);
    expect(live?.approvals).toEqual([entry("a", "approved"), entry("b")]);
  });
});

describe("approval status", () => {
  it("trusts the server outcome, then the local decision", () => {
    expect(approvalStatus(entry("a", "cancelled"), "approved")).toBe("closed");
    expect(approvalStatus(entry("a", "rejected"), "approved")).toBe("rejected");
    expect(approvalStatus(entry("a", "approved_for_chat"), undefined)).toBe(
      "approvedForSession"
    );
    expect(approvalStatus(entry("a"), "rejected")).toBe("rejected");
    expect(approvalStatus(entry("a"), "submitting")).toBe("pending");
    expect(approvalStatus(entry("a"), undefined)).toBe("pending");
  });

  it("keeps a subagent request out of the send gate", () => {
    const agentEntry: ApprovalEntry = {
      request: { ...request("c"), agent_name: "Research" },
      outcome: null,
    };
    expect(approvalStatus(agentEntry, undefined)).toBe("pending");
    expect(
      findPendingApproval(
        [{ ...streamingMessage([agentEntry]), awaitingApproval: true }],
        new Map()
      )
    ).toBeNull();
  });

  it("finds the first request that still waits", () => {
    const messages = [
      { ...streamingMessage([entry("old", "cancelled")]), isStreaming: false },
      streamingMessage([entry("a"), entry("b")]),
    ];
    const local = new Map([["a", "approved" as const]]);
    expect(findPendingApproval(messages, local)?.request.approval_id).toBe("b");
  });

  it.each(["awaiting_approval", null, "user_cancelled", "finished"])(
    "keeps a request pending after a %s stop until the server resolves it",
    (stop_reason) => {
      const waiting = streamingMessage([entry("a")]);
      const stopped = processPacket(
        { obj: { type: "stop", stop_reason } },
        waiting
      ).message!;
      expect(
        findPendingApproval([stopped], new Map())?.request.approval_id
      ).toBe("a");
      const cancelled = processPacket(
        {
          obj: {
            type: "tool_approval_resolved",
            approval_id: "a",
            outcome: "cancelled",
          },
        },
        stopped
      ).message!;
      expect(findPendingApproval([cancelled], new Map())).toBeNull();
      expect(approvalStatus(cancelled.approvals![0]!, undefined)).toBe(
        "closed"
      );
    }
  );

  it.each([
    ["APPROVED", "USER", "approved"],
    ["APPROVED", "SESSION_GRANT", "approvedForSession"],
    ["REJECTED", "USER", "rejected"],
    ["REJECTED", "POLICY", "disabled"],
  ] as const)(
    "shows the decision %s via %s as %s",
    (decision, decidedVia, status) => {
      expect(
        decidedStatus({ decision, decided_via: decidedVia, continuation: null })
      ).toBe(status);
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

function view(expanded: ReadonlySet<string>): ApprovalCardView {
  return {
    submitting: false,
    failed: false,
    expanded,
    onDecide: () => {},
    onToggle: () => {},
  };
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

    const expanded = new Set<string>();
    const card = () =>
      shownText(
        renderApprovalCard(message.approvals![0]!, "pending", view(expanded))
      );
    expect(card().length).toBeLessThan(2_000);
    expect(card()).toContain("Show more");

    expanded.add(JSON.stringify(["a", "body"]));
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
    const expanded = new Set<string>();
    const card = () =>
      shownText(renderApprovalCard(approval, "pending", view(expanded)));
    const last = `k${ARGUMENT_ROWS_SHOWN + 4}`;
    expect(card()).not.toContain(last);
    expect(card()).toContain(`Show all ${ARGUMENT_ROWS_SHOWN + 5} arguments`);

    expanded.add(JSON.stringify(["a"]));
    expect(card()).toContain(last);
  });

  it("name the subagent that asks", () => {
    const approval: ApprovalEntry = {
      request: { ...request("c"), agent_name: "Research" },
      outcome: null,
    };
    expect(
      shownText(renderApprovalCard(approval, "pending", view(new Set())))
    ).toContain("Research wants to run Send email");
    expect(
      shownText(renderApprovalCard(entry("a"), "pending", view(new Set())))
    ).not.toContain("wants to run");
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
    mockFetch(
      async (input: RequestInfo | URL, init?: RequestInit) => {
        calls.push({ url: String(input), init });
        return Response.json({
          approval_id: "a/b",
          decision: "APPROVED",
          decided_via: "SESSION_GRANT",
          continuation: { stream_id: 9, response_ids: [7] },
        });
      }
    );
    const api = new ApiService("https://onyx.test/api", async () => "key");
    expect(await api.submitApprovalDecision("a/b", "approve_session")).toEqual(
      {
        decision: "APPROVED",
        decided_via: "SESSION_GRANT",
        continuation: { stream_id: 9, response_ids: [7] },
      }
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

  it("reads a decision that resumed nothing as no continuation", async () => {
    mockFetch(async () =>
      Response.json({
        decision: "REJECTED",
        decided_via: "USER",
        continuation: null,
      })
    );
    const api = new ApiService("https://onyx.test/api", async () => "key");
    expect(await api.submitApprovalDecision("a", "reject")).toEqual({
      decision: "REJECTED",
      decided_via: "USER",
      continuation: null,
    });
  });

  it.each([404, 409])("reports a request that no longer waits (%s)", async (status) => {
    mockFetch(
      async () => new Response("gone", { status })
    );
    const api = new ApiService("https://onyx.test/api", async () => "key");
    expect(await api.submitApprovalDecision("a", "reject")).toBe("closed");
  });

  it("throws other failures so the card can show an error", async () => {
    mockFetch(
      async () => new Response("boom", { status: 500 })
    );
    const api = new ApiService("https://onyx.test/api", async () => "key");
    await expect(api.submitApprovalDecision("a", "reject")).rejects.toThrow();
  });

  it("replays a running response with its cursors", async () => {
    const urls: string[] = [];
    mockFetch(async (input: RequestInfo | URL) => {
      urls.push(String(input));
      return new Response(
        [
          JSON.stringify({ stream_id: 1, next_cursor: 2, replay_complete: true }),
          JSON.stringify({ placement: { turn_index: 0 }, obj: request("a") }),
          "",
        ].join("\n")
      );
    });
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

  it("passes over the end of a continuation's replayed prefix", async () => {
    mockFetch(
      async () =>
        new Response(
          [
            JSON.stringify({ obj: request("a") }),
            JSON.stringify({
              placement: { turn_index: 0 },
              obj: { type: "replay_end" },
            }),
            JSON.stringify({ obj: { type: "message_start" } }),
          ].join("\n")
        )
    );
    const api = new ApiService("https://onyx.test/api", async () => "key");
    let message: ChatMessage | null = null;
    for await (const packet of api.resumeStream(
      "s",
      new AbortController().signal
    )) {
      if (!("next_cursor" in packet))
        message = processPacket(packet, message).message;
    }
    expect(message?.approvals).toEqual([entry("a")]);
    // It starts no answer, sets no status and ends nothing.
    expect(processPacket({ obj: { type: "replay_end" } }, null)).toEqual({
      message: null,
    });
  });

  it("ends a resume with noBuffer only on a 404, and ended on a body end", async () => {
    const statuses = [404, 200];
    mockFetch(
      async () => new Response("", { status: statuses.shift() })
    );
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
      mockFetch(
        async () => new Response("denied", { status })
      );
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
    mockFetch(async () =>
      Response.json(
        { error_code: APPROVAL_PENDING_ERROR_CODE, detail: "waiting" },
        { status: 409 }
      )
    );
    const api = new ApiService("https://onyx.test/api", async () => "key");
    const stream = api.streamMessage({ message: "hi", chatSessionId: "s" });
    const error = await stream.next().catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).status).toBe(409);
    expect((error as ApiError).errorCode).toBe(APPROVAL_PENDING_ERROR_CODE);
  });
});

/** Resolves once `condition` holds; fails after `timeoutMs`. */
async function waitUntil(condition: () => boolean, timeoutMs = 2_000) {
  const deadline = Date.now() + timeoutMs;
  while (!condition()) {
    if (Date.now() > deadline) throw new Error("The condition never held");
    await Bun.sleep(1);
  }
}

/** Ends the pauses of the poll interval at once. */
function skipPollPauses() {
  mockTimeouts((ms) => (ms === 1_000 ? 0 : ms));
}

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
    saved: (): ChatMessage[] | undefined =>
      JSON.parse(stored.get("onyx-widget-session") ?? "null")?.messages,
    restore: () => Reflect.deleteProperty(globalThis, "sessionStorage"),
  };
}

const continuation = (streamId: number) => ({
  decision: "APPROVED" as const,
  decided_via: "USER",
  continuation: { stream_id: streamId, response_ids: [7] },
});

describe("widget while a request waits", () => {
  /** The session's response 7 stopped while requests a and b wait. */
  function waitingWidget() {
    skipPollPauses();
    const widget = new OnyxChatWidget();
    widget["config"] = { backendUrl: "https://onyx.test/api", apiKey: "key" };
    widget["currentIdentity"] = async () => "user";
    const api = new ApiService("https://onyx.test/api", async () => "key");
    widget["apiService"] = api;
    widget["chatSessionId"] = "session";
    widget["messages"] = [
      {
        ...streamingMessage([entry("a"), entry("b")]),
        isStreaming: false,
        awaitingApproval: true,
      },
    ];
    // The suspended response has no running stream.
    api.resumeStream = mock(async function* (): AsyncGenerator<
      Packet | StreamCursor,
      ResumeEnd
    > {
      return "noBuffer";
    });
    api.waitForSessionIdle = mock(async () => idle());
    api.getChatSession = mock(
      async (): Promise<ChatSessionDetail> => ({ messages: [], packets: [] })
    );
    return { widget, api };
  }

  const status = (widget: OnyxChatWidget, id: string) => {
    const message = widget["messages"].find((item) =>
      item.approvals?.some((approval) => approval.request.approval_id === id)
    )!;
    const approval = message.approvals!.find(
      (item) => item.request.approval_id === id
    )!;
    return approvalStatus(approval, widget["localApprovals"].get(id));
  };

  it("follows the continuation the decision names from its start, while a sibling still shows as waiting", async () => {
    const { widget, api } = waitingWidget();
    // "Approve for this chat" also approved b on the server.
    api.submitApprovalDecision = mock(async () => ({
      ...continuation(9),
      decided_via: "SESSION_GRANT",
    }));
    api.resumeStream = mock(async function* (): AsyncGenerator<
      Packet | StreamCursor
    > {
      yield { stream_id: 9, next_cursor: 0, replay_complete: false };
      yield { obj: { user_message_id: 6, reserved_assistant_message_id: 7 } };
      yield { obj: request("a") };
      yield { obj: request("b") };
      for (const id of ["a", "b"]) {
        yield {
          obj: {
            type: "tool_approval_resolved",
            approval_id: id,
            outcome: "approved_for_chat",
          },
        };
      }
      yield { obj: { type: "message_start" } };
      yield { obj: { type: "message_delta", content: "Sent." } };
      yield { obj: { type: "stop" } };
    });

    await widget["decideApproval"](request("a"), "approve_session");
    await waitUntil(() => widget["messages"][0]?.content === "Sent.");

    expect(api.resumeStream).toHaveBeenCalledTimes(1);
    expect(api.resumeStream).toHaveBeenCalledWith(
      "session",
      expect.anything(),
      { streamId: 9, cursor: 0 }
    );
    expect(status(widget, "a")).toBe("approvedForSession");
    expect(status(widget, "b")).toBe("approvedForSession");
    expect(widget["localApprovals"].size).toBe(0);
    expect(widget["pendingApproval"]).toBeNull();
  });

  it("follows nothing after a decision that names no continuation", async () => {
    const { widget, api } = waitingWidget();
    api.submitApprovalDecision = mock(async () => ({
      decision: "APPROVED" as const,
      decided_via: "USER",
      continuation: null,
    }));

    await widget["decideApproval"](request("a"), "approve_once");

    expect(api.resumeStream).not.toHaveBeenCalled();
    expect(api.waitForSessionIdle).not.toHaveBeenCalled();
    expect(status(widget, "a")).toBe("approved");
    expect(widget["pendingApproval"]?.request.approval_id).toBe("b");
  });

  it("follows the resume stream that the status reports after the last decision names no continuation", async () => {
    const { widget, api } = waitingWidget();
    widget["messages"] = [
      {
        ...streamingMessage([entry("a")]),
        isStreaming: false,
        awaitingApproval: true,
      },
    ];
    // Another turn held the chat when the decision landed.
    api.submitApprovalDecision = mock(async () => ({
      decision: "APPROVED" as const,
      decided_via: "USER",
      continuation: null,
    }));
    let reads = 0;
    api.waitForSessionIdle = mock(
      async (
        _session: string,
        _signal: AbortSignal,
        _onUnconfirmed: () => void,
        attachable: (stream: ChatStream) => boolean = () => false
      ) => {
        reads += 1;
        return reads === 1 ? offer(attachable, 9) : idle();
      }
    );
    api.resumeStream = mock(async function* (
      _session: string,
      _signal: AbortSignal,
      from: { streamId: number; cursor: number } | null = null
    ): AsyncGenerator<Packet | StreamCursor, ResumeEnd> {
      if (from === null) return "noBuffer";
      yield { stream_id: 9, next_cursor: 0, replay_complete: false };
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
      return "ended";
    });

    await widget["decideApproval"](request("a"), "approve_once");
    await waitUntil(() => widget["abortController"] === undefined);

    expect(api.resumeStream).toHaveBeenLastCalledWith(
      "session",
      expect.anything(),
      { streamId: 9, cursor: 0 }
    );
    expect(widget["messages"][0]?.content).toBe("Sent.");
    expect(status(widget, "a")).toBe("approved");
  });

  it("shows the saved answer when the session goes idle after the last decision of a followed stop", async () => {
    let decided!: () => void;
    const decisionDone = new Promise<void>((done) => (decided = done));
    const { widget, api } = sendingWidget();
    api.submitApprovalDecision = mock(async () => ({
      decision: "APPROVED" as const,
      decided_via: "USER",
      continuation: null,
    }));
    let reads = 0;
    // The read after the stop sees another turn until the decision, then an
    // idle session: the resume ran and saved its answer.
    api.waitForSessionIdle = mock(async () => {
      reads += 1;
      if (reads === 2) await decisionDone;
      return idle();
    });
    api.getChatSession = mock(async (): Promise<ChatSessionDetail> => ({
      messages: [
        { message_id: 1, message_type: "user", latest_child_message: 2 },
        { message_id: 2, message_type: "assistant", parent_message: 1 },
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
    }));

    const sending = widget["sendMessage"]();
    await waitUntil(() => reads === 2);
    await widget["decideApproval"](request("a"), "approve_once");
    decided();
    await sending;

    expect(api.getChatSession).toHaveBeenCalledTimes(1);
    expect(widget["messages"].map((m) => [m.id, m.content])).toEqual([
      [1, "send it"],
      [2, "Sent."],
    ]);
    expect(status(widget, "a")).toBe("approved");
  });

  it("shows the saved outcome and reads the status when the request no longer waits", async () => {
    const { widget, api } = waitingWidget();
    api.submitApprovalDecision = mock(async () => "closed" as const);
    api.getChatSession = mock(async (): Promise<ChatSessionDetail> => ({
      messages: [
        { message_id: 6, message_type: "user", latest_child_message: 7 },
        { message_id: 7, message_type: "assistant", parent_message: 6 },
      ],
      packets: [
        [
          { obj: request("a") },
          { obj: request("b") },
          {
            obj: {
              type: "tool_approval_resolved",
              approval_id: "a",
              outcome: "rejected",
            },
          },
          { obj: { type: "stop", stop_reason: "awaiting_approval" } },
        ],
      ],
    }));

    await widget["decideApproval"](request("a"), "approve_once");
    expect(status(widget, "a")).toBe("closed");
    await waitUntil(
      () => widget["messages"][0]?.approvals?.[0]?.outcome !== null
    );

    await waitUntil(() => !widget["isStreaming"]);
    expect(api.waitForSessionIdle).toHaveBeenCalledTimes(1);
    expect(api.resumeStream).not.toHaveBeenCalled();
    expect(status(widget, "a")).toBe("rejected");
    expect(widget["localApprovals"].has("a")).toBe(false);
    expect(widget["pendingApproval"]?.request.approval_id).toBe("b");
  });

  /** A send whose stream shows request a, then stops for decisions. */
  function sendingWidget(beforeStop: () => Promise<void> = async () => {}) {
    const { widget, api } = waitingWidget();
    widget["messages"] = [];
    widget["chatSessionId"] = undefined;
    widget["inputValue"] = "send it";
    api.createChatSession = mock(async () => "session");
    api.streamMessage = mock(async function* (): AsyncGenerator<Packet> {
      yield { obj: { user_message_id: 1, reserved_assistant_message_id: 2 } };
      yield { obj: request("a") };
      await beforeStop();
      yield { obj: { type: "stop", stop_reason: "awaiting_approval" } };
    });
    return { widget, api };
  }

  it("takes a new chat's baseline from its read before the send", async () => {
    const { widget, api } = sendingWidget();
    const calls: string[] = [];
    api.createChatSession = mock(async () => {
      calls.push("create");
      return "session";
    });
    api.waitForSessionIdle = mock(async () => {
      calls.push("status");
      return idle({ approvals_version: "v0" });
    });

    await widget["sendMessage"]();

    expect(calls).toEqual(["create", "status", "status"]);
    expect(widget["approvalsVersion"]).toBe("v0");
    expect(api.getChatSession).not.toHaveBeenCalled();
  });

  it("reads the status once at a stop for decisions, and follows only a new stream of the response", async () => {
    const { widget, api } = sendingWidget();
    const attachables: ((stream: ChatStream) => boolean)[] = [];
    api.waitForSessionIdle = mock(
      async (
        _session: string,
        _signal: AbortSignal,
        _onUnconfirmed: () => void,
        attachable: (stream: ChatStream) => boolean = () => false
      ) => {
        attachables.push(attachable);
        return idle();
      }
    );

    await widget["sendMessage"]();

    expect(widget["isStreaming"]).toBe(false);
    expect(widget["pendingApproval"]?.request.approval_id).toBe("a");
    // The new chat's baseline read, then the read after the stop.
    expect(attachables).toHaveLength(2);
    const attachable = attachables[1] ?? (() => true);
    expect(attachable(chatStream(2, [2]))).toBe(false);
    expect(attachable(chatStream(9, [8]))).toBe(false);
    expect(attachable(chatStream(9, [2]))).toBe(true);
    expect(api.resumeStream).not.toHaveBeenCalled();
    expect(api.getChatSession).not.toHaveBeenCalled();
  });

  it.each([null, 2])(
    "follows the resume stream after a stop for decisions when the decision named %s",
    async (named) => {
      let release!: () => void;
      const released = new Promise<void>((done) => (release = done));
      const { widget, api } = sendingWidget(() => released);
      // The decision found the live response: it names no continuation, or
      // the stream the widget reads.
      api.submitApprovalDecision = mock(async () => ({
        decision: "APPROVED" as const,
        decided_via: "USER",
        continuation: named === null ? null : chatStream(named, [2]),
      }));
      let reads = 0;
      // The run parks after the decision and resumes in stream 9.
      api.waitForSessionIdle = mock(
        async (
          _session: string,
          _signal: AbortSignal,
          _onUnconfirmed: () => void,
          attachable: (stream: ChatStream) => boolean = () => false
        ) => {
          reads += 1;
          if (reads !== 2) return idle();
          const resumed = chatStream(9, [2]);
          return attachable(resumed) ? runs(resumed) : idle();
        }
      );
      api.resumeStream = mock(async function* (): AsyncGenerator<
        Packet | StreamCursor
      > {
        yield { stream_id: 9, next_cursor: 0, replay_complete: false };
        yield { obj: { user_message_id: 1, reserved_assistant_message_id: 2 } };
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
      });

      const sending = widget["sendMessage"]();
      await waitUntil(() => widget["pendingApproval"] !== null);
      await widget["decideApproval"](request("a"), "approve_once");
      expect(api.resumeStream).not.toHaveBeenCalled();
      release();
      await sending;

      expect(api.resumeStream).toHaveBeenCalledTimes(1);
      expect(api.resumeStream).toHaveBeenCalledWith(
        "session",
        expect.anything(),
        { streamId: 9, cursor: 0 }
      );
      expect(widget["messages"].map((m) => [m.id, m.content])).toEqual([
        [1, "send it"],
        [2, "Sent."],
      ]);
      expect(status(widget, "a")).toBe("approved");
    }
  );

  it("follows a continuation named while the stream that stops for decisions is still read", async () => {
    let release!: () => void;
    const released = new Promise<void>((done) => (release = done));
    const { widget, api } = sendingWidget(() => released);
    api.submitApprovalDecision = mock(async () => continuation(9));
    api.resumeStream = mock(async function* (): AsyncGenerator<
      Packet | StreamCursor
    > {
      yield { stream_id: 9, next_cursor: 0, replay_complete: false };
      yield { obj: { user_message_id: 1, reserved_assistant_message_id: 2 } };
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
    });

    const sending = widget["sendMessage"]();
    await waitUntil(() => widget["pendingApproval"] !== null);
    await widget["decideApproval"](request("a"), "approve_once");
    expect(api.resumeStream).not.toHaveBeenCalled();
    release();
    await sending;

    expect(api.resumeStream).toHaveBeenCalledWith(
      "session",
      expect.anything(),
      { streamId: 9, cursor: 0 }
    );
    expect(widget["messages"].map((m) => [m.id, m.content])).toEqual([
      [1, "send it"],
      [2, "Sent."],
    ]);
    expect(status(widget, "a")).toBe("approved");
  });

  it("records an approval of a tool disabled meanwhile as disabled", async () => {
    const { widget, api } = waitingWidget();
    api.submitApprovalDecision = mock(async () => ({
      decision: "REJECTED" as const,
      decided_via: "POLICY",
      continuation: null,
    }));
    await widget["decideApproval"](request("a"), "approve_once");
    expect(widget["localApprovals"].get("a")).toBe("disabled");
  });

  it("keeps the card actionable after a failed decision", async () => {
    const { widget, api } = waitingWidget();
    api.submitApprovalDecision = mock(async () => {
      throw new Error("offline");
    });
    await widget["decideApproval"](request("a"), "reject");
    expect(widget["localApprovals"].get("a")).toBe("failed");
    expect(widget["pendingApproval"]?.request.approval_id).toBe("a");
  });

  it("sends while a card waits, then keeps the draft and points at the card when the server refuses", async () => {
    const { widget, api } = waitingWidget();
    Object.defineProperty(widget, "isConnected", { value: true });
    Object.defineProperty(widget, "updateComplete", {
      value: Promise.resolve(true),
    });
    const pointed: string[] = [];
    widget["pointAtApproval"] = (id: string) => void pointed.push(id);
    api.streamMessage = mock(async function* () {
      throw new ApiError("waiting", 409, APPROVAL_PENDING_ERROR_CODE);
    });
    api.getChatSession = mock(async (): Promise<ChatSessionDetail> => ({
      messages: [
        { message_id: 6, message_type: "user", latest_child_message: 7 },
        { message_id: 7, message_type: "assistant", parent_message: 6 },
      ],
      packets: [
        [
          { obj: request("a") },
          { obj: request("b") },
          { obj: { type: "stop", stop_reason: "awaiting_approval" } },
        ],
      ],
    }));
    widget["inputValue"] = "blocked";

    await widget["sendMessage"]();

    expect(api.streamMessage).toHaveBeenCalledTimes(1);
    expect(widget["inputValue"]).toBe("blocked");
    expect(widget["error"]).toBe(
      "Approve or reject the pending tool calls first."
    );
    expect(api.getChatSession).toHaveBeenCalled();
    expect(pointed).toEqual(["a"]);
    expect(widget["messages"].map((message) => message.id)).toEqual([7]);
  });

  it("sends while only a subagent card waits", async () => {
    const { widget, api } = waitingWidget();
    widget["messages"] = [
      {
        ...streamingMessage([
          {
            request: { ...request("c"), agent_name: "Research" },
            outcome: null,
          },
        ]),
        isStreaming: false,
      },
    ];
    api.streamMessage = mock(async function* (): AsyncGenerator<Packet> {
      yield { obj: { user_message_id: 8, reserved_assistant_message_id: 9 } };
      yield { obj: { type: "message_start" } };
      yield { obj: { type: "message_delta", content: "Done" } };
      yield { obj: { type: "stop" } };
    });
    widget["inputValue"] = "next";

    expect(widget["pendingApproval"]).toBeNull();
    await widget["sendMessage"]();

    expect(api.streamMessage).toHaveBeenCalledTimes(1);
    expect(status(widget, "c")).toBe("pending");
  });

  it("replays the saved session when the approvals version changes, and not again while it stays", async () => {
    const { widget, api } = waitingWidget();
    widget["messages"] = [
      {
        ...streamingMessage([
          {
            request: { ...request("c"), agent_name: "Research" },
            outcome: null,
          },
        ]),
        isStreaming: false,
      },
    ];
    // The version of the load that showed the transcript.
    widget["approvalsVersion"] = "v0";
    let version = "v1";
    api.waitForSessionIdle = mock(async () =>
      idle({ approvals_version: version })
    );
    api.getChatSession = mock(async (): Promise<ChatSessionDetail> => ({
      approvals_version: version,
      messages: [
        { message_id: 6, message_type: "user", latest_child_message: 7 },
        { message_id: 7, message_type: "assistant", parent_message: 6 },
      ],
      packets: [
        [
          { obj: { ...request("c"), agent_name: "Research" } },
          {
            obj: {
              type: "tool_approval_resolved",
              approval_id: "c",
              outcome: version === "v1" ? "rejected" : "approved",
            },
          },
          { obj: { type: "stop" } },
        ],
      ],
    }));

    await widget["resumeStream"]("session", { streamId: null });
    expect(api.getChatSession).toHaveBeenCalledTimes(1);
    expect(status(widget, "c")).toBe("rejected");

    await widget["resumeStream"]("session", { streamId: null });
    expect(api.getChatSession).toHaveBeenCalledTimes(1);

    version = "v2";
    await widget["resumeStream"]("session", { streamId: null });
    expect(api.getChatSession).toHaveBeenCalledTimes(2);
    expect(status(widget, "c")).toBe("approved");
  });

  it("follows a continuation decided while the saved session loads", async () => {
    const { widget, api } = waitingWidget();
    api.submitApprovalDecision = mock(async () => continuation(9));
    const resumedStreams: (number | null)[] = [];
    api.resumeStream = mock(async function* (
      _session: string,
      _signal: AbortSignal,
      from?: { streamId: number; cursor: number } | null
    ): AsyncGenerator<Packet | StreamCursor, ResumeEnd> {
      resumedStreams.push(from?.streamId ?? null);
      return "noBuffer";
    });
    let loaded: () => void = () => {};
    const loading = new Promise<void>((resolve) => {
      loaded = resolve;
    });
    const getChatSession = mock(async (): Promise<ChatSessionDetail> => {
      await loading;
      // The snapshot from before the decision
      return {
        messages: [
          { message_id: 6, message_type: "user", latest_child_message: 7 },
          { message_id: 7, message_type: "assistant", parent_message: 6 },
        ],
        packets: [[{ obj: request("a") }, { obj: request("b") }]],
      };
    });
    api.getChatSession = getChatSession;

    const resumed = widget["resumeStream"]("session", { streamId: null });
    await waitUntil(() => getChatSession.mock.calls.length > 0);
    await widget["decideApproval"](request("a"), "approve_once");
    loaded();
    await resumed;

    expect(resumedStreams).toContain(9);
  });

  it("reads the status again after an agent decision made while the saved session loads", async () => {
    const { widget, api } = waitingWidget();
    const agentEntry = { request: { ...request("c"), agent_name: "Research" } };
    widget["messages"] = [
      {
        ...streamingMessage([{ ...agentEntry, outcome: null }]),
        isStreaming: false,
      },
    ];
    widget["approvalsVersion"] = "v0";
    // The decision moves the version from v1 to v2.
    let version = "v1";
    api.waitForSessionIdle = mock(async () =>
      idle({ approvals_version: version })
    );
    api.submitApprovalDecision = mock(async () => {
      version = "v2";
      return {
        decision: "APPROVED" as const,
        decided_via: "USER",
        continuation: null,
      };
    });
    let loaded: () => void = () => {};
    const loading = new Promise<void>((resolve) => {
      loaded = resolve;
    });
    let loads = 0;
    api.getChatSession = mock(async (): Promise<ChatSessionDetail> => {
      loads += 1;
      if (loads === 1) await loading;
      return {
        approvals_version: loads === 1 ? "v1" : "v2",
        messages: [
          { message_id: 6, message_type: "user", latest_child_message: 7 },
          { message_id: 7, message_type: "assistant", parent_message: 6 },
        ],
        packets: [
          [
            { obj: { ...request("c"), agent_name: "Research" } },
            ...(loads === 1
              ? []
              : [{ obj: { ...request("d"), agent_name: "Research" } }]),
            { obj: { type: "stop" } },
          ],
        ],
      };
    });

    const resumed = widget["resumeStream"]("session", { streamId: null });
    await waitUntil(() => loads === 1);
    await widget["decideApproval"](agentEntry.request, "approve_once");
    loaded();
    await resumed;

    expect(api.getChatSession).toHaveBeenCalledTimes(2);
    expect(status(widget, "d")).toBe("pending");
  });

  it("follows the root turn that a finished agent's unread result starts", async () => {
    const { widget, api } = waitingWidget();
    widget["messages"] = [{ ...streamingMessage([]), isStreaming: false }];
    // The agent finished; its unread result starts the root's turn later.
    const statuses = [
      idle({ has_startable_input: true }),
      runs(chatStream(12, [9])),
      idle(),
    ];
    api.waitForSessionIdle = mock(async () => statuses.shift() ?? idle());
    api.resumeStream = mock(async function* (): AsyncGenerator<
      Packet | StreamCursor
    > {
      yield { stream_id: 12, next_cursor: 0, replay_complete: false };
      yield {
        obj: { user_message_id: null, reserved_assistant_message_id: 9 },
      };
      yield { obj: { type: "message_start" } };
      yield { obj: { type: "message_delta", content: "Agent done." } };
      yield { obj: { type: "stop" } };
    });

    await widget["resumeStream"]("session", null);

    expect(api.resumeStream).toHaveBeenCalledTimes(1);
    expect(widget["messages"].at(-1)).toMatchObject({
      id: 9,
      content: "Agent done.",
    });
  });

  it("loads a root answer that started and finished between two status reads", async () => {
    const { widget, api } = waitingWidget();
    widget["messages"] = [
      { id: 6, role: "user", content: "Research it", timestamp: 0 },
      { ...streamingMessage([]), isStreaming: false },
    ];
    // The agent's result started answer 9, which finished before this read.
    api.waitForSessionIdle = mock(async () => idle({ latest_response_id: 9 }));
    api.getChatSession = mock(async (): Promise<ChatSessionDetail> => ({
      messages: [
        { message_id: 6, message_type: "user", latest_child_message: 7 },
        {
          message_id: 7,
          message_type: "assistant",
          parent_message: 6,
          latest_child_message: 8,
        },
        {
          message_id: 8,
          message_type: "agent_results",
          parent_message: 7,
          latest_child_message: 9,
        },
        { message_id: 9, message_type: "assistant", parent_message: 8 },
      ],
      packets: [
        [{ obj: { type: "stop" } }],
        [
          { obj: { type: "message_start" } },
          { obj: { type: "message_delta", content: "Agent done." } },
          { obj: { type: "stop" } },
        ],
      ],
    }));

    await widget["resumeStream"]("session", null);

    expect(api.getChatSession).toHaveBeenCalledTimes(1);
    expect(widget["messages"].at(-1)).toMatchObject({
      id: 9,
      content: "Agent done.",
    });
  });

  it("checks the status after a stop even when the transport fails before its end", async () => {
    const { widget, api } = waitingWidget();
    widget["messages"] = [{ ...streamingMessage([]), isStreaming: false }];
    api.resumeStream = mock(async function* (): AsyncGenerator<
      Packet | StreamCursor,
      ResumeEnd
    > {
      yield { stream_id: 5, next_cursor: 0, replay_complete: false };
      yield { obj: { user_message_id: 6, reserved_assistant_message_id: 7 } };
      yield { obj: { type: "message_start" } };
      yield { obj: { type: "message_delta", content: "Done." } };
      yield { obj: { type: "stop" } };
      throw new TypeError("network connection lost");
    });
    // The stopped turn started a background agent.
    const statuses = [idle({ has_active_subagents: true }), idle()];
    const waitForSessionIdle = mock(async () => statuses.shift() ?? idle());
    api.waitForSessionIdle = waitForSessionIdle;

    await widget["resumeStream"]("session", { streamId: 5 });

    expect(widget["error"]).toBeUndefined();
    expect(waitForSessionIdle).toHaveBeenCalledTimes(2);
  });

  it("shows an error packet of a resumed stream as an error", async () => {
    const { widget, api } = waitingWidget();
    widget["messages"] = [{ ...streamingMessage([]), isStreaming: false }];
    api.resumeStream = mock(async function* (): AsyncGenerator<
      Packet | StreamCursor,
      ResumeEnd
    > {
      yield { stream_id: 5, next_cursor: 0, replay_complete: false };
      yield { obj: { user_message_id: 6, reserved_assistant_message_id: 7 } };
      yield { obj: { type: "error", exception: "boom" } };
      return "ended";
    });

    await widget["resumeStream"]("session", { streamId: 5 });

    expect(widget["error"]).toBe("Stream error: boom");
  });

  it("refreshes the saved session after approving for the chat with no continuation", async () => {
    const { widget, api } = waitingWidget();
    api.submitApprovalDecision = mock(async () => ({
      decision: "APPROVED" as const,
      decided_via: "USER",
      continuation: null,
    }));
    const resolved = (id: string): Packet => ({
      obj: {
        type: "tool_approval_resolved",
        approval_id: id,
        outcome: "approved_for_chat",
      },
    });
    api.getChatSession = mock(async (): Promise<ChatSessionDetail> => ({
      messages: [
        { message_id: 6, message_type: "user", latest_child_message: 7 },
        { message_id: 7, message_type: "assistant", parent_message: 6 },
      ],
      packets: [
        [
          { obj: request("a") },
          { obj: request("b") },
          resolved("a"),
          resolved("b"),
          { obj: { type: "stop" } },
        ],
      ],
    }));

    await widget["decideApproval"](request("a"), "approve_session");
    await waitUntil(() => widget["abortController"] === undefined);

    expect(api.getChatSession).toHaveBeenCalledTimes(1);
    expect(status(widget, "b")).not.toBe("pending");
    expect(widget["pendingApproval"]).toBeNull();
  });

  it("recovers only the turns of the selected branch", async () => {
    const { stored, saved, restore } = fakeSessionStorage();
    const initial = JSON.stringify({
      sessionId: "session",
      messages: [
        { id: 1, role: "user", content: "first", timestamp: 0 },
        { id: 2, role: "assistant", content: "first answer", timestamp: 0 },
        { id: 5, role: "user", content: "resent", timestamp: 0 },
        { id: 6, role: "assistant", content: "resent answer", timestamp: 0 },
      ],
      timestamp: Date.now(),
      identity: "shared",
    });
    stored.set("onyx-widget-session", initial);
    mockFetch(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/status"))
        return Response.json({ is_processing: false });
      if (url.includes("/get-chat-session/"))
        // Answer 2 has the abandoned question 3 and the selected question 5.
        return Response.json({
          messages: [
            { message_id: 1, message_type: "user", latest_child_message: 2 },
            {
              message_id: 2,
              message_type: "assistant",
              parent_message: 1,
              latest_child_message: 5,
            },
            {
              message_id: 3,
              message_type: "user",
              parent_message: 2,
              latest_child_message: 4,
            },
            { message_id: 4, message_type: "assistant", parent_message: 3 },
            {
              message_id: 5,
              message_type: "user",
              parent_message: 2,
              latest_child_message: 6,
            },
            { message_id: 6, message_type: "assistant", parent_message: 5 },
          ],
          packets: [
            [{ obj: { type: "stop" } }],
            [
              { obj: { type: "user_message", id: "sdk-3", message: "lost" } },
              { obj: { type: "message_start" } },
              { obj: { type: "message_delta", content: "lost answer" } },
              { obj: { type: "stop" } },
            ],
            [{ obj: { type: "stop" } }],
          ],
        });
      return new Response("none", { status: 404 });
    });
    skipPollPauses();
    const widget = new OnyxChatWidget();
    widget["config"] = { backendUrl: "https://onyx.test/api", apiKey: "key" };
    widget["apiService"] = new ApiService(
      "https://onyx.test/api",
      async () => "key"
    );
    widget["currentIdentity"] = async () => "shared";
    try {
      widget["restoreSession"]();
      await waitUntil(() => stored.get("onyx-widget-session") !== initial);
      await waitUntil(() => widget["abortController"] === undefined);
    } finally {
      restore();
    }

    expect(widget["messages"].map((m) => m.id)).toEqual([1, 2, 5, 6]);
    expect(saved()?.map((m) => m.id)).toEqual([1, 2, 5, 6]);
  });

  it("replays an earlier answer whose agent asks after a later question", async () => {
    const { widget, api } = waitingWidget();
    widget["messages"] = [
      { id: 6, role: "user", content: "Research it", timestamp: 0 },
      { ...streamingMessage([]), isStreaming: false },
      { id: 8, role: "user", content: "Another question", timestamp: 0 },
      { ...streamingMessage([]), id: 9, isStreaming: false },
    ];
    widget["approvalsVersion"] = "v0";
    api.waitForSessionIdle = mock(async () =>
      idle({ approvals_version: "v1" })
    );
    api.getChatSession = mock(async (): Promise<ChatSessionDetail> => ({
      approvals_version: "v1",
      messages: [
        { message_id: 6, message_type: "user", latest_child_message: 7 },
        {
          message_id: 7,
          message_type: "assistant",
          parent_message: 6,
          latest_child_message: 8,
        },
        {
          message_id: 8,
          message_type: "user",
          parent_message: 7,
          latest_child_message: 9,
        },
        { message_id: 9, message_type: "assistant", parent_message: 8 },
      ],
      packets: [
        [
          { obj: { ...request("c"), agent_name: "Research" } },
          { obj: { type: "stop" } },
        ],
        [{ obj: { type: "stop" } }],
      ],
    }));

    await widget["resumeStream"]("session", { streamId: null });

    expect(status(widget, "c")).toBe("pending");
    expect(widget["messages"][1]?.approvals).toMatchObject([
      { request: { approval_id: "c" } },
    ]);
  });

  it("keeps a version change pending until a session load succeeds", async () => {
    const { widget, api } = waitingWidget();
    widget["messages"] = [{ ...streamingMessage([]), isStreaming: false }];
    widget["approvalsVersion"] = "v0";
    api.waitForSessionIdle = mock(async () =>
      idle({ approvals_version: "v1" })
    );
    let fails = true;
    api.getChatSession = mock(async (): Promise<ChatSessionDetail> => {
      if (fails) throw new Error("unavailable");
      return {
        approvals_version: "v1",
        messages: [
          { message_id: 6, message_type: "user", latest_child_message: 7 },
          { message_id: 7, message_type: "assistant", parent_message: 6 },
        ],
        packets: [
          [
            { obj: { ...request("c"), agent_name: "Research" } },
            { obj: { type: "stop" } },
          ],
        ],
      };
    });

    await widget["resumeStream"]("session", { streamId: null }).catch(() => {});
    expect(api.getChatSession).toHaveBeenCalledTimes(1);

    fails = false;
    await widget["resumeStream"]("session", { streamId: null });
    expect(api.getChatSession).toHaveBeenCalledTimes(2);
    expect(status(widget, "c")).toBe("pending");
  });

  /**
   * A widget whose answer 7 holds agent request c, shown by the load of
   * version v0. Each status read takes the next of `statuses`, then reports
   * agents as `agentsRun` says; each session load replays c resolved, plus d
   * once the version is v2.
   */
  function agentWidget(
    statuses: { has_active_subagents: boolean; approvals_version: string }[],
    agentsRun: () => boolean = () => false
  ) {
    skipPollPauses();
    const widget = new OnyxChatWidget();
    widget["config"] = { backendUrl: "https://onyx.test/api", apiKey: "key" };
    widget["currentIdentity"] = async () => "user";
    const api = new ApiService("https://onyx.test/api", async () => "key");
    widget["apiService"] = api;
    widget["chatSessionId"] = "session";
    widget["messages"] = [
      { id: 6, role: "user", content: "Research it", timestamp: 0 },
      {
        ...streamingMessage([{ request: agentRequest("c"), outcome: null }]),
        isStreaming: false,
      },
    ];
    widget["approvalsVersion"] = "v0";
    api.submitApprovalDecision = mock(async () => ({
      decision: "APPROVED" as const,
      decided_via: "USER",
      continuation: null,
    }));
    const urls: string[] = [];
    let version = "v0";
    mockFetch(async (input: RequestInfo | URL) => {
      const url = String(input);
      urls.push(url);
      if (url.endsWith("/status")) {
        const status = statuses.shift() ?? {
          has_active_subagents: agentsRun(),
          approvals_version: version,
        };
        version = status.approvals_version;
        return Response.json({ is_processing: false, ...status });
      }
      const resolved = {
        obj: {
          type: "tool_approval_resolved",
          approval_id: "c",
          outcome: "approved",
        },
      };
      return Response.json({
        messages: [
          { message_id: 6, message_type: "user", latest_child_message: 7 },
          { message_id: 7, message_type: "assistant", parent_message: 6 },
        ],
        packets: [
          [
            { obj: agentRequest("c") },
            resolved,
            ...(version === "v2" ? [{ obj: agentRequest("d") }] : []),
            { obj: { type: "stop" } },
          ],
        ],
        approvals_version: version,
      });
    });
    const count = (part: string) =>
      urls.filter((url) => url.includes(part)).length;
    return { widget, count };
  }

  const agentRequest = (id: string) => ({
    ...request(id),
    agent_name: "Research",
  });
  const agentStatus = (running: boolean, version: string) => ({
    has_active_subagents: running,
    approvals_version: version,
  });

  it("polls the status after an agent decision while agents run, reloading on each version", async () => {
    const { restore } = fakeSessionStorage();
    // The decided agent counts as active at once; it then opens d and parks.
    const { widget, count } = agentWidget([
      agentStatus(true, "v1"),
      agentStatus(true, "v1"),
      agentStatus(false, "v2"),
    ]);

    try {
      await widget["decideApproval"](agentRequest("c"), "approve_once");
      await waitUntil(() => widget["abortController"] === undefined);
    } finally {
      restore();
    }

    expect(count("/status")).toBe(3);
    expect(count("/get-chat-session/")).toBe(2);
    expect(count("/resume-stream")).toBe(0);
    expect(widget["messages"][1]?.approvals).toMatchObject([
      { request: { approval_id: "c" }, outcome: "approved" },
      { request: { approval_id: "d" }, outcome: null },
    ]);
    expect(widget["approvalsVersion"]).toBe("v2");
  });

  it("polls for running agents without changing the streaming state on each read", async () => {
    const { restore } = fakeSessionStorage();
    const { widget, count } = agentWidget([
      agentStatus(true, "v1"),
      agentStatus(true, "v1"),
      agentStatus(true, "v1"),
      agentStatus(false, "v1"),
    ]);
    const changes: boolean[] = [];
    let streaming = false;
    Object.defineProperty(widget, "isStreaming", {
      configurable: true,
      get: () => streaming,
      set: (value: boolean) => {
        if (value !== streaming) changes.push(value);
        streaming = value;
      },
    });

    try {
      await widget["decideApproval"](agentRequest("c"), "approve_once");
      await waitUntil(() => widget["abortController"] === undefined);
    } finally {
      restore();
    }

    expect(count("/status")).toBe(4);
    expect(changes).toEqual([true, false]);
  });

  it("sends while it polls for running agents, and the send's follow polls on", async () => {
    const { restore } = fakeSessionStorage();
    // The agents run until the sent answer is done.
    let answered = false;
    const { widget, count } = agentWidget([], () => !answered);
    const streamMessage = mock(async function* (): AsyncGenerator<Packet> {
      yield { obj: { user_message_id: 8, reserved_assistant_message_id: 9 } };
      yield { obj: { type: "message_start" } };
      yield { obj: { type: "message_delta", content: "Done" } };
      yield { obj: { type: "stop" } };
      answered = true;
    });
    widget["apiService"].streamMessage = streamMessage;

    try {
      await widget["decideApproval"](agentRequest("c"), "approve_once");
      await waitUntil(() => count("/status") >= 2);
      widget["inputValue"] = "next";
      await widget["sendMessage"]();
      await waitUntil(() => widget["abortController"] === undefined);
    } finally {
      restore();
    }

    expect(streamMessage).toHaveBeenCalledTimes(1);
    expect(widget["messages"].at(-1)).toMatchObject({ id: 9, content: "Done" });
    expect(widget["inputValue"]).toBe("");
  });

  it("reads the status once after an agent decision when no agent runs", async () => {
    const { restore } = fakeSessionStorage();
    const { widget, count } = agentWidget([]);

    try {
      await widget["decideApproval"](agentRequest("c"), "approve_once");
      await waitUntil(() => widget["abortController"] === undefined);
    } finally {
      restore();
    }

    expect(count("/status")).toBe(1);
    expect(count("/get-chat-session/")).toBe(0);
  });

  it("shows a waiting request that the restored snapshot lacks from the saved session", async () => {
    const { widget, api } = waitingWidget();
    api.getChatSession = mock(async (): Promise<ChatSessionDetail> => ({
      messages: [
        { message_id: 6, message_type: "user", latest_child_message: 7 },
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
    // Saved before the request was; a restore replays the latest answer.
    widget["messages"] = [];
    widget["approvalsChanged"] = true;

    await widget["resumeStream"]("session", { streamId: null });

    expect(widget["pendingApproval"]?.request.approval_id).toBe("a");
    expect(widget["messages"].map((m) => [m.id, m.role])).toEqual([
      [6, "user"],
      [7, "assistant"],
    ]);
  });

  function restoredWidget() {
    skipPollPauses();
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
    mockFetch(async (input: RequestInfo | URL) => {
      const url = String(input);
      urls.push(url);
      if (url.endsWith("/status"))
        return Response.json({ is_processing: false });
      if (url.includes("/get-chat-session/")) {
        return Response.json({
          messages: [
            { message_id: 6, message_type: "user", latest_child_message: 7 },
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
    });
    const widget = restoredWidget();

    try {
      await widget["resumeStream"]("session", { streamId: null });
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
    mockFetch(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/status"))
        return Response.json({ is_processing: false });
      if (url.includes("/get-chat-session/")) {
        return Response.json({
          messages: [
            { message_id: 6, message_type: "user", latest_child_message: 7 },
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
    });
    const widget = restoredWidget();

    try {
      await widget["resumeStream"]("session", { streamId: null });
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
    const { stored, saved, restore } = fakeSessionStorage();
    const messages: ChatMessage[] = [
      { id: 1, role: "user", content: "first", timestamp: 0 },
      { id: 2, role: "assistant", content: "first answer", timestamp: 0 },
      { id: 3, role: "user", content: "second", timestamp: 0 },
    ];
    const initial = JSON.stringify({
      sessionId: "session",
      messages,
      timestamp: Date.now(),
      identity: "shared",
    });
    stored.set("onyx-widget-session", initial);
    mockFetch(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/status"))
        return Response.json({ is_processing: false });
      if (url.includes("/get-chat-session/")) return Response.json(session);
      return new Response("none", { status: 404 });
    });
    const widget = restoredWidget();
    widget["messages"] = [];
    widget["currentIdentity"] = async () => "shared";
    try {
      widget["restoreSession"]();
      // The saved session replaces the stored transcript.
      await waitUntil(() => stored.get("onyx-widget-session") !== initial);
    } finally {
      restore();
    }
    return {
      shown: widget["messages"].map((m) => [m.id, m.content]),
      saved: saved()?.map((m) => [m.id, m.content]),
    };
  }

  it("restores a turn accepted after the transcript was saved when its replay is gone", async () => {
    const { shown, saved } = await restoreUnanswered({
      messages: [
        { message_id: 1, message_type: "user", latest_child_message: 2 },
        {
          message_id: 2,
          message_type: "assistant",
          parent_message: 1,
          latest_child_message: 3,
        },
        {
          message_id: 3,
          message_type: "user",
          parent_message: 2,
          latest_child_message: 4,
        },
        {
          message_id: 4,
          message_type: "assistant",
          parent_message: 3,
          latest_child_message: 5,
        },
        {
          message_id: 5,
          message_type: "user",
          parent_message: 4,
          latest_child_message: 6,
        },
        { message_id: 6, message_type: "assistant", parent_message: 5 },
      ],
      packets: [
        [{ obj: { type: "stop" } }],
        [
          { obj: { type: "message_start" } },
          { obj: { type: "message_delta", content: "second answer" } },
          { obj: { type: "stop" } },
        ],
        [
          { obj: { type: "user_message", id: "sdk-5", message: "third" } },
          { obj: { type: "message_start" } },
          { obj: { type: "message_delta", content: "third answer" } },
          { obj: { type: "stop" } },
        ],
      ],
    });

    const expected = [
      [1, "first"],
      [2, "first answer"],
      [3, "second"],
      [4, "second answer"],
      [5, "third"],
      [6, "third answer"],
    ];
    expect(shown).toEqual(expected);
    expect(saved).toEqual(expected);
  });

  it("places a recovered turn before a newer turn in the saved order", async () => {
    const { stored, saved, restore } = fakeSessionStorage();
    const initial = JSON.stringify({
      sessionId: "session",
      messages: [
        { id: 1, role: "user", content: "first", timestamp: 0 },
        { id: 2, role: "assistant", content: "first answer", timestamp: 0 },
        { id: 5, role: "user", content: "third", timestamp: 0 },
        {
          id: 6,
          role: "assistant",
          content: "",
          timestamp: 0,
          isStreaming: true,
        },
      ],
      timestamp: Date.now(),
      identity: "shared",
    });
    stored.set("onyx-widget-session", initial);
    mockFetch(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/status"))
        return Response.json({ is_processing: false });
      if (url.includes("/get-chat-session/"))
        return Response.json({
          messages: [
            { message_id: 1, message_type: "user", latest_child_message: 2 },
            {
              message_id: 2,
              message_type: "assistant",
              parent_message: 1,
              latest_child_message: 3,
            },
            {
              message_id: 3,
              message_type: "user",
              parent_message: 2,
              latest_child_message: 4,
            },
            {
              message_id: 4,
              message_type: "assistant",
              parent_message: 3,
              latest_child_message: 5,
            },
            {
              message_id: 5,
              message_type: "user",
              parent_message: 4,
              latest_child_message: 6,
            },
            { message_id: 6, message_type: "assistant", parent_message: 5 },
          ],
          packets: [
            [{ obj: { type: "stop" } }],
            [
              { obj: { type: "user_message", id: "sdk-3", message: "second" } },
              { obj: { type: "message_start" } },
              { obj: { type: "message_delta", content: "second answer" } },
              { obj: { type: "stop" } },
            ],
            [
              { obj: { type: "message_start" } },
              { obj: { type: "message_delta", content: "third answer" } },
              { obj: { type: "stop" } },
            ],
          ],
        });
      return new Response("none", { status: 404 });
    });
    const widget = restoredWidget();
    widget["messages"] = [];
    widget["currentIdentity"] = async () => "shared";
    try {
      widget["restoreSession"]();
      await waitUntil(() => stored.get("onyx-widget-session") !== initial);
      await waitUntil(() => widget["abortController"] === undefined);
    } finally {
      restore();
    }

    const expected = [
      [1, "first"],
      [2, "first answer"],
      [3, "second"],
      [4, "second answer"],
      [5, "third"],
      [6, "third answer"],
    ];
    expect(widget["messages"].map((m) => [m.id, m.content])).toEqual(expected);
    expect(saved()?.map((m) => [m.id, m.content])).toEqual(expected);
  });

  it("answers a stored question from the saved session when its replay is gone", async () => {
    const { shown, saved } = await restoreUnanswered({
      messages: [
        { message_id: 1, message_type: "user", latest_child_message: 2 },
        {
          message_id: 2,
          message_type: "assistant",
          parent_message: 1,
          latest_child_message: 3,
        },
        {
          message_id: 3,
          message_type: "user",
          parent_message: 2,
          latest_child_message: 4,
        },
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
        { message_id: 1, message_type: "user", latest_child_message: 2 },
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
    api.waitForSessionIdle = mock(async () => idle());
    api.getChatSession = mock(
      async (): Promise<ChatSessionDetail> => ({ messages: [], packets: [] })
    );
    api.streamMessage = mock(async function* (): AsyncGenerator<Packet> {
      yield { obj: { type: "stop" } };
    });

    await widget["sendMessage"]();

    expect(api.streamMessage).toHaveBeenCalledWith(
      expect.objectContaining({ parentMessageId: 2 })
    );
  });

  it("sends under an agent's answer that finished after the last read, and shows it", async () => {
    const { restore } = fakeSessionStorage();
    const widget = restoredWidget();
    widget["chatSessionId"] = "session";
    widget["messages"] = [
      { id: 6, role: "user", content: "Research it", timestamp: 0 },
      { id: 7, role: "assistant", content: "Started.", timestamp: 0 },
    ];
    widget["inputValue"] = "Next";
    const api = widget["apiService"];
    // The agent's result started answer 9, which finished before the send.
    let sent = false;
    api.waitForSessionIdle = mock(async () =>
      idle({ latest_response_id: sent ? 11 : 9 })
    );
    api.streamMessage = mock(async function* (): AsyncGenerator<Packet> {
      sent = true;
      yield { obj: { user_message_id: 10, reserved_assistant_message_id: 11 } };
      yield { obj: { type: "message_start" } };
      yield { obj: { type: "message_delta", content: "Next answer." } };
      yield { obj: { type: "stop" } };
    });
    api.getChatSession = mock(async (): Promise<ChatSessionDetail> => ({
      messages: [
        { message_id: 6, message_type: "user", latest_child_message: 7 },
        {
          message_id: 7,
          message_type: "assistant",
          parent_message: 6,
          latest_child_message: 8,
        },
        {
          message_id: 8,
          message_type: "agent_results",
          parent_message: 7,
          latest_child_message: 9,
        },
        {
          message_id: 9,
          message_type: "assistant",
          parent_message: 8,
          latest_child_message: 10,
        },
        {
          message_id: 10,
          message_type: "user",
          parent_message: 9,
          latest_child_message: 11,
        },
        { message_id: 11, message_type: "assistant", parent_message: 10 },
      ],
      packets: [
        [{ obj: { type: "stop" } }],
        [
          { obj: { type: "message_start" } },
          { obj: { type: "message_delta", content: "Agent done." } },
          { obj: { type: "stop" } },
        ],
        [
          { obj: { type: "message_start" } },
          { obj: { type: "message_delta", content: "Next answer." } },
          { obj: { type: "stop" } },
        ],
      ],
    }));

    try {
      await widget["sendMessage"]();
      await waitUntil(() => widget["abortController"] === undefined);
    } finally {
      restore();
    }

    expect(api.streamMessage).toHaveBeenCalledWith(
      expect.objectContaining({ parentMessageId: 9 })
    );
    expect(widget["messages"].map((m) => [m.id, m.content])).toEqual([
      [6, "Research it"],
      [7, "Started."],
      [9, "Agent done."],
      [10, "Next"],
      [11, "Next answer."],
    ]);
  });

  it("keeps a restored response unfinished when the saved session cannot load", async () => {
    const { stored, restore } = fakeSessionStorage();
    mockFetch(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/status"))
        return Response.json({ is_processing: false });
      return new Response("none", {
        status: url.includes("/get-chat-session/") ? 403 : 404,
      });
    });
    const widget = restoredWidget();

    try {
      await widget["resumeStream"]("session", { streamId: null });
    } finally {
      restore();
    }

    expect(widget["error"]).toBeDefined();
    expect(widget["messages"][0]!.isStreaming).toBe(true);
    expect(stored.has("onyx-widget-session")).toBe(false);
  });

  it("keeps a restored request pending when the resume fails, and follows the continuation after a decision", async () => {
    const widget = restoredWidget();
    const api = widget["apiService"];
    api.resumeStream = mock(async function* (): AsyncGenerator<Packet> {
      throw new TypeError("Failed to fetch");
    });
    api.waitForSessionIdle = mock(async () => {
      throw new Error("Cannot reach the server");
    });

    await widget["resumeStream"]("session", { streamId: null });

    expect(widget["error"]).toBe("Cannot reach the server");
    expect(widget["isStreaming"]).toBe(false);
    expect(widget["abortController"]).toBeUndefined();
    expect(widget["pendingApproval"]?.request.approval_id).toBe("a");

    widget["chatSessionId"] = "session";
    api.submitApprovalDecision = mock(async () => continuation(4));
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
    const waitForSessionIdle = mock(async () => idle());
    api.waitForSessionIdle = waitForSessionIdle;

    await widget["decideApproval"](request("a"), "approve_once");
    await waitUntil(() => waitForSessionIdle.mock.calls.length > 0);

    expect(api.resumeStream).toHaveBeenCalledTimes(1);
    expect(api.resumeStream).toHaveBeenCalledWith(
      "session",
      expect.anything(),
      { streamId: 4, cursor: 0 }
    );
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
    // Read while the stream waits, before the saved session loads
    const seen: { pending: ApprovalEntry | null } = { pending: null };
    api.resumeStream = mock(async function* (): AsyncGenerator<
      Packet | StreamCursor,
      ResumeEnd
    > {
      yield { obj: { user_message_id: 1, reserved_assistant_message_id: 7 } };
      yield { obj: request("a") };
      seen.pending = widget["pendingApproval"];
      return "ended";
    });
    api.waitForSessionIdle = mock(async () => idle());
    const getChatSession = mock(
      async (): Promise<ChatSessionDetail> => ({ messages: [], packets: [] })
    );
    api.getChatSession = getChatSession;

    try {
      widget["restoreSession"]();
      // The follow ends at the saved session.
      await waitUntil(() => getChatSession.mock.calls.length > 0);
    } finally {
      restore();
    }

    expect(api.resumeStream).toHaveBeenCalledWith(
      "session",
      expect.anything(),
      null
    );
    expect(seen.pending?.request.approval_id).toBe("a");
  });

  it("restores the question of a turn accepted before the reload saved it", async () => {
    const { stored, saved, restore } = fakeSessionStorage();
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
    api.waitForSessionIdle = mock(async () => idle());
    const getChatSession = mock(
      async (): Promise<ChatSessionDetail> => ({ messages: [], packets: [] })
    );
    api.getChatSession = getChatSession;

    try {
      widget["restoreSession"]();
      // The follow ends at the saved session, which finishes the answer.
      await waitUntil(() => getChatSession.mock.calls.length > 0);
      await waitUntil(() => saved()?.at(-1)?.isStreaming === false);
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
    expect(saved()?.map((m) => m.id)).toEqual([1, 2, 3, 4]);
  });

  it("follows the sent response again from its start when its stream ends before it does", async () => {
    const { restore } = fakeSessionStorage();
    skipPollPauses();
    const widget = new OnyxChatWidget();
    widget["config"] = { backendUrl: "https://onyx.test/api", apiKey: "key" };
    const api = new ApiService("https://onyx.test/api", async () => "key");
    api.createChatSession = mock(async () => "session");
    // The status reports the sent stream 2 while it runs.
    api.waitForSessionIdle = mock(
      async (
        _session: string,
        _signal: AbortSignal,
        _onUnconfirmed: () => void,
        attachable: (stream: ChatStream) => boolean = () => false
      ) => (offer(attachable, 2))
    );
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

    try {
      await widget["sendMessage"]();
    } finally {
      restore();
    }

    expect(api.resumeStream).toHaveBeenCalledTimes(1);
    expect(api.resumeStream).toHaveBeenCalledWith(
      "session",
      expect.anything(),
      { streamId: 2, cursor: 0 }
    );
    expect(widget["messages"].at(-1)).toMatchObject({
      id: 2,
      isStreaming: false,
      approvals: [{ outcome: "rejected" }],
    });
  });
});
