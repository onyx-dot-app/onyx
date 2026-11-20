import { describe, expect, it } from "@jest/globals";
import { readChatHistory, readChatNotification } from "@onyx-ai/shared/acp";

const placement = { turn_index: 0 };
const packet = { type: "section_end" };
const failure = {
  jsonrpc: "2.0",
  method: "session/update",
  params: {
    sessionId: "session",
    update: {
      sessionUpdate: "tool_call_update",
      toolCallId: "run/tool/id",
      status: "failed",
      _meta: { onyx: { placement, packet } },
    },
  },
};

describe("chat ACP notifications", () => {
  it("preserves the same amended tool outcome live and on reload", () => {
    const expected = {
      placement,
      obj: packet,
      acpTool: { toolCallId: "run/tool/id", status: "failed" },
    };
    expect(readChatNotification(failure, "session")).toEqual(expected);
    expect(
      readChatHistory("session", { packets: [[failure], []] }).packets,
    ).toEqual([[expected], []]);
  });

  it("loads history and stream controls from a server that returns v1", () => {
    const legacy = { placement, obj: { type: "message_delta", content: "Hi" } };
    expect(readChatHistory("session", { packets: [[legacy]] }).packets).toEqual(
      [[legacy]],
    );
    const cursor = { stream_id: 1, next_cursor: 2, replay_complete: true };
    expect(readChatNotification(cursor, "session")).toEqual(cursor);
  });

  it("rejects notifications for another conversation", () => {
    expect(() => readChatNotification(failure, "another")).toThrow();
  });
});
