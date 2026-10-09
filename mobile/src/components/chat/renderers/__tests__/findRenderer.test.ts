import { describe, expect, it, jest } from "@jest/globals";

import { makeMessageStartPacket, makePacket } from "@/chat/__tests__/fixtures";
import { type Packet } from "@/chat/streamingModels";

import { findRenderer } from "../findRenderer";
import { MessageTextRenderer } from "../MessageTextRenderer";
import { ReasoningRenderer } from "../ReasoningRenderer";

// findRenderer transitively imports StreamingMarkdown, whose react-native-streamdown (worklets) crashes
// under jest. Stub the leaf; dispatch still returns the real renderers.
jest.mock("@/components/chat/StreamingMarkdown", () => ({
  StreamingMarkdown: () => null,
}));

describe("findRenderer", () => {
  it("routes chat packets to the message text renderer", () => {
    const packets = [
      makeMessageStartPacket(),
      makePacket({ type: "message_delta", content: "hello" }),
    ];
    expect(findRenderer(packets)).toBe(MessageTextRenderer);
  });

  it("prioritizes chat over reasoning when both are present", () => {
    const packets = [
      makePacket({ type: "reasoning_start" }),
      makePacket({ type: "reasoning_delta", reasoning: "thinking" }),
      makeMessageStartPacket(),
    ];
    expect(findRenderer(packets)).toBe(MessageTextRenderer);
  });

  it("routes reasoning-only packets to the reasoning renderer", () => {
    const packets = [
      makePacket({ type: "reasoning_start" }),
      makePacket({ type: "reasoning_delta", reasoning: "thinking" }),
    ];
    expect(findRenderer(packets)).toBe(ReasoningRenderer);
  });

  it.each([
    ["reasoning_start", makePacket({ type: "reasoning_start" })],
    [
      "reasoning_delta",
      makePacket({ type: "reasoning_delta", reasoning: "thinking" }),
    ],
  ])("routes a group carrying only %s to the reasoning renderer", (_l, p) => {
    expect(findRenderer([p])).toBe(ReasoningRenderer);
  });

  // Each unwired tool slot must still decline ahead of reasoning: every closed group carries a
  // synthesized section_end, which the reasoning predicate would otherwise match.
  describe("unwired tool slots decline before reasoning", () => {
    const toolStarts: [string, Packet][] = [
      ["image generation", makePacket({ type: "image_generation_start" })],
      ["internal search", makePacket({ type: "search_tool_start" })],
      [
        "web search",
        makePacket({ type: "search_tool_start", is_internet_search: true }),
      ],
      ["python", makePacket({ type: "python_tool_start", code: "print(1)" })],
      ["file reader", makePacket({ type: "file_reader_start" })],
      [
        "custom tool",
        makePacket({ type: "custom_tool_start", tool_name: "t" }),
      ],
      // The fetch tool's wire type is "open_url_start", not "fetch_tool_start".
      ["fetch", makePacket({ type: "open_url_start" })],
      ["memory", makePacket({ type: "memory_tool_start" })],
      ["deep research plan", makePacket({ type: "deep_research_plan_start" })],
      [
        "research agent",
        makePacket({ type: "research_agent_start", research_task: "dig" }),
      ],
      [
        "coding agent",
        makePacket({ type: "coding_agent_start", query: "fix", repo: null }),
      ],
    ];

    it.each(toolStarts)(
      "returns null for a closed %s group rather than the reasoning renderer",
      (_label, start) => {
        expect(
          findRenderer([start, makePacket({ type: "section_end" })]),
        ).toBeNull();
      },
    );

    it("declines an image group even when the turn also carried reasoning", () => {
      // MessageRow hands the renderer the node's whole flat packet list, so both turns arrive
      // together and image must win over the reasoning packets alongside it.
      expect(
        findRenderer([
          makePacket({ type: "reasoning_start" }),
          makePacket({ type: "reasoning_delta", reasoning: "picking a style" }),
          makePacket({ type: "image_generation_start" }, 1),
          makePacket({ type: "section_end" }, 1),
        ]),
      ).toBeNull();
    });
  });

  // With no tool slot claiming it, a bare section_end/error falls through to reasoning, which
  // treats it as a closed, empty step.
  it("falls through to the reasoning renderer for section-end / error-only packets", () => {
    expect(findRenderer([makePacket({ type: "section_end" })])).toBe(
      ReasoningRenderer,
    );
    expect(findRenderer([makePacket({ type: "error", message: "boom" })])).toBe(
      ReasoningRenderer,
    );
  });

  it("returns null for an empty packet list", () => {
    expect(findRenderer([])).toBeNull();
  });
});
