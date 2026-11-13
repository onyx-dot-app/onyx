import { afterEach, describe, expect, it, mock } from "bun:test";
import { ApiError, ApiService } from "../src/services/api-service";
import {
  APPROVAL_PENDING_ERROR_CODE,
  type ApprovalEntry,
  approvalDeadline,
  approvalRecord,
  approvalStatus,
  argumentRows,
  decidedStatus,
  findPendingApproval,
} from "../src/services/approvals";
import { processPacket } from "../src/services/stream-parser";
import type { Packet, ToolApprovalRequest } from "../src/types/api-types";
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
    expires_at: "2026-11-13T15:45:00Z",
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

  it("never closes a request by the device clock", () => {
    const expired = entry("a");
    expired.request.expires_at = "2000-01-01T00:00:00Z";
    expect(approvalStatus(expired, undefined, false)).toBe("pending");
  });

  it("finds the first request that still waits", () => {
    const messages = [
      { ...streamingMessage([entry("old")]), isStreaming: false },
      streamingMessage([entry("a"), entry("b")]),
    ];
    const local = new Map([["a", "approved" as const]]);
    expect(findPendingApproval(messages, true, local)?.request.approval_id).toBe(
      "b"
    );
    // A stopped widget stream closes what still waits.
    expect(findPendingApproval(messages, false, local)).toBeNull();
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

  it("writes one-line records and the deadline", () => {
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
    expect(approvalDeadline("2026-11-13T15:45:00Z", "en-US")).toMatch(
      /^Approve by \d{1,2}:\d{2}\s?[AP]M$/
    );
    expect(approvalDeadline("not a date")).toBeNull();
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

  it("replays a running response and skips its replay positions", async () => {
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
    const packets: Packet[] = [];
    for await (const packet of api.resumeStream(
      "s",
      new AbortController().signal
    )) {
      packets.push(packet);
    }
    expect(urls).toEqual([
      "https://onyx.test/api/chat/chat-session/s/resume-stream?cursor=0",
    ]);
    expect(packets.map((packet) => packet.obj)).toEqual([request("a")]);
  });

  it("ends a resume without packets when nothing runs", async () => {
    globalThis.fetch = mock(
      async () => new Response("none", { status: 404 })
    ) as typeof fetch;
    const api = new ApiService("https://onyx.test/api", async () => "key");
    const stream = api.resumeStream("s", new AbortController().signal);
    expect((await stream.next()).done).toBe(true);
  });

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

  it("keeps a decision through streamed packets until the server resolves it", async () => {
    const widget = new OnyxChatWidget();
    widget["config"] = { backendUrl: "https://onyx.test/api", apiKey: "key" };
    const api = new ApiService("https://onyx.test/api", async () => "key");
    api.createChatSession = mock(async () => "session");
    api.waitForSessionIdle = mock(async () => {});
    api.submitApprovalDecision = mock(async () => ({
      decision: "APPROVED" as const,
      decided_via: "SESSION_GRANT",
    }));
    let decide!: () => void;
    const decided = new Promise<void>((resolve) => (decide = resolve));
    let resolve!: () => void;
    const resolution = new Promise<void>((done) => (resolve = done));
    // Set once the widget has applied the packets streamed after the decision
    let streamedAfterDecision = false;
    api.streamMessage = mock(async function* (): AsyncGenerator<Packet> {
      yield {
        obj: { user_message_id: 1, reserved_assistant_message_id: 2 },
      };
      yield { obj: request("a") };
      await decided;
      yield { obj: { type: "heartbeat" } } as unknown as Packet;
      yield { obj: { type: "message_start" } };
      streamedAfterDecision = true;
      await resolution;
      yield {
        obj: {
          type: "tool_approval_resolved",
          approval_id: "a",
          outcome: "approved_for_chat",
        },
      };
      yield { obj: { type: "stop" } };
    });
    widget["apiService"] = api;
    widget["inputValue"] = "send it";

    const sending = widget["sendMessage"]();
    while (!widget["pendingApproval"]) await Bun.sleep(1);
    await widget["decideApproval"](request("a"), "approve_session");
    decide();
    while (!streamedAfterDecision) await Bun.sleep(1);
    const status = () =>
      approvalStatus(
        widget["messages"].at(-1)!.approvals![0]!,
        widget["localApprovalStatuses"].get("a"),
        false
      );
    expect(widget["pendingApproval"]).toBeNull();
    expect(status()).toBe("approvedForSession");

    resolve();
    await sending;
    expect(widget["localApprovalStatuses"].size).toBe(0);
    expect(status()).toBe("approvedForSession");
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
    let pending: ApprovalEntry | null = null;
    api.resumeStream = mock(async function* (): AsyncGenerator<Packet> {
      yield { obj: { user_message_id: 1, reserved_assistant_message_id: 2 } };
      yield { obj: request("a") };
      pending = widget["pendingApproval"];
    });
    widget["apiService"] = api;
    widget["inputValue"] = "blocked";
    await widget["sendMessage"]();
    expect(widget["inputValue"]).toBe("blocked");
    expect(widget["error"]).toContain("waits for your decision");
    // The waiting request shows again, so the user can decide it.
    expect(api.resumeStream).toHaveBeenCalledWith("session", expect.anything());
    expect(pending?.request.approval_id).toBe("a");
    expect(widget["messages"].map((message) => message.id)).toEqual([2]);
  });

  it("shows a restored waiting request again", async () => {
    const widget = new OnyxChatWidget();
    widget["config"] = { backendUrl: "https://onyx.test/api", apiKey: "key" };
    const api = new ApiService("https://onyx.test/api", async () => "key");
    let pending: ApprovalEntry | null = null;
    api.resumeStream = mock(async function* (): AsyncGenerator<Packet> {
      yield { obj: { user_message_id: 1, reserved_assistant_message_id: 7 } };
      yield { obj: request("a") };
      pending = widget["pendingApproval"];
    });
    widget["apiService"] = api;
    // Saved while the request waited
    widget["messages"] = [streamingMessage([entry("a")])];
    expect(widget["pendingApproval"]).toBeNull();

    await widget["resumeStream"]("session");

    expect(pending?.request.approval_id).toBe("a");
    expect(widget["messages"]).toHaveLength(1);
  });

  it("stops a restored response that finished while the page was closed", async () => {
    const stored = new Map<string, string>();
    globalThis.sessionStorage = {
      getItem: (key: string) => stored.get(key) ?? null,
      setItem: (key: string, value: string) => void stored.set(key, value),
      removeItem: (key: string) => void stored.delete(key),
    } as Storage;
    globalThis.fetch = mock(
      async () => new Response("none", { status: 404 })
    ) as typeof fetch;
    const widget = new OnyxChatWidget();
    widget["config"] = { backendUrl: "https://onyx.test/api", apiKey: "key" };
    widget["apiService"] = new ApiService(
      "https://onyx.test/api",
      async () => "key"
    );
    widget["messages"] = [streamingMessage([entry("a")])];

    try {
      await widget["resumeStream"]("session");
    } finally {
      Reflect.deleteProperty(globalThis, "sessionStorage");
    }

    expect(widget["isStreaming"]).toBe(false);
    expect(widget["messages"][0]!.isStreaming).toBe(false);
    const saved = JSON.parse(stored.get("onyx-widget-session") ?? "null");
    expect(saved.messages[0].isStreaming).toBe(false);
  });
});
