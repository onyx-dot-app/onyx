import { createRef, useLayoutEffect } from "react";
import { act, fireEvent, render, screen } from "@testing-library/react";
import ChatScrollContainer, {
  ChatScrollContainerHandle,
} from "@/sections/chat/ChatScrollContainer";
import { useScrollContainer } from "@/sections/chat/ScrollContainerContext";

interface SpacerProps {
  height: number;
}

function Spacer({ height }: SpacerProps) {
  const { spacerHeightRef } = useScrollContainer();
  useLayoutEffect(() => {
    spacerHeightRef.current = height;
  }, [height, spacerHeightRef]);
  return null;
}

const originalScrollTo = Object.getOwnPropertyDescriptor(
  HTMLElement.prototype,
  "scrollTo"
);
beforeEach(() => {
  Object.defineProperty(HTMLElement.prototype, "scrollTo", {
    configurable: true,
    writable: true,
    value: jest.fn(),
  });
});
afterEach(() => {
  if (originalScrollTo) {
    Object.defineProperty(HTMLElement.prototype, "scrollTo", originalScrollTo);
  } else {
    Reflect.deleteProperty(HTMLElement.prototype, "scrollTo");
  }
});

test("mounting with auto-scroll enabled does not start an unrelated scroll", () => {
  const view = render(<ChatScrollContainer>{null}</ChatScrollContainer>);
  expect(HTMLElement.prototype.scrollTo).not.toHaveBeenCalled();
  view.unmount();
});

describe.each([0, 200])("with spacer height %i", (spacerHeight) => {
  describe.each(["drain", "smooth", "both"])("%s pause", (pause) => {
    test.each([
      {
        scenario: "follows new content",
        autoScroll: true,
        scrollUp: false,
        follows: true,
        returnToBottom: false,
      },
      {
        scenario: "respects disabled auto-scroll",
        autoScroll: false,
        scrollUp: false,
        follows: false,
        returnToBottom: false,
      },
      {
        scenario: "respects a user scrolling up",
        autoScroll: true,
        scrollUp: true,
        follows: false,
        returnToBottom: false,
      },
      {
        scenario: "follows after the user returns to bottom",
        autoScroll: true,
        scrollUp: true,
        follows: true,
        returnToBottom: true,
      },
    ])(
      "$scenario after a following pause",
      async ({ autoScroll, scrollUp, follows, returnToBottom }) => {
        const frames: FrameRequestCallback[] = [];
        const requestFrame = jest
          .spyOn(window, "requestAnimationFrame")
          .mockImplementation((callback) => {
            frames.push(callback);
            return frames.length;
          });
        const message = (enabled: boolean) => (
          <ChatScrollContainer autoScroll={enabled}>
            <Spacer height={spacerHeight} />
          </ChatScrollContainer>
        );
        const view = render(message(pause === "smooth" ? autoScroll : false));
        const container = screen.getByTestId("chat-scroll-container");
        const end = container.firstElementChild?.lastElementChild;
        if (!(end instanceof HTMLElement))
          throw new Error("Missing content end marker");
        let contentHeight = 1000;
        Object.defineProperties(container, {
          clientHeight: { get: () => 400 },
          scrollHeight: { get: () => contentHeight },
        });
        Object.defineProperty(end, "offsetTop", { get: () => contentHeight });
        const scrollTo = jest.fn(
          (options?: ScrollToOptions | number, y?: number) => {
            const top = typeof options === "number" ? y : options?.top;
            if (top !== undefined) container.scrollTop = top;
          }
        );
        container.scrollTo = scrollTo;

        async function flushChanges(change: () => void) {
          await act(async () => {
            change();
            // Let the real MutationObserver deliver its records before the next frame.
            await Promise.resolve();
          });
          act(() => frames.splice(0).forEach((callback) => callback(0)));
        }

        try {
          container.scrollTop = 600;
          fireEvent.scroll(container);
          if (scrollUp) {
            container.scrollTop = 100;
            fireEvent.scroll(container);
          }

          if (returnToBottom) {
            container.scrollTop = 600;
            fireEvent.scroll(container);
          }

          if (pause !== "drain") {
            await flushChanges(() => {
              container.dataset.smoothScrollActive = "true";
            });
          }
          scrollTo.mockClear();
          await flushChanges(() => {
            // The answer footer appears while instant following is suppressed.
            contentHeight += 48;
            end.before(document.createElement("div"));
          });
          expect(scrollTo).not.toHaveBeenCalled();

          await flushChanges(() => {
            view.rerender(message(autoScroll));
          });
          if (pause !== "drain") {
            expect(scrollTo).not.toHaveBeenCalled();
            await flushChanges(() => {
              container.dataset.smoothScrollActive = "false";
            });
          }
          if (follows) {
            expect(scrollTo).toHaveBeenCalledWith({
              top: 648,
              behavior: "instant",
            });
            expect(container.scrollTop).toBe(648);
          } else {
            expect(scrollTo).not.toHaveBeenCalled();
            expect(container.scrollTop).toBe(scrollUp ? 100 : 600);
          }
        } finally {
          view.unmount();
          requestFrame.mockRestore();
        }
      }
    );
  });
});

