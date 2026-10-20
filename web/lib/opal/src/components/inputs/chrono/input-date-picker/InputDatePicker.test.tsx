import { render, screen, setupUser } from "@tests/setup/test-utils";
import { InputDatePicker } from "@opal/components";

it("Escape on the calendar button returns focus to the first segment", async () => {
  const user = setupUser();
  render(
    <InputDatePicker
      value={new Date(2026, 9, 19)}
      onChange={() => {}}
      clearable
    />
  );

  screen.getByRole("button", { name: "Open calendar" }).focus();
  await user.keyboard("{Escape}");
  expect(screen.getByLabelText("Month")).toHaveFocus();
});
