import { render, screen, setupUser } from "@tests/setup/test-utils";
import { InputTime } from "@opal/components";

it("Escape on the clear button returns focus to the first segment", async () => {
  const user = setupUser();
  render(
    <InputTime
      value={{ hours: 9, minutes: 30, seconds: 0 }}
      onChange={() => {}}
      clearable
    />
  );

  screen.getByRole("button", { name: "Clear" }).focus();
  await user.keyboard("{Escape}");
  expect(screen.getByLabelText("Hours")).toHaveFocus();
});