test("an interrupted smooth scroll does not resume following later content", async () => {
  jest.useFakeTimers();
  const ref = createRef<ChatScrollContainerHandle>();
  const view = render(
    <ChatScrollContainer ref={ref}>{null}</ChatScrollContainer>
  );
  const container = screen.getByTestId("chat-scroll-container");
  const end = container.firstElementChild?.lastElementChild;
  if (!(end instanceof HTMLElement))
    throw new Error("Missing content end marker");
  let height = 1000;
  Object.defineProperties(container, {
    clientHeight: { get: () => 400 },
    scrollHeight: { get: () => height },
  });
  Object.defineProperty(end, "offsetTop", { get: () => height });
  const scrollTo = jest.fn();
  container.scrollTo = scrollTo;
  try {
    act(() => ref.current?.scrollToBottom("smooth"));
    container.scrollTop = 100;
    fireEvent.scroll(container);
    act(() => jest.advanceTimersByTime(600));
    scrollTo.mockClear();
    await act(async () => {
      height += 48;
      end.before(document.createElement("div"));
      await Promise.resolve();
    });
    act(() => jest.advanceTimersByTime(20));
    expect(scrollTo).not.toHaveBeenCalled();
    expect(container.scrollTop).toBe(100);
  } finally {
    view.unmount();
    jest.useRealTimers();
  }
});

test.each([
  // The browser clamps the scroll position to the shorter content.
  { case: "layout moves", scrollTopAfterShrink: 500, follows: true },
  // The user scrolls up farther than the content shrank.
  { case: "the user scrolls", scrollTopAfterShrink: 300, follows: false },
])(
  "when shrinking rows move the scroll position up and $case, following is $follows",
  async ({ scrollTopAfterShrink, follows }) => {
    // A reloaded chat: windowed rows settle to smaller heights, the scroll
    // position moves up, then the resumed run streams more content.
    const frames: FrameRequestCallback[] = [];
    const requestFrame = jest
      .spyOn(window, "requestAnimationFrame")
      .mockImplementation((callback) => {
        frames.push(callback);
        return frames.length;
      });
    const view = render(
      <ChatScrollContainer autoScroll>
        <Spacer height={0} />
      </ChatScrollContainer>
    );
    const container = screen.getByTestId("chat-scroll-container");
    const end = container.firstElementChild?.lastElementChild;
    if (!(end instanceof HTMLElement))
      throw new Error("Missing content end marker");
    let contentHeight = 1000;
    Object.defineProperties(container, {
      clientHeight: { get: () => 400 },
      scrollHeight: { get: () => contentHeight },
    });
    Object.defineProperty(end, "offsetTop", { get: () => contentHeight });
    const scrollTo = jest.fn((options?: ScrollToOptions | number) => {
      if (typeof options === "object" && options.top !== undefined)
        container.scrollTop = options.top;
    });
    container.scrollTo = scrollTo;
    try {
      container.scrollTop = 600;
      fireEvent.scroll(container);

      contentHeight = 900;
      container.scrollTop = scrollTopAfterShrink;
      fireEvent.scroll(container);

      scrollTo.mockClear();
      await act(async () => {
        contentHeight += 150;
        end.before(document.createElement("div"));
        await Promise.resolve();
      });
      act(() => frames.splice(0).forEach((callback) => callback(0)));

      if (follows) {
        expect(scrollTo).toHaveBeenCalledWith({
          top: 650,
          behavior: "instant",
        });
        expect(container.scrollTop).toBe(650);
      } else {
        expect(scrollTo).not.toHaveBeenCalled();
        expect(container.scrollTop).toBe(scrollTopAfterShrink);
      }
    } finally {
      view.unmount();
      requestFrame.mockRestore();
    }
  }
);
