import { render, screen, setupUser } from "@tests/setup/test-utils";
import HumanMessage from "@/lib/timeline/chat/message/HumanMessage";
import { ChatFileType } from "@/app/app/types";

test("edit hands the message, its mentions and its files to the composer", async () => {
  const onEdit = jest.fn();
  const files = [
    { id: "store-1", type: ChatFileType.PLAIN_TEXT, name: "notes.txt" },
  ];
  const mentions = [{ type: "skill" as const, name: "code-review" }];
  render(
    <HumanMessage
      content="@code-review this"
      mentions={mentions}
      files={files}
      nodeId={1}
      messageId={7}
      onEdit={onEdit}
    />
  );

  await setupUser().click(screen.getByTestId("HumanMessage/edit-button"));

  expect(onEdit).toHaveBeenCalledWith({
    messageId: 7,
    message: "@code-review this",
    mentions,
    files,
  });
  expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
});
