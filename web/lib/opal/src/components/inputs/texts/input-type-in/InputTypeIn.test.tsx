import { useState } from "react";
import { render, screen, setupUser } from "@tests/setup/test-utils";
import { InputTypeIn } from "@opal/components";

function ClearableField() {
  const [value, setValue] = useState("query");
  return (
    <InputTypeIn
      clearButton
      aria-label="Search"
      value={value}
      onChange={(event) => setValue(event.target.value)}
    />
  );
}

it("clears from the keyboard and keeps focus in the field", async () => {
  const user = setupUser();
  render(<ClearableField />);
  const field = screen.getByRole("textbox", { name: "Search" });
  await user.click(field);
  await user.tab();
  expect(screen.getByRole("button", { name: "Clear" })).toHaveFocus();
  await user.keyboard("{Enter}");
  expect(field).toHaveValue("");
  expect(field).toHaveFocus();
});

it("Escape on a control beside the field returns focus to the field", async () => {
  const user = setupUser();
  render(<ClearableField />);
  const field = screen.getByRole("textbox", { name: "Search" });
  await user.click(field);
  await user.tab();
  expect(screen.getByRole("button", { name: "Clear" })).toHaveFocus();
  await user.keyboard("{Escape}");
  expect(field).toHaveFocus();
  expect(field).toHaveValue("query");
});
