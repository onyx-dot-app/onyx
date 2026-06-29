import React, { useState } from "react";
import {
  render,
  screen,
  fireEvent,
  waitFor,
  within,
} from "@testing-library/react";
import "@testing-library/jest-dom";
import userEvent from "@testing-library/user-event";
import InputComboBoxMulti from "./InputComboBoxMulti";
import { ComboBoxOption } from "./types";

// Mock createPortal so the dropdown renders inline
jest.mock("react-dom", () => ({
  ...jest.requireActual("react-dom"),
  createPortal: (node: React.ReactNode) => node,
}));

// scrollIntoView is not implemented in jsdom
Element.prototype.scrollIntoView = jest.fn();

const options: ComboBoxOption[] = [
  { value: "1", label: "Apple" },
  { value: "2", label: "Banana" },
  { value: "3", label: "Cherry" },
];

function setupUser() {
  return userEvent.setup({ delay: null });
}

/**
 * Controlled harness — the component is controlled, so the harness owns
 * `selected` and forwards the latest value to assertions via onChange.
 */
function Harness({
  initial = [],
  onChange,
  creatable = false,
  onCreate,
}: {
  initial?: ComboBoxOption[];
  onChange?: (selected: ComboBoxOption[]) => void;
  creatable?: boolean;
  onCreate?: (label: string) => Promise<ComboBoxOption | null>;
}) {
  const [selected, setSelected] = useState<ComboBoxOption[]>(initial);
  return (
    <InputComboBoxMulti
      placeholder="Select fruit"
      options={options}
      selected={selected}
      creatable={creatable}
      onCreate={onCreate}
      onChange={(next) => {
        setSelected(next);
        onChange?.(next);
      }}
    />
  );
}

describe("InputComboBoxMulti", () => {
  test("renders selected options as removable chips", () => {
    render(<Harness initial={[options[0]!, options[1]!]} />);
    expect(screen.getByText("Apple")).toBeInTheDocument();
    expect(screen.getByText("Banana")).toBeInTheDocument();
  });

  test("selecting an option adds it to the selection", async () => {
    const user = setupUser();
    const onChange = jest.fn();
    render(<Harness onChange={onChange} />);

    fireEvent.focus(screen.getByPlaceholderText("Select fruit"));
    await user.click(await screen.findByText("Banana"));

    expect(onChange).toHaveBeenCalledWith([
      expect.objectContaining({ value: "2", label: "Banana" }),
    ]);
  });

  test("already-selected options are hidden from the dropdown", () => {
    render(<Harness initial={[options[0]!]} />);
    fireEvent.focus(screen.getByPlaceholderText("Select fruit"));

    // "Apple" appears only as a chip, not as a dropdown option
    expect(screen.getByText("Banana")).toBeInTheDocument();
    expect(screen.getByText("Cherry")).toBeInTheDocument();
    expect(screen.getAllByText("Apple")).toHaveLength(1);
  });

  test("removing a chip deselects the option", async () => {
    const user = setupUser();
    const onChange = jest.fn();
    render(
      <Harness initial={[options[0]!, options[1]!]} onChange={onChange} />
    );

    // Scope to the "Apple" chip and click its X remove button
    const appleChip = screen.getByText("Apple").closest("div")!;
    await user.click(within(appleChip).getByRole("button"));

    expect(onChange).toHaveBeenCalledWith([
      expect.objectContaining({ value: "2", label: "Banana" }),
    ]);
  });

  test("creatable: typing a new value and creating it adds the resolved option", async () => {
    const user = setupUser();
    const onChange = jest.fn();
    const onCreate = jest
      .fn()
      .mockResolvedValue({ value: "99", label: "Dragonfruit" });
    render(<Harness creatable onCreate={onCreate} onChange={onChange} />);

    const input = screen.getByPlaceholderText("Select fruit");
    fireEvent.focus(input);
    await user.type(input, "Dragonfruit");
    await user.click(await screen.findByText(/Dragonfruit/));

    await waitFor(() => expect(onCreate).toHaveBeenCalledWith("Dragonfruit"));
    await waitFor(() =>
      expect(onChange).toHaveBeenCalledWith([
        expect.objectContaining({ value: "99", label: "Dragonfruit" }),
      ])
    );
  });
});
