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

  it("detects skill scripts in bash commands and surfaces the description", () => {
    const packet = {
      tool_call_id: "bash-call-1",
      kind: "execute",
      status: "in_progress",
      raw_input: {
        command: "python .opencode/skills/linear/linear_api.py issue ENG-123",
        description: "Fetch Linear issue ENG-123",
      },
      _meta: { toolName: "bash" },
    };
    expect(parsePacket({ type: "tool_call_start", ...packet })).toMatchObject({
      type: "tool_call_start",
      toolName: "bash",
      kind: "execute",
      skillName: "linear",
      description: "Fetch Linear issue ENG-123",
    });
    expect(
      parsePacket({ type: "tool_call_progress", ...packet })
    ).toMatchObject({
      type: "tool_call_progress",
      toolName: "bash",
      kind: "execute",
      skillName: "linear",
      description: "Fetch Linear issue ENG-123",
    });
  });

  it("detects gh CLI commands as the github skill", () => {
    const packet = {
      tool_call_id: "bash-call-3",
      kind: "execute",
      status: "completed",
      raw_input: {
        command: "gh api user",
        description: "Get the connected GitHub user",
      },
      _meta: { toolName: "bash" },
    };
    expect(parsePacket({ type: "tool_call_start", ...packet })).toMatchObject({
      type: "tool_call_start",
      skillName: "github",
      description: "Get the connected GitHub user",
    });
    expect(
      parsePacket({ type: "tool_call_progress", ...packet })
    ).toMatchObject({
      type: "tool_call_progress",
      skillName: "github",
      description: "Get the connected GitHub user",
    });
  });

  it("does not attach a skill to ordinary bash commands", () => {
    expect(
      parsePacket({
        type: "tool_call_progress",
        tool_call_id: "bash-call-2",
        kind: "execute",
        status: "completed",
        raw_input: { command: "ls -lah src/", description: "list files" },
        _meta: { toolName: "bash" },
      })
    ).toMatchObject({
      type: "tool_call_progress",
      skillName: null,
      description: "list files",
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

  it("parses connect-app requests with their correlation id and slug", () => {
    expect(
      parsePacket({
        type: "connect_app_request",
        request_id: "req-1",
        app_slug: "google_calendar",
        reason: "to schedule events",
      })
    ).toEqual({
      type: "connect_app_request",
      requestId: "req-1",
      appSlug: "google_calendar",
      reason: "to schedule events",
    });
  });

  it("parses context_usage from persisted (snake_case) and live (camelCase) shapes", () => {
    expect(parsePacket({ type: "context_usage", used_tokens: 15526 })).toEqual({
      type: "context_usage",
      usedTokens: 15526,
    });

    expect(parsePacket({ type: "context_usage", usedTokens: 42 })).toEqual({
      type: "context_usage",
      usedTokens: 42,
    });
  });

  it("parses compaction packets, defaulting a missing summary to null", () => {
    expect(
      parsePacket({ type: "compaction", summary: "Recap of earlier work" })
    ).toEqual({ type: "compaction", summary: "Recap of earlier work" });
    expect(parsePacket({ type: "compaction" })).toEqual({
      type: "compaction",
      summary: null,
    });
  });
});
