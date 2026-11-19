import { buildCraftTranscript } from "@/app/craft/utils/timelineEntries";
import type { StreamItem, ToolCallState } from "@/app/craft/types/displayTypes";

function toolItem(
  id: string,
  status: ToolCallState["status"] = "completed"
): StreamItem {
  return {
    type: "tool_call",
    id,
    toolCall: {
      id,
      kind: "execute",
      title: "Running command",
      description: "",
      command: "ls",
      status,
      rawOutput: "",
    },
  };
}

describe("buildCraftTranscript", () => {
  it("puts consecutive tool calls and thinking on one rail block, split by text", () => {
    const blocks = buildCraftTranscript([
      { type: "thinking", id: "t1", content: "Plan.", isStreaming: false },
      toolItem("a"),
      toolItem("b", "in_progress"),
      { type: "text", id: "x", content: "Done.", isStreaming: false },
      toolItem("c", "failed"),
    ]);

    expect(
      blocks.map((block) =>
        block.kind === "steps"
          ? block.entries.map((e) => `${e.id}:${e.status}`)
          : block.item.id
      )
    ).toEqual([["t1:done", "a:done", "b:streaming"], "x", ["c:error"]]);
  });

  it("drops empty thinking", () => {
    const blocks = buildCraftTranscript([
      { type: "thinking", id: "t1", content: "", isStreaming: true },
    ]);

    expect(blocks).toEqual([]);
  });
});
