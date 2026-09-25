import { describe, expect, it } from "@jest/globals";

import { type Packet } from "@/chat/streamingModels";
import {
  constructCurrentReasoningState,
  extractFirstParagraph,
  resolveGroupReasoning,
} from "@/chat/timeline/reasoningState";

import { makePacket } from "../../__tests__/fixtures";

const delta = (reasoning: string) =>
  makePacket({ type: "reasoning_delta", reasoning });

describe("extractFirstParagraph", () => {
  it("promotes a leading markdown heading to the title and drops it from the body", () => {
    expect(extractFirstParagraph("## Checking the docs\n\nbody text")).toEqual({
      title: "Checking the docs",
      remainingContent: "body text",
    });
  });

  it("accepts any heading level", () => {
    expect(extractFirstParagraph("#### Deep\nrest").title).toBe("Deep");
  });

  it("leaves plain prose as body with no title", () => {
    const content = "Checking the docs\n\nbody text";
    expect(extractFirstParagraph(content)).toEqual({
      title: null,
      remainingContent: content,
    });
  });

  it("requires whitespace after the hashes (a bare #tag is not a heading)", () => {
    const content = "#tag not a heading";
    expect(extractFirstParagraph(content).title).toBeNull();
  });

  it("rejects a heading longer than 60 characters and keeps the full content", () => {
    const longHeading = `# ${"a".repeat(61)}`;
    const content = `${longHeading}\n\nbody`;
    expect(extractFirstParagraph(content)).toEqual({
      title: null,
      remainingContent: content,
    });
  });

  it("accepts a heading of exactly 60 characters (boundary is inclusive)", () => {
    const title = "a".repeat(60);
    expect(extractFirstParagraph(`# ${title}\n\nbody`).title).toBe(title);
  });

  it("returns no title for empty or whitespace-only content", () => {
    expect(extractFirstParagraph("")).toEqual({
      title: null,
      remainingContent: "",
    });
    expect(extractFirstParagraph("   \n  ")).toEqual({
      title: null,
      remainingContent: "   \n  ",
    });
  });

  it("returns an empty body when the heading is the entire content", () => {
    expect(extractFirstParagraph("# Only a heading")).toEqual({
      title: "Only a heading",
      remainingContent: "",
    });
  });

  it("splits on a single newline as well as a paragraph break", () => {
    expect(extractFirstParagraph("# Title\nline two")).toEqual({
      title: "Title",
      remainingContent: "line two",
    });
  });
});

describe("constructCurrentReasoningState", () => {
  it("joins reasoning deltas in packet order with no separator", () => {
    const state = constructCurrentReasoningState([
      makePacket({ type: "reasoning_start" }),
      delta("Let me "),
      delta("think "),
      delta("about it."),
    ]);
    expect(state).toEqual({
      hasStart: true,
      hasEnd: false,
      content: "Let me think about it.",
    });
  });

  it("ignores non-reasoning packets when accumulating content", () => {
    const state = constructCurrentReasoningState([
      makePacket({ type: "reasoning_start" }),
      delta("kept"),
      makePacket({ type: "message_delta", content: "dropped" }),
    ]);
    expect(state.content).toBe("kept");
  });

  it.each([
    ["section_end", makePacket({ type: "section_end" })],
    ["error", makePacket({ type: "error", message: "boom" })],
    ["reasoning_done", makePacket({ type: "reasoning_done" })],
  ])("treats %s as the end of the reasoning step", (_label, terminator) => {
    const state = constructCurrentReasoningState([
      makePacket({ type: "reasoning_start" }),
      delta("thinking"),
      terminator,
    ]);
    expect(state.hasEnd).toBe(true);
  });

  it("reports an end without a start (history hydrated mid-step)", () => {
    const state = constructCurrentReasoningState([
      delta("thinking"),
      makePacket({ type: "section_end" }),
    ]);
    expect(state).toEqual({
      hasStart: false,
      hasEnd: true,
      content: "thinking",
    });
  });

  it("returns the empty state for no packets", () => {
    expect(constructCurrentReasoningState([])).toEqual({
      hasStart: false,
      hasEnd: false,
      content: "",
    });
  });
});

describe("resolveGroupReasoning", () => {
  function mapWith(...reasoning: string[]): Map<string, Packet[]> {
    return new Map([
      [
        "0-0",
        [makePacket({ type: "reasoning_start" }), ...reasoning.map(delta)],
      ],
      ["1-0", [makePacket({ type: "search_tool_start" })]],
    ]);
  }

  it("returns null when no reader is open", () => {
    expect(resolveGroupReasoning(mapWith("thinking"), null)).toBeNull();
  });

  it("returns the named group's reasoning, not another step's", () => {
    expect(resolveGroupReasoning(mapWith("thinking"), "0-0")).toBe("thinking");
    expect(resolveGroupReasoning(mapWith("thinking"), "1-0")).toBe("");
  });

  // The point of resolving by key: re-running against a grown map must yield the grown text. A
  // snapshot taken when the reader opened would freeze here, and Copy would truncate.
  it("tracks the stream as the group's packets grow", () => {
    expect(resolveGroupReasoning(mapWith("first "), "0-0")).toBe("first ");
    expect(resolveGroupReasoning(mapWith("first ", "second"), "0-0")).toBe(
      "first second",
    );
  });

  it("returns null for a key with no group (history reset)", () => {
    expect(resolveGroupReasoning(mapWith("thinking"), "9-9")).toBeNull();
  });
});
