import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { Collapsible } from "@opal/components/collapsible/components";

function Parts({
  defaultOpen,
  disabled,
  asChild = false,
}: {
  defaultOpen?: boolean;
  disabled?: boolean;
  asChild?: boolean;
}) {
  return (
    <Collapsible.Root defaultOpen={defaultOpen} disabled={disabled}>
      {asChild ? (
        <Collapsible.Trigger asChild>
          <div role="button" tabIndex={0}>
            Toggle
          </div>
        </Collapsible.Trigger>
      ) : (
        <Collapsible.Trigger>Toggle</Collapsible.Trigger>
      )}
      <Collapsible.Content>Body</Collapsible.Content>
    </Collapsible.Root>
  );
}

function Controlled() {
  const [open, setOpen] = useState(false);
  return (
    <>
      <span>{open ? "parent open" : "parent closed"}</span>
      <Collapsible.Root open={open} onOpenChange={setOpen}>
        <Collapsible.Trigger>Toggle</Collapsible.Trigger>
        <Collapsible.Content>Body</Collapsible.Content>
      </Collapsible.Root>
    </>
  );
}

describe("Collapsible parts", () => {
  it("starts closed and toggles on its own", async () => {
    const user = userEvent.setup();
    render(<Parts />);
    const trigger = screen.getByRole("button", { name: "Toggle" });

    expect(trigger).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText("Body")).not.toBeInTheDocument();

    await user.click(trigger);
    expect(trigger).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("Body")).toBeInTheDocument();

    await user.click(trigger);
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    // The body animates closed, then drops its content.
    await waitFor(() =>
      expect(screen.queryByText("Body")).not.toBeInTheDocument()
    );
  });

  it("starts open with defaultOpen", () => {
    render(<Parts defaultOpen />);
    expect(screen.getByRole("button", { name: "Toggle" })).toHaveAttribute(
      "aria-expanded",
      "true"
    );
    expect(screen.getByText("Body")).toBeInTheDocument();
  });

  it("reports changes when controlled", async () => {
    const user = userEvent.setup();
    render(<Controlled />);

    await user.click(screen.getByRole("button", { name: "Toggle" }));
    expect(screen.getByText("parent open")).toBeInTheDocument();
    expect(screen.getByText("Body")).toBeInTheDocument();
  });

  it("points the trigger at the content", () => {
    render(<Parts defaultOpen />);
    const trigger = screen.getByRole("button", { name: "Toggle" });
    const contentId = trigger.getAttribute("aria-controls");
    expect(contentId).toBeTruthy();
    expect(document.getElementById(contentId ?? "")).toContainElement(
      screen.getByText("Body")
    );
  });

  it("disables a native trigger when the root is disabled", async () => {
    const user = userEvent.setup();
    render(<Parts disabled />);
    const trigger = screen.getByRole("button", { name: "Toggle" });

    expect(trigger).toBeDisabled();
    await user.click(trigger);
    expect(trigger).toHaveAttribute("aria-expanded", "false");
  });

  it("toggles through an asChild element, and marks it disabled", async () => {
    const user = userEvent.setup();
    const { unmount } = render(<Parts asChild />);
    const trigger = screen.getByRole("button", { name: "Toggle" });

    expect(trigger.tagName).toBe("DIV");
    await user.click(trigger);
    expect(trigger).toHaveAttribute("aria-expanded", "true");
    unmount();

    render(<Parts asChild disabled />);
    const disabledTrigger = screen.getByRole("button", { name: "Toggle" });
    expect(disabledTrigger).toHaveAttribute("aria-disabled", "true");
    await user.click(disabledTrigger);
    expect(disabledTrigger).toHaveAttribute("aria-expanded", "false");
  });

  it("runs no click handler on a disabled asChild trigger", async () => {
    const user = userEvent.setup();
    const onTriggerClick = jest.fn();
    const onChildClick = jest.fn();
    render(
      <Collapsible.Root disabled>
        <Collapsible.Trigger asChild onClick={onTriggerClick}>
          <button type="button" onClick={onChildClick}>
            Toggle
          </button>
        </Collapsible.Trigger>
        <Collapsible.Content>Body</Collapsible.Content>
      </Collapsible.Root>
    );

    await user.click(screen.getByRole("button", { name: "Toggle" }));
    expect(onTriggerClick).not.toHaveBeenCalled();
    expect(onChildClick).not.toHaveBeenCalled();
    expect(screen.queryByText("Body")).not.toBeInTheDocument();
  });
});
