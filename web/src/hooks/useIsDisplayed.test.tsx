/** A hidden element reads as not displayed, and a resize after its display flips updates it. */
import { act, render, screen } from "@tests/setup/test-utils";
import useIsDisplayed from "@/hooks/useIsDisplayed";

function Probe({ hidden }: { hidden: boolean }) {
  const [ref, displayed] = useIsDisplayed<HTMLDivElement>();
  return (
    <div ref={ref} style={{ display: hidden ? "none" : "block" }}>
      <span data-testid="state">{displayed ? "shown" : "hidden"}</span>
    </div>
  );
}

const realResizeObserver = global.ResizeObserver;
let resized: (() => void) | null = null;
beforeEach(() => {
  resized = null;
  global.ResizeObserver = class {
    constructor(callback: () => void) {
      resized = callback;
    }
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;
});
afterEach(() => {
  global.ResizeObserver = realResizeObserver;
});

describe("useIsDisplayed", () => {
  it("reads display none as hidden on mount", () => {
    render(<Probe hidden />);
    expect(screen.getByTestId("state")).toHaveTextContent("hidden");
  });

  it("follows a display change once the box resizes", () => {
    const { rerender } = render(<Probe hidden={false} />);
    expect(screen.getByTestId("state")).toHaveTextContent("shown");
    rerender(<Probe hidden />);
    act(() => resized?.());
    expect(screen.getByTestId("state")).toHaveTextContent("hidden");
  });
});
