import { craftPacketToEvents } from "@/lib/timeline/craft/events";
import { reduceTimelineEvents } from "@/lib/timeline/reducer";

describe("craftPacketToEvents", () => {
  it("maps a live tool call start and update, with unset fields as null", () => {
    const events = [
      {
        type: "tool_call_start",
        sessionUpdate: "tool_call",
        toolCallId: "t1",
        title: "Running command",
        kind: "execute",
        status: "pending",
        content: null,
        locations: null,
        rawInput: { command: "npm test" },
        rawOutput: null,
        _meta: { toolName: "bash" },
      },
      {
        type: "tool_call_progress",
        sessionUpdate: "tool_call_update",
        toolCallId: "t1",
        title: null,
        kind: null,
        status: "completed",
        content: null,
        locations: null,
        rawInput: null,
        rawOutput: { output: "ok" },
        _meta: { toolName: "bash" },
      },
    ].flatMap((packet) => craftPacketToEvents(packet));

    const state = reduceTimelineEvents(events);
    const payload = state.entries[0]?.payload;
    expect(payload?.kind === "tool" && payload.toolCall).toMatchObject({
      toolCallId: "t1",
      title: "Running command",
      kind: "execute",
      status: "completed",
      rawInput: { command: "npm test" },
      rawOutput: { output: "ok" },
      _meta: { toolName: "bash" },
    });
  });

  it("reads saved rows, which use their own type names", () => {
    const events = [
      {
        type: "agent_thought",
        content: { type: "text", text: "Planning." },
      },
      {
        type: "tool_call_progress",
        sessionUpdate: "tool_call_update",
        toolCallId: "t1",
        title: "Editing file",
        kind: "edit",
        status: "completed",
        content: [{ type: "diff", path: "a.ts", oldText: "a", newText: "b" }],
        _meta: { toolName: "edit" },
      },
      { type: "agent_message", content: { type: "text", text: "Done." } },
    ].flatMap((packet) => craftPacketToEvents(packet));

    expect(
      reduceTimelineEvents(events).entries.map((entry) => entry.payload.kind)
    ).toEqual(["thinking", "tool", "message"]);
  });

  it("moves the text part id and snapshot into _meta.onyx", () => {
    expect(
      craftPacketToEvents({
        type: "agent_message_chunk",
        sessionUpdate: "agent_message_chunk",
        content: { type: "text", text: "lo" },
        _meta: { partId: "p1", snapshotText: "Hello" },
      })
    ).toEqual([
      {
        type: "update",
        update: {
          sessionUpdate: "agent_message_chunk",
          content: { type: "text", text: "lo" },
          _meta: { onyx: { partId: "p1", snapshotText: "Hello" } },
        },
      },
    ]);
  });

  it("leaves out subagent events and saved subagent output", () => {
    expect(
      craftPacketToEvents({
        type: "agent_message_chunk",
        sessionUpdate: "agent_message_chunk",
        content: { type: "text", text: "child" },
        _meta: { sessionId: "child", parentSessionId: "parent" },
      })
    ).toEqual([]);
    expect(
      craftPacketToEvents({
        type: "agent_message",
        source: "task_output",
        content: { type: "text", text: "output" },
      })
    ).toEqual([]);
  });

  it("turns TodoWrite into a plan update instead of a step", () => {
    expect(
      craftPacketToEvents({
        type: "tool_call_progress",
        sessionUpdate: "tool_call_update",
        toolCallId: "todo",
        status: "completed",
        rawInput: {
          todos: [
            { content: "Build", status: "completed", activeForm: "Building" },
            { content: "Ship", status: "pending" },
          ],
        },
        _meta: { toolName: "todowrite" },
      })
    ).toEqual([
      {
        type: "update",
        update: {
          sessionUpdate: "plan",
          entries: [
            {
              content: "Build",
              priority: "medium",
              status: "completed",
              _meta: { onyx: { activeForm: "Building" } },
            },
            { content: "Ship", priority: "medium", status: "pending" },
          ],
        },
      },
    ]);
  });

  it("maps the turn's end and its failures", () => {
    expect(
      craftPacketToEvents({ type: "prompt_response", stopReason: "cancelled" })
    ).toEqual([{ type: "stop", stopReason: "cancelled" }]);
    expect(
      craftPacketToEvents({
        type: "turn_completed",
        status: "FAILED",
        error_detail: "Sandbox crashed",
      })
    ).toEqual([{ type: "error", message: "Sandbox crashed" }]);
    expect(
      craftPacketToEvents({ type: "turn_completed", status: "SUCCEEDED" })
    ).toEqual([]);
    expect(
      craftPacketToEvents({ type: "error", message: "Rate limited" })
    ).toEqual([{ type: "error", message: "Rate limited" }]);
  });

  it("maps compaction and connect-app requests to Onyx notifications", () => {
    expect(
      craftPacketToEvents({ type: "compaction", summary: "Trimmed" })
    ).toEqual([
      {
        type: "ext",
        notification: {
          method: "_onyx/compaction",
          params: { summary: "Trimmed" },
        },
      },
    ]);
    expect(
      craftPacketToEvents({
        type: "connect_app_request",
        request_id: "r1",
        external_app_id: 7,
        reason: "Needs Linear",
      })
    ).toEqual([
      {
        type: "ext",
        notification: {
          method: "_onyx/connect_app_request",
          params: { requestId: "r1", externalAppId: 7, reason: "Needs Linear" },
        },
      },
    ]);
    expect(
      craftPacketToEvents({
        type: "connect_app_request",
        request_id: "r2",
        external_app_id: -1,
      })
    ).toEqual([]);
  });

  it("returns no events for packets the timeline does not show", () => {
    expect(craftPacketToEvents({ type: "context_usage", used: 10 })).toEqual(
      []
    );
    expect(craftPacketToEvents({ type: "approval_requested" })).toEqual([]);
    expect(craftPacketToEvents("not a packet")).toEqual([]);
  });
});
