import React from "react";
import { fireEvent, screen, within } from "@testing-library/react";
import { render } from "@tests/setup/test-utils";
import { TooltipProvider } from "@radix-ui/react-tooltip";
import BuildMessageList from "@/app/craft/components/BuildMessageList";
import type {
  BuildMessage,
  OutputCard,
} from "@/app/craft/types/streamingTypes";
import type { StreamItem } from "@/app/craft/types/displayTypes";

jest.mock("@/lib/app/components", () => ({
  FoldableLogo: () => <div data-testid="onyx-logo" />,
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
        sessionId="session-1"
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

// Output ownership follows settled turns, independently of assistant prose.
test("renders a settled output-only turn but never places its cards before a live response", () => {
  const message: BuildMessage = {
    id: "user",
    type: "user",
    content: "Make a report",
    timestamp: new Date(),
    turn_index: 0,
  };
  const output: OutputCard = {
    id: "report",
    kind: "file",
    path: "outputs/report.md",
    name: "report.md",
    turn_index: 0,
    revision: 1,
    size_bytes: 12,
    deleted: false,
    viewed_revision: null,
  };
  const props = {
    sessionId: "session-1",
    messages: [message],
    streamItems: [],
    outputCards: [output],
    onOutputOpen: jest.fn(),
    onTurnOutputsOpen: jest.fn(),
    scrollContainerRef: scrollRef(),
    autoScrollEnabled: false,
  };
  const { rerender } = render(<BuildMessageList {...props} isStreaming />);
  expect(
    screen.queryByRole("button", { name: output.name })
  ).not.toBeInTheDocument();
  rerender(<BuildMessageList {...props} isStreaming={false} />);
  expect(screen.getByRole("button", { name: output.name })).toBeInTheDocument();
  expect(screen.getByText(message.content)).toBeInTheDocument();
});

test("moves a file card to its latest persisted turn and retains an output-only turn", () => {
  const messages: BuildMessage[] = [
    { ...savedAssistantMessage, turn_index: 0 },
    {
      id: "assistant-2",
      type: "assistant",
      content: "",
      timestamp: new Date(),
      turn_index: 1,
    },
  ];
  const output: OutputCard = {
    id: "report",
    kind: "file",
    path: "outputs/report.md",
    name: "report.md",
    turn_index: 0,
    revision: 1,
    size_bytes: 12,
    deleted: false,
    viewed_revision: null,
  };
  const onOutputOpen = jest.fn();
  const props = {
    sessionId: "session-1",
    messages,
    streamItems: [],
    autoScrollEnabled: false,
    scrollContainerRef: scrollRef(),
    onOutputOpen,
    onTurnOutputsOpen: jest.fn(),
  };
  const { rerender } = render(
    <BuildMessageList {...props} outputCards={[output]} />
  );
  expect(
    within(screen.getByTestId("craft-turn-outputs-0")).getByRole("button", {
      name: output.name,
    })
  ).toBeInTheDocument();
  rerender(
    <BuildMessageList
      {...props}
      outputCards={[{ ...output, turn_index: 1, revision: 2 }]}
    />
  );
  expect(screen.queryByTestId("craft-turn-outputs-0")).not.toBeInTheDocument();
  fireEvent.click(
    within(screen.getByTestId("craft-turn-outputs-1")).getByRole("button", {
      name: output.name,
    })
  );
  expect(onOutputOpen).toHaveBeenCalledWith({
    ...output,
    turn_index: 1,
    revision: 2,
  });
  expect(screen.getByText("Final answer")).toBeInTheDocument();
});

describe("BuildMessageList thinking visibility", () => {
  it("renders image attachments on user messages", () => {
    renderList({
      messages: [
        {
          id: "user-1",
          type: "user",
          content: "Use this image",
          timestamp: new Date("2026-01-01T00:00:00Z"),
          attachments: [
            {
              name: "reference image.png",
              path: "attachments/reference image.png",
              mimeType: "image/png",
            },
          ],
        },
      ],
    });

    expect(
      screen.getByRole("img", { name: "reference image.png" })
    ).toHaveAttribute(
      "src",
      "/api/build/sessions/session-1/artifacts/attachments/reference%20image.png"
    );
  });

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
