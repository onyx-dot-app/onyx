import { beforeEach, describe, expect, it, jest } from "@jest/globals";
import { act, fireEvent, render, screen } from "@testing-library/react-native";
import { ScrollView } from "react-native";

import {
  REASONING_WINDOW_MAX_HEIGHT,
  ReasoningTextWindow,
} from "@/components/chat/timeline/ReasoningTextWindow";

// StreamingMarkdown wraps a native markdown module; capture its props instead of rendering it.
let mockMarkdownProps: {
  content: string;
  isStreaming: boolean;
  variant?: string;
} | null = null;
jest.mock("@/components/chat/StreamingMarkdown", () => ({
  StreamingMarkdown: (props: {
    content: string;
    isStreaming: boolean;
    variant?: string;
  }) => {
    mockMarkdownProps = props;
    return null;
  },
}));

// The "View full text" Button navigates via expo-router's `router`.
jest.mock("expo-router", () => ({ router: { navigate: jest.fn() } }));

const DISPLAYED = "the body";

function renderWindow(isStreaming = false, onExpand?: () => void) {
  return render(
    <ReasoningTextWindow
      displayContent={DISPLAYED}
      isStreaming={isStreaming}
      onExpand={onExpand}
    />,
  );
}

function windowScroll() {
  return screen.UNSAFE_getAllByType(ScrollView)[0]!;
}

function growContentTo(height: number) {
  act(() => {
    windowScroll().props.onContentSizeChange(320, height);
  });
}

describe("ReasoningTextWindow", () => {
  beforeEach(() => {
    mockMarkdownProps = null;
  });

  it("caps the window at the fixed height", () => {
    renderWindow();
    expect(windowScroll().props.style).toEqual(
      expect.objectContaining({ maxHeight: REASONING_WINDOW_MAX_HEIGHT }),
    );
  });

  it("shows the heading-stripped body in the muted variant", () => {
    renderWindow(true);
    expect(mockMarkdownProps?.content).toBe(DISPLAYED);
    expect(mockMarkdownProps?.variant).toBe("muted");
    expect(mockMarkdownProps?.isStreaming).toBe(true);
  });

  describe("auto-follow", () => {
    it("scrolls to the newest lines while streaming", () => {
      renderWindow(true);
      const scroll = windowScroll();
      const scrollToEnd = jest.fn();
      // The ref target is the same instance the component holds.
      scroll.instance.scrollToEnd = scrollToEnd;
      growContentTo(500);
      expect(scrollToEnd).toHaveBeenCalledWith({ animated: false });
    });

    it("does not yank the view once the stream has ended", () => {
      renderWindow(false);
      const scroll = windowScroll();
      const scrollToEnd = jest.fn();
      scroll.instance.scrollToEnd = scrollToEnd;
      growContentTo(500);
      expect(scrollToEnd).not.toHaveBeenCalled();
    });

    it("locks user scrolling while streaming and unlocks after, once content overflows", () => {
      renderWindow(true);
      growContentTo(500);
      expect(windowScroll().props.scrollEnabled).toBe(false);

      renderWindow(false);
      growContentTo(500);
      expect(windowScroll().props.scrollEnabled).toBe(true);
    });

    // An enabled ScrollView wins the pan on iOS even with nothing to scroll, so a short finished
    // step would become a band where the conversation refuses to scroll.
    it("stays inert when the finished reasoning fits in the window", () => {
      renderWindow(false);
      growContentTo(REASONING_WINDOW_MAX_HEIGHT - 1);
      expect(windowScroll().props.scrollEnabled).toBe(false);
      expect(windowScroll().props.alwaysBounceVertical).toBe(false);
    });
  });

  describe("handing off to the full-text reader", () => {
    it("offers the affordance only once the reasoning overflows", () => {
      renderWindow(false, jest.fn());
      expect(screen.queryByText("View full text")).toBeNull();
      growContentTo(REASONING_WINDOW_MAX_HEIGHT + 1);
      expect(screen.getByText("View full text")).toBeTruthy();
    });

    // The window hands up only a request. It never sees the full text, so it cannot hand up a
    // snapshot that would freeze while the step keeps streaming.
    it("asks the row to open the reader, carrying no text of its own", () => {
      const onExpand = jest.fn();
      renderWindow(false, onExpand);
      growContentTo(500);
      fireEvent.press(screen.getByText("View full text"));
      expect(onExpand).toHaveBeenCalledTimes(1);
      expect(onExpand).toHaveBeenCalledWith();
    });

    // The reader lives above the timeline, so a step that has no way to reach it must not offer one.
    it("hides the affordance when no reader is wired up", () => {
      renderWindow(false);
      growContentTo(500);
      expect(screen.queryByText("View full text")).toBeNull();
    });

    // The window never mounts a Modal itself; auto-collapse would destroy it mid-read.
    it("renders no sheet of its own", () => {
      renderWindow(false, jest.fn());
      growContentTo(500);
      expect(screen.queryByText("Full text")).toBeNull();
      expect(screen.queryByText("Copy")).toBeNull();
    });
  });
});
