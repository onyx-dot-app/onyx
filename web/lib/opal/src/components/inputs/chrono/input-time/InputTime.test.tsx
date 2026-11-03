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
  const minutes = screen.getByLabelText<HTMLInputElement>("Minutes");
  expect(minutes).toHaveFocus();
  expect(minutes.selectionStart).toBe(0);

  // The caret lands at the start of Minutes, so ArrowLeft goes straight back.
  await user.keyboard("{ArrowLeft}");
  expect(hours).toHaveFocus();
  expect(hours.selectionStart).toBe(2);
});

describe("arrows that stay inside a segment", () => {
  function renderAtHoursEnd(
    selectionStart = 2,
    selectionEnd = selectionStart
  ): HTMLInputElement {
    render(
      <InputTime
        value={{ hours: 9, minutes: 30, seconds: 0 }}
        onChange={() => {}}
      />
    );
    const hours = screen.getByLabelText<HTMLInputElement>("Hours");
    hours.focus();
    hours.setSelectionRange(selectionStart, selectionEnd);
    return hours;
  }

  it("keeps a mid-segment caret move native", async () => {
    const user = setupUser();
    const hours = renderAtHoursEnd(1);
    await user.keyboard("{ArrowRight}");
    expect(hours).toHaveFocus();
  });

  it("keeps a selection native", async () => {
    const user = setupUser();
    const hours = renderAtHoursEnd(0, 2);
    await user.keyboard("{ArrowRight}");
    expect(hours).toHaveFocus();
  });

  it.each(["Shift", "Control", "Meta", "Alt"])(
    "leaves %s+ArrowRight at the edge to the browser",
    async (modifier) => {
      const user = setupUser();
      const hours = renderAtHoursEnd();
      await user.keyboard(`{${modifier}>}{ArrowRight}{/${modifier}}`);
      expect(hours).toHaveFocus();
    }
  );
});
