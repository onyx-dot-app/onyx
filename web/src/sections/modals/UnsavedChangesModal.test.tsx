import { useState } from "react";
import { Button } from "@opal/components";
import { render, screen, setupUser, waitFor } from "@tests/setup/test-utils";
import UnsavedChangesModal from "@/sections/modals/UnsavedChangesModal";

describe("UnsavedChangesModal", () => {
  it("returns keyboard focus to the opening control after Escape", async () => {
    function Example() {
      const [open, setOpen] = useState(false);
      return (
        <>
          <Button onClick={() => setOpen(true)}>Leave editor</Button>
          <UnsavedChangesModal
            open={open}
            onCancel={() => setOpen(false)}
            onDiscard={() => setOpen(false)}
          />
        </>
      );
    }
    const user = setupUser();
    render(<Example />);
    const trigger = screen.getByRole("button", { name: "Leave editor" });
    trigger.focus();
    await user.keyboard("{Enter}");
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    await user.keyboard("{Escape}");
    await waitFor(() => expect(trigger).toHaveFocus());
  });

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
