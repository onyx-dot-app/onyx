import { describe, expect, it } from "@jest/globals";

import { type Packet } from "@/chat/streamingModels";
import {
  isCodingAgentPackets,
  isPythonToolPackets,
  isReasoningPackets,
  isSearchToolPackets,
} from "@/chat/timeline/packetHelpers";
import {
  isActualToolCallPacket,
  isDisplayPacket,
  isToolPacket,
} from "@/chat/timeline/packetUtils";
import {
  getToolKey,
  getToolName,
  hasToolError,
  isToolComplete,
  parseToolKey,
} from "@/chat/timeline/toolDisplay";

import { makePlacedPacket } from "../../__tests__/fixtures";

const reasoning: Packet = makePlacedPacket({ type: "reasoning_start" });
const searchInternet: Packet = makePlacedPacket({
  type: "search_tool_start",
  is_internet_search: true,
});
const searchInternal: Packet = makePlacedPacket({ type: "search_tool_start" });
const message: Packet = makePlacedPacket({
  type: "message_start",
  id: "m",
  content: "",
  final_documents: null,
});
const sectionEnd: Packet = makePlacedPacket({ type: "section_end" });
const errorPacket: Packet = makePlacedPacket({ type: "error" });

describe("packetUtils / packetHelpers", () => {
  it("classifies tool vs non-tool packets", () => {
    expect(isToolPacket(reasoning)).toBe(true);
    expect(isToolPacket(message)).toBe(false);
    expect(isToolPacket(sectionEnd, true)).toBe(true);
    expect(isToolPacket(sectionEnd, false)).toBe(false);
  });

  it("excludes reasoning from actual tool calls", () => {
    expect(isActualToolCallPacket(reasoning)).toBe(false);
    expect(isActualToolCallPacket(searchInternal)).toBe(true);
  });

  it("identifies display packets", () => {
    expect(isDisplayPacket(message)).toBe(true);
    expect(isDisplayPacket(reasoning)).toBe(false);
  });

  it("has per-family predicates", () => {
    expect(isReasoningPackets([reasoning])).toBe(true);
    expect(isSearchToolPackets([searchInternal])).toBe(true);
    expect(isReasoningPackets([searchInternal])).toBe(false);
    expect(
      isPythonToolPackets([
        makePlacedPacket({ type: "python_tool_start", code: "x" }),
      ]),
    ).toBe(true);
    expect(
      isCodingAgentPackets([
        makePlacedPacket({ type: "bash_tool_start", cmd: "ls" }),
      ]),
    ).toBe(true);
  });
});

describe("toolDisplay", () => {
  it("round-trips a tool key", () => {
    expect(getToolKey(2, 3)).toBe("2-3");
    expect(parseToolKey("2-3")).toEqual({ turn_index: 2, tab_index: 3 });
    expect(parseToolKey("bad")).toEqual({ turn_index: NaN, tab_index: 0 });
  });

  it("names tools, discriminating internet vs internal search", () => {
    expect(getToolName([reasoning])).toBe("Thinking");
    expect(getToolName([searchInternet])).toBe("Web Search");
    expect(getToolName([searchInternal])).toBe("Internal Search");
    expect(getToolName([])).toBe("Tool");
  });

  it("detects completion and errors", () => {
    expect(isToolComplete([reasoning, sectionEnd])).toBe(true);
    expect(isToolComplete([reasoning])).toBe(false);
    expect(hasToolError([reasoning, errorPacket])).toBe(true);
    expect(hasToolError([reasoning, sectionEnd])).toBe(false);
  });

  it("only counts a research agent complete on a parent-level SECTION_END", () => {
    const researchStart: Packet = makePlacedPacket({
      type: "research_agent_start",
      research_task: "t",
    });
    const nestedEnd: Packet = makePlacedPacket(
      { type: "section_end" },
      { turn_index: 0, sub_turn_index: 1 },
    );
    const parentEnd: Packet = makePlacedPacket({ type: "section_end" });
    expect(isToolComplete([researchStart, nestedEnd])).toBe(false);
    expect(isToolComplete([researchStart, parentEnd])).toBe(true);
  });
});
