import { describe, expect, it, jest } from "@jest/globals";

import { makeMessageStartPacket, makePacket } from "@/chat/__tests__/fixtures";

import { findRenderer } from "../findRenderer";
import { MessageTextRenderer } from "../MessageTextRenderer";

// findRenderer transitively imports StreamingMarkdown, whose react-native-streamdown (worklets) crashes
// under jest. Stub the leaf; dispatch still returns the real MessageTextRenderer.
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

  it("returns null for reasoning-only packets (renderer wired in 9b.6)", () => {
    const packets = [
      makePacket({ type: "reasoning_start" }),
      makePacket({ type: "reasoning_delta", reasoning: "thinking" }),
    ];
    expect(findRenderer(packets)).toBeNull();
  });

  it("returns null for section-end / error-only packets", () => {
    expect(findRenderer([makePacket({ type: "section_end" })])).toBeNull();
    expect(
      findRenderer([makePacket({ type: "error", message: "boom" })]),
    ).toBeNull();
  });

  it("returns null for an empty packet list", () => {
    expect(findRenderer([])).toBeNull();
  });
});
