import { renderHook } from "@testing-library/react";
import { platform, size } from "@floating-ui/react-dom";
import { useDropdownOverlay } from "@opal/components/dropdown/hooks";

jest.mock("@floating-ui/react-dom", () => {
  const actual = jest.requireActual<typeof import("@floating-ui/react-dom")>(
    "@floating-ui/react-dom"
  );
  return { ...actual, size: jest.fn(actual.size) };
});

describe("dropdown width within the viewport", () => {
  it.each([
    { anchorWidth: 480, availableWidth: 302, expectedWidth: 302 },
    { anchorWidth: 200, availableWidth: 900, expectedWidth: 212 },
    { anchorWidth: 200, availableWidth: -5, expectedWidth: 0 },
  ])("limits a $anchorWidth px anchor to $availableWidth px", async (test) => {
    jest.mocked(size).mockClear();
    renderHook(() =>
      useDropdownOverlay({ disabled: false, align: "start", side: "bottom" })
    );
    const options = jest.mocked(size).mock.calls[0]?.[0];
    if (!options || typeof options === "function" || !options.apply) {
      throw new Error(
        "Dropdown must provide size middleware with an apply callback"
      );
    }
    const reference = document.createElement("button");
    const floating = document.createElement("div");
    await options.apply({
      x: 0,
      y: 0,
      initialPlacement: "bottom-start",
      placement: "bottom-start",
      strategy: "absolute",
      middlewareData: {},
      platform,
      elements: { reference, floating },
      rects: {
        reference: { x: 0, y: 0, width: test.anchorWidth, height: 40 },
        floating: { x: 0, y: 0, width: 0, height: 100 },
      },
      availableWidth: test.availableWidth,
      availableHeight: 500,
    });
    expect(floating.style.width).toBe(`${test.expectedWidth}px`);
    expect(floating.style.minWidth).toBe(
      `min(var(--block-width-dropdown-min), ${Math.max(0, test.availableWidth)}px)`
    );
  });
});
