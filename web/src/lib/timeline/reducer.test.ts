import type { AcpSessionUpdate } from "@/lib/timeline/acp";
import type { TimelineEvent } from "@/lib/timeline/events";
import { reduceTimelineEvents } from "@/lib/timeline/reducer";

function update(value: AcpSessionUpdate): TimelineEvent {
  return { type: "update", update: value };
}

function thought(text: string): TimelineEvent {
  return update({
    sessionUpdate: "agent_thought_chunk",
    content: { type: "text", text },
  });
}

function message(text: string): TimelineEvent {
  return update({
    sessionUpdate: "agent_message_chunk",
    content: { type: "text", text },
  });
}

describe("reduceTimeline", () => {
  it("keeps messages, thinking and tool calls in arrival order", () => {
    const state = reduceTimelineEvents([
      thought("Let me "),
      thought("check."),
      message("Checking "),
      message("now."),
      update({ sessionUpdate: "tool_call", toolCallId: "t1", title: "Run" }),
      message("Done."),
    ]);

    expect(
      state.entries.map((entry) => [entry.id, entry.status, entry.payload])
    ).toEqual([
      ["thinking-0", "done", { kind: "thinking", text: "Let me check." }],
      [
        "message-1",
        "done",
        { kind: "message", content: [{ type: "text", text: "Checking now." }] },
      ],
      ["t1", "streaming", expect.objectContaining({ kind: "tool" })],
      [
        "message-3",
        "streaming",
        { kind: "message", content: [{ type: "text", text: "Done." }] },
      ],
    ]);
  });

  it("updates a part by its part id and replaces its text with a snapshot", () => {
    const part = (text: string, snapshotText?: string): TimelineEvent =>
      update({
        sessionUpdate: "agent_message_chunk",
        content: { type: "text", text },
        _meta: { onyx: { partId: "p1", snapshotText } },
      });
    const state = reduceTimelineEvents([
      part("Hel"),
      part("lo"),
      part("lo", "Hello"),
    ]);

    expect(state.entries).toEqual([
      {
        id: "part:p1",
        status: "streaming",
        groupId: null,
        payload: {
          kind: "message",
          content: [{ type: "text", text: "Hello" }],
        },
      },
    ]);
  });

  it("applies tool call updates and keeps the fields an update leaves out", () => {
    const state = reduceTimelineEvents([
      update({
        sessionUpdate: "tool_call",
        toolCallId: "t1",
        title: "Run tests",
        kind: "execute",
        status: "pending",
        rawInput: { command: "npm test" },
      }),
      update({
        sessionUpdate: "tool_call_update",
        toolCallId: "t1",
        status: "in_progress",
      }),
      update({
        sessionUpdate: "tool_call_update",
        toolCallId: "t1",
        status: "completed",
        content: [{ type: "content", content: { type: "text", text: "ok" } }],
      }),
    ]);

    const [entry] = state.entries;
    expect(entry?.status).toBe("done");
    expect(entry?.payload).toEqual({
      kind: "tool",
      toolCall: {
        toolCallId: "t1",
        title: "Run tests",
        kind: "execute",
        status: "completed",
        content: [{ type: "content", content: { type: "text", text: "ok" } }],
        locations: [],
        rawInput: { command: "npm test" },
        rawOutput: null,
        _meta: null,
      },
    });
  });

  it("treats null fields as unset", () => {
    const state = reduceTimelineEvents([
      update({
        sessionUpdate: "tool_call",
        toolCallId: "t1",
        title: "Read",
        rawInput: { path: "a.ts" },
      }),
      update({
        sessionUpdate: "tool_call_update",
        toolCallId: "t1",
        title: null,
        rawInput: null,
        status: "completed",
      }),
    ]);

    const payload = state.entries[0]?.payload;
    expect(payload?.kind === "tool" && payload.toolCall).toMatchObject({
      title: "Read",
      rawInput: { path: "a.ts" },
      status: "completed",
    });
  });

  it("keeps concurrent tool calls as separate entries in arrival order", () => {
    const state = reduceTimelineEvents([
      update({ sessionUpdate: "tool_call", toolCallId: "a", title: "A" }),
      update({ sessionUpdate: "tool_call", toolCallId: "b", title: "B" }),
      update({
        sessionUpdate: "tool_call_update",
        toolCallId: "a",
        status: "in_progress",
      }),
    ]);

    expect(
      state.entries.map((entry) => [entry.id, entry.status, entry.groupId])
    ).toEqual([
      ["a", "streaming", null],
      ["b", "streaming", null],
    ]);
  });

  it("keeps a cancelled call apart from a failed one", () => {
    const state = reduceTimelineEvents([
      update({ sessionUpdate: "tool_call", toolCallId: "f", title: "F" }),
      update({
        sessionUpdate: "tool_call_update",
        toolCallId: "f",
        status: "failed",
      }),
      update({ sessionUpdate: "tool_call", toolCallId: "c", title: "C" }),
      update({
        sessionUpdate: "tool_call_update",
        toolCallId: "c",
        _meta: { onyx: { cancelled: true } },
      }),
    ]);

    expect(state.entries.map((entry) => entry.status)).toEqual([
      "error",
      "stopped",
    ]);
  });

  it("adds a tool call when its first event is an update", () => {
    const state = reduceTimelineEvents([
      update({
        sessionUpdate: "tool_call_update",
        toolCallId: "late",
        title: "Read file",
        status: "in_progress",
      }),
    ]);

    expect(state.entries.map((entry) => [entry.id, entry.status])).toEqual([
      ["late", "streaming"],
    ]);
  });

  it("records the stop reason and leaves running tool calls as they are", () => {
    const state = reduceTimelineEvents([
      update({
        sessionUpdate: "tool_call",
        toolCallId: "t",
        title: "T",
        status: "in_progress",
      }),
      thought("Still thinking"),
      { type: "stop", stopReason: "cancelled" },
    ]);

    expect(state.stopReason).toBe("cancelled");
    expect(state.entries.map((entry) => [entry.id, entry.status])).toEqual([
      ["t", "streaming"],
      ["thinking-1", "done"],
    ]);
  });

  it("adds notices and errors between steps, in arrival order", () => {
    const connect: TimelineEvent = {
      type: "ext",
      notification: {
        method: "_onyx/connect_app_request",
        params: { requestId: "r1", externalAppId: 7, reason: null },
      },
    };
    const state = reduceTimelineEvents([
      update({ sessionUpdate: "tool_call", toolCallId: "t1", title: "Run" }),
      connect,
      connect,
      {
        type: "ext",
        notification: { method: "_onyx/compaction", params: { summary: null } },
      },
      { type: "error", message: "Rate limited" },
    ]);

    expect(
      state.entries.map((entry) => [entry.id, entry.status, entry.payload.kind])
    ).toEqual([
      ["t1", "streaming", "tool"],
      ["connect:r1", "done", "notice"],
      ["compaction-2", "done", "notice"],
      ["error-3", "error", "notice"],
    ]);
  });

  it("replaces the plan on each plan update", () => {
    const state = reduceTimelineEvents([
      update({
        sessionUpdate: "plan",
        entries: [{ content: "One", priority: "high", status: "pending" }],
      }),
      update({
        sessionUpdate: "plan",
        entries: [{ content: "One", priority: "high", status: "completed" }],
      }),
    ]);

    expect(state.plan).toEqual([
      { content: "One", priority: "high", status: "completed" },
    ]);
  });
});
