import { render, screen, setupUser } from "@tests/setup/test-utils";
import UnsavedChangesModal from "@/sections/modals/UnsavedChangesModal";

describe("UnsavedChangesModal", () => {
  it("reports a single cancellation when the close button is clicked", async () => {
    const user = setupUser();
    const onCancel = jest.fn();

    render(
      <UnsavedChangesModal open onCancel={onCancel} onDiscard={jest.fn()} />
    );
    await user.click(screen.getByRole("button", { name: "Close" }));

    expect(onCancel).toHaveBeenCalledTimes(1);
  });
});
