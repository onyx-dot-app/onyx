import { render, screen, setupUser } from "@tests/setup/test-utils";
import HumanMessage from "@/app/app/message/HumanMessage";

test("an edit keeps the recorded mentions its text still has", async () => {
  const onEdit = jest.fn();
  render(
    <HumanMessage
      content="@code-review and @pdf this"
      mentions={[
        { type: "skill", name: "code-review" },
        { type: "skill", name: "pdf" },
      ]}
      nodeId={1}
      messageId={7}
      onEdit={onEdit}
    />
  );
  expect(screen.getAllByTestId("mention-chip")).toHaveLength(2);

  const user = setupUser();
  await user.click(screen.getByTestId("HumanMessage/edit-button"));
  const editor = screen.getByRole("textbox");
  await user.clear(editor);
  // The edit has no `@` menu, so new mention text picks nothing.
  await user.type(editor, "@code-review this with @triage");
  await user.click(screen.getByRole("button", { name: "Submit" }));

  expect(onEdit).toHaveBeenCalledWith(
    {
      message: "@code-review this with @triage",
      mentions: [{ type: "skill", name: "code-review" }],
    },
    7
  );
});
