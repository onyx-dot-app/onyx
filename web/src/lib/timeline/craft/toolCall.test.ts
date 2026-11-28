import { parsePacket } from "@/app/craft/utils/parsePacket";
import { toolCallStateFromProgress } from "@/app/craft/utils/subagentRouting";
import { toCraftToolCall } from "@/lib/timeline/craft/toolCall";
import type { AcpToolCall } from "@/lib/timeline/reducer";

function acpToolCall(fields: Partial<AcpToolCall>): AcpToolCall {
  return {
    toolCallId: "t1",
    title: "",
    kind: null,
    status: "completed",
    content: [],
    locations: [],
    rawInput: null,
    rawOutput: null,
    _meta: null,
    ...fields,
  };
}

/** What the current stream path shows for the same wire packet. */
function streamState(toolCall: AcpToolCall) {
  const parsed = parsePacket({
    type: "tool_call_progress",
    sessionUpdate: "tool_call_update",
    ...toolCall,
  });
  if (parsed.type !== "tool_call_progress") throw new Error("not a tool call");
  return toolCallStateFromProgress(parsed);
}

describe("toCraftToolCall", () => {
  it.each([
    [
      "bash",
      acpToolCall({
        title: "Running command",
        kind: "execute",
        rawInput: { command: "npm test", description: "Run tests" },
        rawOutput: { output: "ok" },
        _meta: { toolName: "bash" },
      }),
    ],
    [
      "edit",
      acpToolCall({
        title: "Editing file",
        kind: "edit",
        rawInput: { filePath: "src/a.ts" },
        content: [
          { type: "diff", path: "src/a.ts", oldText: "a", newText: "b" },
        ],
        _meta: { toolName: "edit" },
      }),
    ],
    [
      "skill",
      acpToolCall({
        title: "Running tool",
        kind: "other",
        rawInput: { name: "linear" },
        _meta: { toolName: "skill" },
      }),
    ],
  ])("matches the stream's display fields for %s", (_name, toolCall) => {
    expect(toCraftToolCall(toolCall)).toEqual(streamState(toolCall));
  });

  it("shows a call stopped by Onyx as cancelled, not failed", () => {
    const state = toCraftToolCall(
      acpToolCall({
        kind: "execute",
        status: "in_progress",
        _meta: { toolName: "bash", onyx: { cancelled: true } },
      })
    );
    expect(state.status).toBe("cancelled");
  });
});
