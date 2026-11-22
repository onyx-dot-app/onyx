import { createRef } from "react";
import { act, fireEvent, render, screen } from "@testing-library/react";
import ChatScrollContainer, {
  ChatScrollContainerHandle,
} from "@/lib/chatScroll/components/ChatScrollContainer";

const VIEWPORT_HEIGHT = 400;
/** Longer than the window in which a move counts as the user's. */
const AFTER_INPUT_MS = 1000;

const originalScrollTo = Object.getOwnPropertyDescriptor(
  HTMLElement.prototype,
  "scrollTo"
);
let frames: FrameRequestCallback[] = [];

beforeEach(() => {
  jest.useFakeTimers();
  frames = [];
  jest.spyOn(window, "requestAnimationFrame").mockImplementation((callback) => {
    frames.push(callback);
    return frames.length;
  });
  Object.defineProperty(HTMLElement.prototype, "scrollTo", {
    configurable: true,
    writable: true,
    value: jest.fn(),
  });
});

afterEach(() => {
  jest.restoreAllMocks();
  jest.useRealTimers();
  if (originalScrollTo) {
    Object.defineProperty(HTMLElement.prototype, "scrollTo", originalScrollTo);
  } else {
    Reflect.deleteProperty(HTMLElement.prototype, "scrollTo");
  }
});

/** A chat at its end: 1000px of content in a 400px viewport. */
function renderChat({ autoScroll = true, paused = false } = {}) {
  const ref = createRef<ChatScrollContainerHandle>();
  const chat = (enabled: boolean, pause: boolean) => (
    <ChatScrollContainer
      ref={ref}
      sessionId="session"
      anchorSelector="#anchor"
      autoScroll={enabled}
      pauseFollowing={pause}
    >
      <div id="anchor" />
    </ChatScrollContainer>
  );
  const view = render(chat(autoScroll, paused));
  const container = screen.getByTestId("chat-scroll-container");
  let contentHeight = 1000;
  Object.defineProperties(container, {
    clientHeight: { get: () => VIEWPORT_HEIGHT },
    scrollHeight: { get: () => contentHeight },
  });
  container.scrollTo = jest.fn(
    (options?: ScrollToOptions | number, y?: number) => {
      const top = typeof options === "number" ? y : options?.top;
      if (top !== undefined) container.scrollTop = top;
    }
  );
  act(() => ref.current?.scrollToBottom("instant"));

  const flushFrames = () =>
    act(() => frames.splice(0).forEach((callback) => callback(0)));
  /** Content below grows: the observers react on the next frame. */
  const grow = async (by: number) => {
    await act(async () => {
      contentHeight += by;
      container.firstElementChild?.appendChild(document.createElement("div"));
      // Let the MutationObserver deliver its records before the frame.
      await Promise.resolve();
    });
    flushFrames();
  };
  /** The user scrolls: a wheel input, then the position changes. */
  const userScroll = (top: number) => {
    fireEvent.wheel(container);
    container.scrollTop = top;
    fireEvent.scroll(container);
    flushFrames();
  };
  /** The position changes with no input (a Firefox clamp, anchoring). */
  const layoutMove = (top: number) => {
    container.scrollTop = top;
    fireEvent.scroll(container);
    flushFrames();
  };
  const settleInput = () => act(() => jest.advanceTimersByTime(AFTER_INPUT_MS));
  const setFollowing = (enabled: boolean, pause = false) =>
    act(() => view.rerender(chat(enabled, pause)));
  return {
    ref,
    container,
    grow,
    userScroll,
    layoutMove,
    settleInput,
    setFollowing,
  };
}

test("mounting with no messages starts no scroll", () => {
  const view = render(<ChatScrollContainer>{null}</ChatScrollContainer>);
  expect(HTMLElement.prototype.scrollTo).not.toHaveBeenCalled();
  view.unmount();
});

test("a view at the end follows new content", async () => {
  const { container, grow } = renderChat();
  await grow(48);
  expect(container.scrollTop).toBe(648);
});

test("with auto-scroll off, growth does not move the view, nor does a later resume", async () => {
  const { container, grow, setFollowing } = renderChat({ autoScroll: false });
  await grow(48);
  expect(container.scrollTop).toBe(600);
  setFollowing(true);
  expect(container.scrollTop).toBe(600);
});

/** The chat's width changes, as when a side panel opens beside it. */
function resize(container: HTMLElement, width: number) {
  Object.defineProperty(container, "clientWidth", {
    configurable: true,
    get: () => width,
  });
}

test("with auto-scroll off, a width change that reflows the rows keeps a view at the end there", async () => {
  const { container, grow } = renderChat({ autoScroll: false });
  resize(container, 600);
  await grow(300);
  expect(container.scrollTop).toBe(900);
});

test("a width change does not move a reading view", async () => {
  const { container, grow, userScroll, settleInput } = renderChat();
  userScroll(100);
  settleInput();
  resize(container, 600);
  await grow(300);
  expect(container.scrollTop).toBe(100);
});

test("a user scroll up stops following", async () => {
  const { container, grow, userScroll, settleInput } = renderChat();
  userScroll(100);
  settleInput();
  await grow(48);
  expect(container.scrollTop).toBe(100);
});

test("a user scroll back to the end resumes following", async () => {
  const { container, grow, userScroll, settleInput } = renderChat();
  userScroll(100);
  userScroll(600);
  settleInput();
  await grow(48);
  expect(container.scrollTop).toBe(648);
});

test("a pause holds the view at the end, and the resume catches up", async () => {
  // The typewriter's drain pauses following without turning it off.
  const { container, grow, setFollowing } = renderChat({ paused: true });
  await grow(48);
  expect(container.scrollTop).toBe(600);
  setFollowing(true, false);
  expect(container.scrollTop).toBe(648);
});

test("a move with no input puts a following view back at the end", () => {
  const { container, layoutMove, settleInput } = renderChat();
  settleInput();
  layoutMove(300);
  expect(container.scrollTop).toBe(600);
});

test("a user scroll during a glide ends it, and later content does not move the view", async () => {
  const { ref, container, grow, userScroll, settleInput } = renderChat();
  act(() => ref.current?.scrollToBottom("smooth"));
  userScroll(100);
  settleInput();
  await grow(48);
  expect(container.scrollTop).toBe(100);
});
