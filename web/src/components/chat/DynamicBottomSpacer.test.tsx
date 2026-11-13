import { useRef } from "react";
import { act, render, waitFor } from "@tests/setup/test-utils";
import DynamicBottomSpacer from "@/components/chat/DynamicBottomSpacer";
import { ScrollContainerProvider } from "@/sections/chat/ScrollContainerContext";
import { useChatSessionStore } from "@/app/app/stores/useChatSessionStore";
import type { ChatState } from "@/app/app/types";

const ANCHOR_NODE_ID = 2;

/** A scrolled chat whose latest user message sits near the end of the history. */
function Chat({ anchorNodeId }: { anchorNodeId: number | undefined }) {
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const contentWrapperRef = useRef<HTMLDivElement>(null);
  const spacerHeightRef = useRef(0);
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
          <DynamicBottomSpacer anchorNodeId={anchorNodeId} />
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

/** Wait two frames: the effect and the spacer's own layout pass. */
async function settleFrames() {
  for (let frame = 0; frame < 2; frame++)
    await act(
      () => new Promise((resolve) => requestAnimationFrame(() => resolve(null)))
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
  const { container } = render(<Chat anchorNodeId={ANCHOR_NODE_ID} />);

  await settleFrames();

  expect(spacerHeight(container) ?? "").toMatch(/^(0px)?$/);
});

test("a message sent from the page pushes the history up", async () => {
  const { container } = render(<Chat anchorNodeId={ANCHOR_NODE_ID} />);

  setChatState("loading");
  setChatState("streaming");

  await waitFor(() => expect(spacerHeight(container)).toBe("484px"));
});

test("a send in one chat does not push up another chat the page opens mid-run", async () => {
  const { container, rerender } = render(<Chat anchorNodeId={undefined} />);
  setChatState("loading");

  act(() => {
    useChatSessionStore.getState().createSession("other");
    useChatSessionStore.getState().updateChatState("other", "streaming");
    useChatSessionStore.getState().setCurrentSession("other");
  });
  rerender(<Chat anchorNodeId={ANCHOR_NODE_ID} />);
  await settleFrames();

  expect(spacerHeight(container) ?? "").toMatch(/^(0px)?$/);
});
