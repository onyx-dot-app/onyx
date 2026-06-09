import { parsePacket } from "@/app/craft/utils/parsePacket";

describe("parsePacket", () => {
  it("parses raw opencode thought chunks that carry the event type in sessionUpdate", () => {
    expect(
      parsePacket({
        sessionUpdate: "agent_thought_chunk",
        content: { type: "text", text: "Inspecting the app state." },
      })
    ).toEqual({
      type: "thinking_chunk",
      text: "Inspecting the app state.",
      sessionId: null,
      parentSessionId: null,
    });
  });

  it("parses persisted agent thought packets as thinking chunks", () => {
    expect(
      parsePacket({
        type: "agent_thought",
        content: { type: "text", text: "Inspecting saved context." },
      })
    ).toEqual({
      type: "thinking_chunk",
      text: "Inspecting saved context.",
      sessionId: null,
      parentSessionId: null,
    });
  });

  it("parses task starts from kind-only packets", () => {
    expect(
      parsePacket({
        type: "tool_call_start",
        tool_call_id: "task-call-1",
        kind: "task",
        raw_input: { prompt: "Build Space Invaders game" },
        _meta: { toolName: "unknown" },
      })
    ).toMatchObject({
      type: "tool_call_start",
      toolName: "task",
      kind: "task",
      command: "Build Space Invaders game",
      description: "Spawning subagent: Build Space Invaders game",
    });
  });

  it("extracts subagent session ids from completed task output", () => {
    expect(
      parsePacket({
        type: "tool_call_progress",
        tool_call_id: "task-call-1",
        kind: "task",
        status: "completed",
        raw_input: { prompt: "Build Space Invaders game" },
        raw_output: {
          output:
            "task_id: child-session-1 (for resuming to continue this task if needed)\n\n<task_result>done</task_result>",
        },
      })
    ).toMatchObject({
      type: "tool_call_progress",
      toolName: "task",
      subagentSessionId: "child-session-1",
      taskOutput:
        "task_id: child-session-1 (for resuming to continue this task if needed)\n\n<task_result>done</task_result>",
    });
  });
});
