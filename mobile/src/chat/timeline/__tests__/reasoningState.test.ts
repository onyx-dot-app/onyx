import { describe, expect, it } from "@jest/globals";

import { type ResponseItem } from "@/chat/streamingModels";
import {
  constructCurrentReasoningState,
  extractFirstParagraph,
  resolveGroupReasoning,
} from "@/chat/timeline/reasoningState";

import { makeItem } from "../../__tests__/fixtures";

const reasoningItem = (
  text: string,
  status: "running" | "complete" = "running",
) => makeItem({ kind: "reasoning", text, status });

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

describe("reasoning snapshots", () => {
  it("reads partial and completed reasoning from the same item shape", () => {
    expect(constructCurrentReasoningState([reasoningItem("Thinking")])).toEqual(
      { hasStart: true, hasEnd: false, content: "Thinking" },
    );
    expect(
      constructCurrentReasoningState([reasoningItem("Finished", "complete")]),
    ).toEqual({ hasStart: true, hasEnd: true, content: "Finished" });
  });
  it("resolves the latest item value for the open reasoning reader", () => {
    const groups = new Map<string, ResponseItem[]>([
      ["0-0", [reasoningItem("First")]],
    ]);
    expect(resolveGroupReasoning(groups, "0-0")).toBe("First");
    groups.set("0-0", [reasoningItem("First and second")]);
    expect(resolveGroupReasoning(groups, "0-0")).toBe("First and second");
    expect(resolveGroupReasoning(groups, "missing")).toBeNull();
  });
});
