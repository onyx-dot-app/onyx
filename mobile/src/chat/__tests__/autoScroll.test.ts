import { describe, expect, it } from "@jest/globals";

import {
  AT_BOTTOM_THRESHOLD_PX,
  contentSignature,
  distanceFromBottom,
  isWithinBottomBand,
  ScrollMetrics,
} from "@/chat/autoScroll";
import { Message } from "@/chat/interfaces";

// A long chat scrolled to various positions. contentHeight 1000, viewport 600 → max offset 400.
function metrics(offsetY: number): ScrollMetrics {
  return { offsetY, contentHeight: 1000, viewportHeight: 600 };
}

function node(over: Partial<Message>): Message {
  return {
    nodeId: 1,
    parentNodeId: null,
    type: "assistant",
    message: "",
    files: [],
    packets: [],
    ...over,
  };
}

describe("distanceFromBottom", () => {
  it("is zero at the very bottom", () => {
    expect(distanceFromBottom(metrics(400))).toBe(0);
  });

  it("grows as the user scrolls up", () => {
    expect(distanceFromBottom(metrics(300))).toBe(100);
    expect(distanceFromBottom(metrics(0))).toBe(400);
  });

  it("is negative when content is shorter than the viewport", () => {
    expect(
      distanceFromBottom({
        offsetY: 0,
        contentHeight: 200,
        viewportHeight: 600,
      }),
    ).toBe(-400);
  });
});

describe("isWithinBottomBand", () => {
  it("treats a short (unscrollable) chat as at the bottom", () => {
    expect(
      isWithinBottomBand({
        offsetY: 0,
        contentHeight: 200,
        viewportHeight: 600,
      }),
    ).toBe(true);
  });

  it("is inclusive of the threshold boundary", () => {
    expect(isWithinBottomBand(metrics(400 - AT_BOTTOM_THRESHOLD_PX))).toBe(
      true,
    );
    expect(isWithinBottomBand(metrics(400 - AT_BOTTOM_THRESHOLD_PX - 1))).toBe(
      false,
    );
  });
});

describe("contentSignature", () => {
  it("is stable when nothing changed", () => {
    const messages = [node({ nodeId: 1, message: "hi" })];
    expect(contentSignature(messages)).toBe(contentSignature([...messages]));
  });

  it("changes when a streaming flush appends packets to the last node", () => {
    const before = contentSignature([node({ nodeId: 1, packets: [] })]);
    const after = contentSignature([
      node({ nodeId: 1, packets: [{} as never] }),
    ]);
    expect(after).not.toBe(before);
  });

  it("changes when a new turn is appended", () => {
    const before = contentSignature([node({ nodeId: 1, message: "q" })]);
    const after = contentSignature([
      node({ nodeId: 1, message: "q" }),
      node({ nodeId: 2, message: "" }),
    ]);
    expect(after).not.toBe(before);
  });

  it("handles an empty chat", () => {
    expect(contentSignature([])).toBe(`0::0:0`);
  });
});
