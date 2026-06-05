import React from "react";
import { render, screen } from "@testing-library/react";
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

function scrollRef() {
  const el = document.createElement("div");
  el.scrollTo = jest.fn();
  return { current: el };
}

function renderList(props: {
  messages?: BuildMessage[];
  streamItems?: StreamItem[];
  isStreaming?: boolean;
  showThinkingDetails?: boolean;
}) {
  return render(
    <BuildMessageList
      messages={props.messages ?? []}
      streamItems={props.streamItems ?? []}
      isStreaming={props.isStreaming}
      showThinkingDetails={props.showThinkingDetails}
      autoScrollEnabled={false}
      scrollContainerRef={scrollRef()}
    />
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
  it("hides completed thought packets by default", () => {
    renderList({ messages: [savedAssistantMessage] });

    expect(screen.queryByText("Thought")).not.toBeInTheDocument();
    expect(screen.getByText("Final answer")).toBeInTheDocument();
  });

  it("shows completed thought packets when thought details are enabled", () => {
    renderList({
      messages: [savedAssistantMessage],
      showThinkingDetails: true,
    });

    expect(screen.getByText("Thought")).toBeInTheDocument();
    expect(screen.getByText("Final answer")).toBeInTheDocument();
  });

  it("always shows live thought packets as progress", () => {
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

    expect(screen.getByText("Thinking")).toBeInTheDocument();
  });
});
