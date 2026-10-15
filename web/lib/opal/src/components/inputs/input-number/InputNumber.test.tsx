import { useState } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import InputNumber from "@opal/components/inputs/input-number/components";

interface HarnessProps {
  min?: number;
  initial?: number | null;
  allowEmpty?: boolean;
}

function Harness({ min, initial = null, allowEmpty }: HarnessProps) {
  const [value, setValue] = useState<number | null>(initial);
  return (
    <>
      <InputNumber
        id="n"
        value={value}
        onChange={setValue}
        min={min}
        allowEmpty={allowEmpty}
      />
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

it("commits null when a cleared field loses focus", async () => {
  const user = userEvent.setup();
  render(<Harness initial={5} />);

  await user.clear(screen.getByRole("textbox"));
  await user.tab();

  expect(screen.getByTestId("value")).toHaveTextContent("null");
});

it("restores the value of a cleared field that does not allow empty", async () => {
  const user = userEvent.setup();
  render(<Harness initial={5} allowEmpty={false} />);

  await user.clear(screen.getByRole("textbox"));
  await user.tab();

  expect(screen.getByRole("textbox")).toHaveValue("5");
  expect(screen.getByTestId("value")).toHaveTextContent("5");
});
