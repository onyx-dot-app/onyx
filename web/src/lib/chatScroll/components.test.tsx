import { act, render, screen } from "@tests/setup/test-utils";
import { ChatScrollView, WindowedRow } from "@/lib/chatScroll/components";

// Distance from the row to the scroll container's viewport.
const ROW_DISTANCE_PX = 400;

const resizeCallbacks = new Map<Element, (() => void)[]>();
let intersectionObservers = 0;
let viewportHeight = 100;
const originalIntersectionObserver = global.IntersectionObserver;
const originalResizeObserver = global.ResizeObserver;
const originalClientHeight = Object.getOwnPropertyDescriptor(
  HTMLElement.prototype,
  "clientHeight"
);

beforeEach(() => {
  resizeCallbacks.clear();
  intersectionObservers = 0;
  viewportHeight = 100;
  Object.defineProperty(HTMLElement.prototype, "clientHeight", {
    configurable: true,
    get(this: HTMLElement) {
      return this.hasAttribute("data-chat-scroll") ? viewportHeight : 0;
    },
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
      const callbacks = resizeCallbacks.get(target) ?? [];
      callbacks.push(() =>
        this.callback([], this as unknown as ResizeObserver)
      );
      resizeCallbacks.set(target, callbacks);
    }
    disconnect() {}
  } as unknown as typeof ResizeObserver;
});

afterEach(() => {
  global.IntersectionObserver = originalIntersectionObserver;
  global.ResizeObserver = originalResizeObserver;
  if (originalClientHeight) {
    Object.defineProperty(
      HTMLElement.prototype,
      "clientHeight",
      originalClientHeight
    );
  }
});

test("a row mounted while the chat was short stays mounted once the chat grows", () => {
  render(
    <ChatScrollView data-testid="chat">
      <WindowedRow id="message-1" initiallyMounted>
        First message
      </WindowedRow>
      <WindowedRow id="message-2" initiallyMounted>
        Second message
      </WindowedRow>
    </ChatScrollView>
  );
  expect(screen.queryByText("First message")).not.toBeInTheDocument();
  // The rows share one observer of the container.
  expect(intersectionObservers).toBe(1);

  viewportHeight = 720;
  const root = screen.getByTestId("chat");
  act(() => resizeCallbacks.get(root)?.forEach((callback) => callback()));
  expect(screen.getByText("First message")).toBeInTheDocument();
  expect(screen.getByText("Second message")).toBeInTheDocument();
  expect(intersectionObservers).toBe(2);
});
