import { useState } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Disabled } from "@opal/core/disabled/components";

it("disables the form controls inside, so the keyboard cannot reach them", async () => {
  const user = userEvent.setup();
  render(
    <Disabled disabled>
      <input aria-label="name" />
      <button>Save</button>
    </Disabled>
  );

  expect(screen.getByRole("textbox", { name: "name" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
  await user.tab();
  expect(document.body).toHaveFocus();
});

it("keeps the controls usable with allowClick", () => {
  render(
    <Disabled disabled allowClick>
      <input aria-label="name" />
    </Disabled>
  );

  expect(screen.getByRole("textbox", { name: "name" })).toBeEnabled();
});

it("keeps a control's state when it toggles between enabled and disabled", async () => {
  const user = userEvent.setup();
  function Harness() {
    const [locked, setLocked] = useState(false);
    return (
      <>
        <button onClick={() => setLocked((value) => !value)}>toggle</button>
        <Disabled disabled={locked}>
          <input aria-label="name" />
        </Disabled>
      </>
    );
  }
  render(<Harness />);

  const input = screen.getByRole("textbox", { name: "name" });
  await user.type(input, "kept");
  await user.click(screen.getByRole("button", { name: "toggle" }));
  await user.click(screen.getByRole("button", { name: "toggle" }));

  expect(screen.getByRole("textbox", { name: "name" })).toBe(input);
  expect(input).toHaveValue("kept");
});
