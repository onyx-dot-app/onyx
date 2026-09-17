import { describe, expect, it } from "@jest/globals";
import { makeItem } from "@/chat/__tests__/fixtures";
import {
  getToolName,
  hasToolError,
  isToolComplete,
} from "@/chat/timeline/toolDisplay";

describe("tool display", () => {
  it("keeps the parent completion separate from nested activity", () => {
    const root = makeItem({
      kind: "tool",
      name: "research_agent",
      arguments: {},
      status: "running",
      output: "",
      metadata: null,
    });
    const child = makeItem(
      { kind: "reasoning", text: "Done", status: "complete" },
      { sub_turn_index: 0 },
    );
    expect(isToolComplete([root, child])).toBe(false);
    expect(
      isToolComplete([
        { ...root, content: { ...root.content, status: "complete" } },
        child,
      ]),
    ).toBe(true);
  });
  it("uses the actual custom tool name and its error status", () => {
    const item = makeItem({
      kind: "tool",
      name: "Jira",
      arguments: {},
      status: "error",
      output: "Unavailable",
      metadata: null,
    });
    expect(getToolName([item])).toBe("Jira");
    expect(hasToolError([item])).toBe(true);
  });
});
