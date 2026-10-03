import React, { useState } from "react";
import { render, screen } from "@tests/setup/test-utils";
import "@testing-library/jest-dom";
import userEvent from "@testing-library/user-event";
import { Dropdown, InputTypeIn } from "@opal/components";
import type { DropdownItem, DropdownOption } from "@opal/components";

// Mock createPortal for dropdown rendering
jest.mock("react-dom", () => ({
  ...jest.requireActual("react-dom"),
  createPortal: (node: React.ReactNode) => node,
}));

// Mock scrollIntoView which is not available in jsdom
Element.prototype.scrollIntoView = jest.fn();

const ITEMS: DropdownItem[] = [
  { kind: "option", value: "apple", title: "Apple" },
  { kind: "option", value: "banana", title: "Banana", disabled: true },
  {
    kind: "group",
    title: "Citrus",
    foldable: true,
    items: [
      { kind: "option", value: "lemon", title: "Lemon" },
      { kind: "option", value: "lime", title: "Lime" },
    ],
  },
  {
    kind: "group",
    title: "Berries",
    items: [{ kind: "option", value: "strawberry", title: "Strawberry" }],
  },
];

interface HarnessProps {
  items?: DropdownItem[];
  onSelect?: (option: DropdownOption) => void;
  onCreate?: (text: string) => void;
}

/** A type-in trigger over the items; what a pick means is the test's. */
function Harness({ items = ITEMS, onSelect, onCreate }: HarnessProps) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [picked, setPicked] = useState("");
  return (
    <Dropdown open={open} onOpenChange={setOpen}>
      <Dropdown.Trigger asChild typeIn>
        <InputTypeIn
          placeholder="Fruit"
          aria-label="Fruit"
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setOpen(true);
          }}
        />
      </Dropdown.Trigger>
      <Dropdown.Data
        items={items}
        label="Fruit"
        query={query}
        value={picked}
        onSelect={(option) => {
          setPicked(option.value);
          onSelect?.(option);
          setOpen(false);
        }}
        create={
          onCreate && query.trim() !== ""
            ? { text: query.trim(), onCreate }
            : undefined
        }
      />
    </Dropdown>
  );
}

function setupUser() {
  return userEvent.setup({ delay: null });
}

function highlighted() {
  return screen
    .queryAllByRole("option")
    .filter((o) => o.getAttribute("data-interaction") === "hover")
    .map((o) => o.textContent);
}

describe("Dropdown", () => {
  test("the trigger carries the combobox wiring and ArrowDown opens the list", async () => {
    const user = setupUser();
    render(<Harness />);
    const trigger = screen.getByRole("combobox", { name: "Fruit" });
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    expect(trigger).toHaveAttribute("aria-autocomplete", "list");
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();

    await user.click(trigger);
    await user.keyboard("{ArrowDown}");
    expect(trigger).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("listbox", { name: "Fruit" })).toBeInTheDocument();
    expect(highlighted()).toEqual(["Apple"]);
    expect(trigger).toHaveAttribute(
      "aria-activedescendant",
      screen.getByRole("option", { name: "Apple" }).id
    );
  });

  test("the walk skips a disabled row, stops on a folded title, and wraps", async () => {
    const user = setupUser();
    render(<Harness />);
    await user.click(screen.getByRole("combobox", { name: "Fruit" }));
    await user.keyboard("{ArrowDown}");
    expect(highlighted()).toEqual(["Apple"]);

    // Banana is disabled: the next stop is the folded Citrus title.
    await user.keyboard("{ArrowDown}");
    expect(highlighted()).toEqual([]);
    expect(screen.queryByRole("option", { name: "Lemon" })).toBeNull();

    // Enter on the title unfolds it; its rows join the walk.
    await user.keyboard("{Enter}");
    expect(screen.getByRole("option", { name: "Lemon" })).toBeInTheDocument();
    await user.keyboard("{ArrowDown}");
    expect(highlighted()).toEqual(["Lemon"]);

    // Past the last row the walk wraps to the first.
    await user.keyboard("{ArrowDown}{ArrowDown}{ArrowDown}");
    expect(highlighted()).toEqual(["Apple"]);
  });

  test("Enter picks the highlighted row and Escape closes", async () => {
    const user = setupUser();
    const onSelect = jest.fn();
    render(<Harness onSelect={onSelect} />);
    const trigger = screen.getByRole("combobox", { name: "Fruit" });
    await user.click(trigger);
    await user.keyboard("{ArrowDown}{Enter}");
    expect(onSelect).toHaveBeenCalledWith(
      expect.objectContaining({ value: "apple" })
    );
    expect(trigger).toHaveAttribute("aria-expanded", "false");

    await user.keyboard("{ArrowDown}");
    expect(trigger).toHaveAttribute("aria-expanded", "true");
    await user.keyboard("{Escape}");
    expect(trigger).toHaveAttribute("aria-expanded", "false");
  });

  test("the query filters the rows and opens folded groups to show matches", async () => {
    const user = setupUser();
    render(<Harness />);
    await user.type(screen.getByRole("combobox", { name: "Fruit" }), "li");
    expect(screen.getByRole("option", { name: "Lime" })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: "Apple" })).toBeNull();
    expect(screen.queryByRole("option", { name: "Strawberry" })).toBeNull();
  });

  test("the create row is pinned first and Enter commits its text", async () => {
    const user = setupUser();
    const onCreate = jest.fn();
    render(<Harness onCreate={onCreate} />);
    await user.type(screen.getByRole("combobox", { name: "Fruit" }), "kiwi");
    const options = screen.getAllByRole("option");
    expect(options[0]).toHaveTextContent("kiwi");

    await user.keyboard("{ArrowDown}{Enter}");
    expect(onCreate).toHaveBeenCalledWith("kiwi");
  });

  test("a selected value reads as selected", async () => {
    const user = setupUser();
    render(<Harness />);
    const trigger = screen.getByRole("combobox", { name: "Fruit" });
    await user.click(trigger);
    await user.keyboard("{ArrowDown}{Enter}");
    await user.keyboard("{ArrowDown}");
    expect(screen.getByRole("option", { name: "Apple" })).toHaveAttribute(
      "aria-selected",
      "true"
    );
    expect(screen.getByRole("option", { name: "Strawberry" })).toHaveAttribute(
      "aria-selected",
      "false"
    );
  });
});
