import { describe, expect, it, jest } from "@jest/globals";
import { render, screen } from "@testing-library/react-native";

import { makePacket } from "@/chat/__tests__/fixtures";
import type { Message } from "@/chat/interfaces";
import { MessageRow } from "@/components/chat/MessageRow";

// These reach native modules that jest cannot load. StreamingMarkdown renders its text instead.
jest.mock("@/state/storage");
jest.mock("@/components/chat/StreamingMarkdown", () => {
  const { Text } = jest.requireActual<typeof import("@/components/ui/text")>(
    "@/components/ui/text",
  );
  return {
    StreamingMarkdown: ({ content }: { content: string }) => (
      <Text>{content}</Text>
    ),
  };
});
jest.mock("expo-router", () => ({ router: { navigate: jest.fn() } }));
jest.mock("@/components/avatars/AgentAvatar", () => ({
  AgentAvatar: () => null,
}));

describe("MessageRow", () => {
  it("renders nothing for an automatic follow-up's hidden question", () => {
    const node: Message = {
      nodeId: 3,
      messageId: 3,
      message: "Subagent results",
      type: "agent_results",
      files: [],
      parentNodeId: 2,
      childrenNodeIds: [4],
      latestChildNodeId: 4,
      packets: [],
    };

    const view = render(<MessageRow node={node} agent={null} />);

    expect(view.toJSON()).toBeNull();
  });

  it("renders a replaced packet list of the same length", () => {
    const files: Message["files"] = [];
    const answer = (content: string): Message => ({
      nodeId: 2,
      messageId: 2,
      message: "",
      type: "assistant",
      files,
      parentNodeId: 1,
      childrenNodeIds: [],
      latestChildNodeId: null,
      packets: [
        makePacket({ type: "message_start", id: "m", content }),
        makePacket({ type: "stop" }),
      ],
    });

    const view = render(<MessageRow node={answer("Partial")} agent={null} />);
    expect(screen.getByText("Partial")).toBeTruthy();

    view.rerender(<MessageRow node={answer("Replayed answer")} agent={null} />);

    expect(screen.getByText("Replayed answer")).toBeTruthy();
  });
});
