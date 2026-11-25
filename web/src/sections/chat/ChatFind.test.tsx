import type { Message } from "@/app/app/types";
import { render, screen, setupUser, waitFor } from "@tests/setup/test-utils";
import ChatScrollContainer from "@/lib/chatScroll/components/ChatScrollContainer";
import ChatFind from "@/sections/chat/ChatFind";

function message(fields: Partial<Message> & Pick<Message, "nodeId">): Message {
  return {
    message: "",
    type: "user",
    files: [],
    toolCall: null,
    parentNodeId: null,
    packets: [],
    ...fields,
  };
}

const mockMessages: Message[] = [
  message({ nodeId: 1, message: "Where is the foo?" }),
  message({
    nodeId: 2,
    type: "assistant",
    parentNodeId: 1,
    packets: [
      {
        placement: { turn_index: 0 },
        obj: {
          type: "message_start",
          id: "m",
          content: "The foo is next to **Foo**.",
          final_documents: null,
        },
      },
    ],
  }),
];

jest.mock("@/app/app/stores/useChatSessionStore", () => ({
  useCurrentMessageHistory: () => mockMessages,
  useCurrentMessageTree: () => null,
}));

test("Ctrl+F finds text in the whole chat and Enter steps to the next match", async () => {
  const user = setupUser();
  render(
    <ChatScrollContainer sessionId="chat-1" overlay={<ChatFind />}>
      <div />
    </ChatScrollContainer>
  );

  expect(screen.queryByRole("search")).not.toBeInTheDocument();
  await user.keyboard("{Control>}f{/Control}");

  const input = screen.getByRole("textbox", { name: "Find in session" });
  expect(input).toHaveFocus();

  await user.type(input, "foo");
  await waitFor(() => expect(screen.getByText("1 of 3")).toBeInTheDocument());

  await user.keyboard("{Enter}");
  expect(screen.getByText("2 of 3")).toBeInTheDocument();
  await user.keyboard("{Shift>}{Enter}{/Shift}");
  expect(screen.getByText("1 of 3")).toBeInTheDocument();

  await user.keyboard("{Escape}");
  expect(screen.queryByRole("search")).not.toBeInTheDocument();
});
