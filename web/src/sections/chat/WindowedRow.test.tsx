import { useRef } from "react";
import { act, render, screen } from "@tests/setup/test-utils";
import WindowedRow from "@/sections/chat/WindowedRow";
import { ScrollContainerProvider } from "@/sections/chat/ScrollContainerContext";

// Distance from the row to the scroll container's viewport.
const ROW_DISTANCE_PX = 400;

const resizeCallbacks = new Map<Element, () => void>();
const resizeTargets: Element[] = [];
let intersectionObservers = 0;
const originalIntersectionObserver = global.IntersectionObserver;
const originalResizeObserver = global.ResizeObserver;

beforeEach(() => {
  resizeCallbacks.clear();
  resizeTargets.length = 0;
  intersectionObservers = 0;
  // Native scroll anchoring, so rows make no scroll corrections.
  Object.defineProperty(window, "CSS", {
    value: { supports: () => true },
    configurable: true,
  });
  // Reports the row as near when its distance fits in the observer's margin.
  global.IntersectionObserver = class {
    constructor(
      private readonly callback: IntersectionObserverCallback,
      private readonly options?: IntersectionObserverInit
    ) {
      intersectionObservers++;
    }
    observe(target: Element) {
      const margin = Number.parseFloat(this.options?.rootMargin ?? "0");
      this.callback(
        [
          {
            target,
            isIntersecting: ROW_DISTANCE_PX <= margin,
          } as unknown as IntersectionObserverEntry,
        ],
        this as unknown as IntersectionObserver
      );
    }
    unobserve() {}
    disconnect() {}
  } as unknown as typeof IntersectionObserver;
  global.ResizeObserver = class {
    constructor(private readonly callback: ResizeObserverCallback) {}
    observe(target: Element) {
      resizeTargets.push(target);
      resizeCallbacks.set(target, () =>
        this.callback([], this as unknown as ResizeObserver)
      );
    }
    disconnect() {}
  } as unknown as typeof ResizeObserver;
});

afterEach(() => {
  global.IntersectionObserver = originalIntersectionObserver;
  global.ResizeObserver = originalResizeObserver;
});

function Chat({ root }: { root: HTMLDivElement }) {
  const scrollContainerRef = useRef(root);
  const contentWrapperRef = useRef<HTMLDivElement>(null);
  const spacerHeightRef = useRef(0);
  return (
    <ScrollContainerProvider
      scrollContainerRef={scrollContainerRef}
      contentWrapperRef={contentWrapperRef}
      spacerHeightRef={spacerHeightRef}
    >
      <WindowedRow id="message-1" initiallyMounted heightCache={new Map()}>
        First message
      </WindowedRow>
      <WindowedRow id="message-2" initiallyMounted heightCache={new Map()}>
        Second message
      </WindowedRow>
    </ScrollContainerProvider>
  );
}

test("a row mounted while the chat was short stays mounted once the chat grows", () => {
  const root = document.createElement("div");
  let height = 100;
  Object.defineProperty(root, "clientHeight", { get: () => height });
  render(<Chat root={root} />);
  expect(screen.queryByText("First message")).not.toBeInTheDocument();
  // The rows share one observer of the container.
  expect(intersectionObservers).toBe(1);
  expect(resizeTargets.filter((target) => target === root)).toHaveLength(1);

  height = 720;
  act(() => resizeCallbacks.get(root)?.());
  expect(screen.getByText("First message")).toBeInTheDocument();
  expect(screen.getByText("Second message")).toBeInTheDocument();
  expect(intersectionObservers).toBe(2);
});
