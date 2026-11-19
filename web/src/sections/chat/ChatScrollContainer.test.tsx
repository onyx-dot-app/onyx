import { act, fireEvent, render, screen } from "@testing-library/react";
import ChatScrollContainer from "@/sections/chat/ChatScrollContainer";

const VIEWPORT_HEIGHT = 400;

const resizeCallbacks = new Map<Element, (() => void)[]>();
const originalResizeObserver = global.ResizeObserver;

beforeEach(() => {
  jest.useFakeTimers();
  resizeCallbacks.clear();
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
  jest.useRealTimers();
  global.ResizeObserver = originalResizeObserver;
});

/** A chat in a 400px viewport. */
function renderChat(autoScroll: boolean) {
  let contentHeight = 0;
  const chat = (enabled: boolean) => (
    <ChatScrollContainer sessionId="session" autoScroll={enabled}>
      <div />
    </ChatScrollContainer>
  );
  const view = render(chat(autoScroll));
  const container = screen.getByTestId("chat-scroll-container");
  Object.defineProperties(container, {
    clientHeight: { get: () => VIEWPORT_HEIGHT },
    scrollHeight: { get: () => contentHeight },
  });
  /** Content changes size: the controller reacts before paint. */
  const layout = (height: number) => {
    contentHeight = height;
    act(() => resizeCallbacks.get(container)?.forEach((run) => run()));
  };
  /** Content shrinks before any resize callback runs. */
  const shrink = (height: number) => {
    contentHeight = height;
  };
  const userScroll = (top: number) => {
    fireEvent.wheel(container);
    container.scrollTop = top;
    fireEvent.scroll(container);
  };
  /** The position moves without user input (rounding, a clamp). */
  const drift = (top: number) => {
    container.scrollTop = top;
    fireEvent.scroll(container);
  };
  const setAutoScroll = (enabled: boolean) => view.rerender(chat(enabled));
  return { container, layout, shrink, userScroll, drift, setAutoScroll };
}

/** Past the opening, when the view keeps to the end whatever the setting. */
function settleOpening() {
  act(() => jest.advanceTimersByTime(1500));
}

test("with auto-scroll on, the view follows new content at the end", () => {
  const { container, layout } = renderChat(true);
  layout(1000);
  settleOpening();
  layout(1048);
  expect(container.scrollTop).toBe(648);
});

test("with auto-scroll off, new content does not move the view", () => {
  const { container, layout } = renderChat(false);
  layout(1000);
  expect(container.scrollTop).toBe(600);
  settleOpening();
  layout(1048);
  expect(container.scrollTop).toBe(600);
});

test("a user scroll up stops following, and a return to the end resumes it", () => {
  const { container, layout, userScroll } = renderChat(true);
  layout(1000);
  settleOpening();

  userScroll(100);
  layout(1048);
  expect(container.scrollTop).toBe(100);

  userScroll(648);
  layout(1096);
  expect(container.scrollTop).toBe(696);
});

test("a pause in auto-scroll holds the view, and the resume catches up", () => {
  // The typewriter's drain turns auto-scroll off while it runs.
  const { container, layout, setAutoScroll } = renderChat(true);
  layout(1000);
  settleOpening();

  setAutoScroll(false);
  layout(1048);
  expect(container.scrollTop).toBe(600);

  setAutoScroll(true);
  expect(container.scrollTop).toBe(648);
});

test("a position change without user input does not stop following", () => {
  // The browser clamps to shorter content, or re-rounds a fractional position.
  const { container, layout, shrink, drift } = renderChat(true);
  layout(1000);
  settleOpening();

  shrink(900);
  drift(300);
  expect(container.scrollTop).toBe(500);
  layout(1000);
  expect(container.scrollTop).toBe(600);
});
