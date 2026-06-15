import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { TooltipProvider } from "@radix-ui/react-tooltip";
import BuildMessageList from "@/app/craft/components/BuildMessageList";
import type { BuildMessage } from "@/app/craft/types/streamingTypes";
import type { StreamItem } from "@/app/craft/types/displayTypes";

jest.mock("@/refresh-components/Logo", () => ({
  __esModule: true,
  default: () => <div data-testid="onyx-logo" />,
}));

jest.mock("@/components/chat/MinimalMarkdown", () => ({
  __esModule: true,
  default: ({ content }: { content: string }) => <div>{content}</div>,
}));

jest.mock("@/app/app/message/BlinkingBar", () => ({
  BlinkingBar: () => <span data-testid="blinking-bar" />,
}));

jest.mock("motion/react", () => ({
  AnimatePresence: ({ children }: { children: React.ReactNode }) => (
    <>{children}</>
  ),
  motion: {
    div: ({
      children,
      initial: _initial,
      animate: _animate,
      exit: _exit,
      transition: _transition,
      ...props
    }: React.HTMLAttributes<HTMLDivElement> & {
      initial?: unknown;
      animate?: unknown;
      exit?: unknown;
      transition?: unknown;
    }) => <div {...props}>{children}</div>,
  },
}));

function scrollRef() {
  const el = document.createElement("div");
  el.scrollTo = jest.fn();
  return { current: el };
}

function renderList(props: {
  messages?: BuildMessage[];
  streamItems?: StreamItem[];
  isStreaming?: boolean;
}) {
  return render(
    <TooltipProvider>
      <BuildMessageList
        messages={props.messages ?? []}
        streamItems={props.streamItems ?? []}
        isStreaming={props.isStreaming}
        autoScrollEnabled={false}
        scrollContainerRef={scrollRef()}
      />
    </TooltipProvider>
  );
}

const savedAssistantMessage: BuildMessage = {
  id: "assistant-1",
  type: "assistant",
  content: "Final answer",
  timestamp: new Date("2026-01-01T00:00:00Z"),
  message_metadata: {
    streamItems: [
      {
        type: "thinking",
        id: "thought-1",
        content: "Checking the app structure.",
        isStreaming: false,
      },
      {
        type: "text",
        id: "text-1",
        content: "Final answer",
        isStreaming: false,
      },
    ],
  },
};

describe("BuildMessageList thinking visibility", () => {
  it("shows restored thought packets as collapsed thinking rows", () => {
    renderList({ messages: [savedAssistantMessage] });

    fireEvent.click(screen.getByRole("button", { name: /Thinking/ }));

    expect(screen.getByText("Thinking")).toBeInTheDocument();
    expect(screen.getByText("Checking the app structure.")).toBeInTheDocument();
    expect(screen.getByText("Final answer")).toBeInTheDocument();
  });

  it("does not open restored thought packets by default", () => {
    renderList({ messages: [savedAssistantMessage] });

    expect(screen.getByText("Thinking")).toBeInTheDocument();
    expect(
      screen.queryByText("Checking the app structure.")
    ).not.toBeInTheDocument();
    expect(screen.getByText("Final answer")).toBeInTheDocument();
  });

  it("keeps completed thought packets collapsed in the active stream", () => {
    renderList({
      isStreaming: true,
      streamItems: [
        {
          type: "thinking",
          id: "settled-thought",
          content: "Checking the app structure.",
          isStreaming: false,
        },
        {
          type: "text",
          id: "stream-text",
          content: "Final answer",
          isStreaming: false,
        },
      ],
    });

    expect(screen.getByText("Thinking")).toBeInTheDocument();
    expect(
      screen.queryByText("Checking the app structure.")
    ).not.toBeInTheDocument();
    expect(screen.getByText("Final answer")).toBeInTheDocument();
  });

  it("shows live thought packets as collapsed progress by default", () => {
    renderList({
      isStreaming: true,
      streamItems: [
        {
          type: "thinking",
          id: "live-thought",
          content: "Checking the app structure.",
          isStreaming: true,
        },
      ],
    });

    expect(screen.getByText("Thinking...")).toBeInTheDocument();
    expect(
      screen.queryByText("Checking the app structure.")
    ).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Thinking/ }));

    expect(screen.getByText("Checking the app structure.")).toBeInTheDocument();
  });

  it("shows stream error packets inline", () => {
    renderList({
      streamItems: [
        {
          type: "error",
          id: "error-1",
          content: "provider model not found",
        },
      ],
    });

    expect(screen.getByRole("alert")).toHaveTextContent(
      "provider model not found"
    );
  });
});
