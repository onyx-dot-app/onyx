import { describe, expect, it, jest } from "@jest/globals";
import { makeItem } from "@/chat/__tests__/fixtures";
import { findRenderer } from "@/components/chat/renderers/findRenderer";
import { MessageTextRenderer } from "@/components/chat/renderers/MessageTextRenderer";
import { ReasoningRenderer } from "@/components/chat/renderers/ReasoningRenderer";
jest.mock("@/components/chat/StreamingMarkdown", () => ({
  StreamingMarkdown: () => null,
}));
describe("renderer dispatch", () => {
  it("selects text and reasoning by item kind", () => {
    expect(
      findRenderer([
        makeItem({
          kind: "text",
          text: "answer",
          purpose: "answer",
          status: "complete",
          documents: [],
          citations: [],
        }),
      ]),
    ).toBe(MessageTextRenderer);
    expect(
      findRenderer([
        makeItem({ kind: "reasoning", text: "thinking", status: "running" }),
      ]),
    ).toBe(ReasoningRenderer);
  });
  it("does not render tool output as reasoning", () => {
    expect(
      findRenderer([
        makeItem({
          kind: "tool",
          name: "internal_search",
          arguments: {},
          status: "complete",
          output: "",
          metadata: null,
        }),
      ]),
    ).toBeNull();
  });
});
