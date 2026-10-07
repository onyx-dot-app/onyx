import { useState } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import InputNumber from "@opal/components/inputs/input-number/components";

function Harness({ min }: { min?: number }) {
  const [value, setValue] = useState<number | null>(null);
  return (
    <>
      <InputNumber id="n" value={value} onChange={setValue} min={min} />
      <output data-testid="value">{String(value)}</output>
    </>
  );
}

it("takes a typed negative value when min is negative", async () => {
  const user = userEvent.setup();
  render(<Harness min={-1} />);

  await user.type(screen.getByRole("textbox"), "-1");

  expect(screen.getByRole("textbox")).toHaveValue("-1");
  expect(screen.getByTestId("value")).toHaveTextContent("-1");
});

it("ignores a minus sign when min is not negative", async () => {
  const user = userEvent.setup();
  render(<Harness min={0} />);

  await user.type(screen.getByRole("textbox"), "-5");

  expect(screen.getByRole("textbox")).toHaveValue("5");
  expect(screen.getByTestId("value")).toHaveTextContent("5");
});
