import { useRef, type MutableRefObject } from "react";
import { act, render, waitFor } from "@tests/setup/test-utils";
import DynamicBottomSpacer from "@/components/chat/DynamicBottomSpacer";
import { ScrollContainerProvider } from "@/sections/chat/ScrollContainerContext";
import { useChatSessionStore } from "@/app/app/stores/useChatSessionStore";
import type { ChatState } from "@/app/app/types";

const ANCHOR_NODE_ID = 2;

/** A scrolled chat whose latest user message sits near the end of the history. */
function Chat({
  spacerHeightRef,
  showSpacer = true,
}: {
  spacerHeightRef: MutableRefObject<number>;
  showSpacer?: boolean;
}) {
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const contentWrapperRef = useRef<HTMLDivElement>(null);
  return (
    <div
      ref={(element) => {
        scrollContainerRef.current = element;
        if (!element) return;
        Object.defineProperty(element, "clientHeight", { value: 600 });
        Object.defineProperty(element, "scrollHeight", { value: 1000 });
        element.scrollTo = jest.fn();
      }}
    >
      <div ref={contentWrapperRef}>
        <ScrollContainerProvider
          scrollContainerRef={scrollContainerRef}
          contentWrapperRef={contentWrapperRef}
          spacerHeightRef={spacerHeightRef}
        >
          <div
            id={`message-${ANCHOR_NODE_ID}`}
            ref={(element) => {
              if (element)
                element.getBoundingClientRect = () => ({ top: 900 }) as DOMRect;
            }}
          />
          {showSpacer && <DynamicBottomSpacer anchorNodeId={ANCHOR_NODE_ID} />}
        </ScrollContainerProvider>
      </div>
    </div>
  );
}

function setChatState(chatState: ChatState) {
  act(() =>
    useChatSessionStore.getState().updateChatState("session", chatState)
  );
}

function spacerHeight(container: HTMLElement): string | undefined {
  return container.querySelector<HTMLElement>("[data-dynamic-spacer]")?.style
    .height;
}

beforeEach(() => {
  useChatSessionStore.setState({ sessions: new Map(), currentSessionId: null });
  useChatSessionStore.getState().createSession("session");
  useChatSessionStore.getState().setCurrentSession("session");
});

test("a run the page resumes does not push the history up", async () => {
  // A reload of a chat whose answer is still streaming.
  setChatState("streaming");
  const { container } = render(<Chat spacerHeightRef={{ current: 0 }} />);

  // Two frames: the effect and the spacer's own layout pass.
  await act(
    () => new Promise((resolve) => requestAnimationFrame(() => resolve(null)))
  );
  await act(
    () => new Promise((resolve) => requestAnimationFrame(() => resolve(null)))
  );

  expect(spacerHeight(container) ?? "").toMatch(/^(0px)?$/);
});

test("a message sent from the page pushes the history up", async () => {
  const { container } = render(<Chat spacerHeightRef={{ current: 0 }} />);

  setChatState("loading");
  setChatState("streaming");

  await waitFor(() => expect(spacerHeight(container)).toBe("484px"));
});

test("removing the spacer clears the height the scroll container reads", async () => {
  // A chat switch remounts the spacer while the scroll container stays.
  const spacerHeightRef = { current: 0 };
  const { container, rerender } = render(
    <Chat spacerHeightRef={spacerHeightRef} />
  );
  setChatState("loading");
  setChatState("streaming");
  await waitFor(() => expect(spacerHeight(container)).toBe("484px"));
  expect(spacerHeightRef.current).toBe(484);

  rerender(<Chat spacerHeightRef={spacerHeightRef} showSpacer={false} />);

  expect(spacerHeightRef.current).toBe(0);
});
