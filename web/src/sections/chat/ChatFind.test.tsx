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

let mockHasOlderMessages = false;
jest.mock("@/app/app/stores/useChatSessionStore", () => ({
  useCurrentMessageHistory: () => mockMessages,
  useCurrentMessageTree: () => null,
  useHasOlderMessages: () => mockHasOlderMessages,
}));

const mockLoadOlderPages = jest.fn<Promise<boolean>, [string]>();
jest.mock("@/lib/chatFind/olderPages", () => ({
  loadOlderPagesForFind: (sessionId: string) => mockLoadOlderPages(sessionId),
}));

afterEach(() => {
  mockHasOlderMessages = false;
  mockLoadOlderPages.mockReset();
});

test("a search in a chat with older pages loads them first", async () => {
  mockHasOlderMessages = true;
  let finish: (capped: boolean) => void = () => {};
  mockLoadOlderPages.mockReturnValue(
    new Promise((resolve) => {
      finish = resolve;
    })
  );
  const user = setupUser();
  render(
    <ChatScrollContainer sessionId="chat-1" overlay={<ChatFind />}>
      <div />
    </ChatScrollContainer>
  );

  await user.keyboard("{Control>}f{/Control}");
  await user.type(
    screen.getByRole("textbox", { name: "Find in session" }),
    "foo"
  );
  await waitFor(() =>
    expect(screen.getByText("Loading older messages…")).toBeInTheDocument()
  );
  expect(mockLoadOlderPages).toHaveBeenCalledTimes(1);
  expect(mockLoadOlderPages).toHaveBeenCalledWith("chat-1");

  finish(true);
  expect(await screen.findByText("1 of 3")).toBeInTheDocument();
  expect(screen.getByText("Searched the last 2 messages")).toBeInTheDocument();
});

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
