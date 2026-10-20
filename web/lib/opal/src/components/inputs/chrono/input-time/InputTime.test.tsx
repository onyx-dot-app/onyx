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

it("ArrowRight and ArrowLeft at a segment edge move between segments", async () => {
  const user = setupUser();
  render(
    <InputTime
      value={{ hours: 9, minutes: 30, seconds: 0 }}
      onChange={() => {}}
    />
  );

  const hours = screen.getByLabelText<HTMLInputElement>("Hours");
  hours.focus();
  hours.setSelectionRange(2, 2);
  await user.keyboard("{ArrowRight}");
  expect(screen.getByLabelText("Minutes")).toHaveFocus();

  // The caret lands at the start of Minutes, so ArrowLeft goes straight back.
  await user.keyboard("{ArrowLeft}");
  expect(hours).toHaveFocus();
});
