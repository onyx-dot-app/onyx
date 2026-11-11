import { useState } from "react";
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { InputSwitch } from "@opal/components/inputs/booleans/input-switch/components";

it("toggles on every Enter and Space press and keeps focus", async () => {
  const user = userEvent.setup();
  const onCheckedChange = jest.fn();
  render(<InputSwitch aria-label="alerts" onCheckedChange={onCheckedChange} />);
  const toggle = screen.getByRole("switch", { name: "alerts" });

  await user.tab();
  await user.keyboard("{Enter}{Enter}[Space]");

  expect(onCheckedChange.mock.calls).toEqual([[true], [false], [true]]);
  expect(toggle).toHaveFocus();
});

function SavingSwitch({ onSave }: { onSave: (checked: boolean) => void }) {
  const [checked, setChecked] = useState(false);
  const [saving, setSaving] = useState(false);
  return (
    <>
      <InputSwitch
        aria-label="alerts"
        checked={checked}
        disabled={saving}
        onCheckedChange={(next) => {
          setChecked(next);
          setSaving(true);
          onSave(next);
        }}
      />
      <button onClick={() => setSaving(false)}>finish save</button>
    </>
  );
}

it("keeps focus while disabled for a save, ignores input, then toggles again", async () => {
  const user = userEvent.setup();
  const onSave = jest.fn();
  render(<SavingSwitch onSave={onSave} />);
  const toggle = screen.getByRole("switch", { name: "alerts" });

  await user.tab();
  await user.keyboard("{Enter}");
  expect(toggle).toHaveAttribute("aria-disabled", "true");
  expect(toggle).toHaveFocus();

  await user.keyboard("{Enter}");
  expect(onSave.mock.calls).toEqual([[true]]);

  // A direct click, not user.click: the save ends without moving focus.
  act(() => screen.getByRole("button", { name: "finish save" }).click());
  expect(toggle).not.toHaveAttribute("aria-disabled");
  expect(toggle).toHaveFocus();
  await user.keyboard("{Enter}");
  expect(onSave.mock.calls).toEqual([[true], [false]]);
});

it("skips a disabled switch when tabbing", async () => {
  const user = userEvent.setup();
  render(
    <>
      <InputSwitch aria-label="first" />
      <InputSwitch aria-label="disabled" disabled />
      <InputSwitch aria-label="last" />
    </>
  );

  await user.tab();
  await user.tab();

  expect(screen.getByRole("switch", { name: "last" })).toHaveFocus();
});
