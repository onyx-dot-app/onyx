import React, { useState } from "react";
import { render, screen } from "@tests/setup/test-utils";
import "@testing-library/jest-dom";
import userEvent from "@testing-library/user-event";
import { Dropdown, InputTypeIn } from "@opal/components";
import type {
  DropdownItem,
  DropdownMenuItem,
  DropdownOption,
} from "@opal/components";

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

interface MenuHarnessProps {
  onAction: jest.Mock;
  onToggle: jest.Mock;
  onSecondary?: jest.Mock;
}

/** A button trigger over a menu: an action, a toggle and a custom row. */
function MenuHarness({ onAction, onToggle, onSecondary }: MenuHarnessProps) {
  const [checked, setChecked] = useState(false);
  const items: DropdownMenuItem[] = [
    { kind: "action", id: "rename", title: "Rename", onSelect: onAction },
    {
      kind: "toggle",
      id: "pin",
      title: "Pinned",
      checked,
      onCheckedChange: (next) => {
        setChecked(next);
        onToggle(next);
      },
    },
    {
      kind: "custom",
      id: "custom",
      keywords: ["settings"],
      onSecondary,
      render: ({ highlighted, props }) => (
        <div data-highlighted={highlighted || undefined} {...props}>
          Settings
        </div>
      ),
    },
  ];
  return (
    <Dropdown>
      <Dropdown.Trigger asChild>
        <button type="button">Actions</button>
      </Dropdown.Trigger>
      <Dropdown.Data label="Actions" items={items} />
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

describe("Dropdown picker", () => {
  test("the trigger carries the combobox wiring and ArrowDown opens the list", async () => {
    const user = setupUser();
    render(<Harness />);
    const trigger = screen.getByRole("combobox", { name: "Fruit" });
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    expect(trigger).toHaveAttribute("aria-haspopup", "listbox");
    expect(trigger).toHaveAttribute("aria-autocomplete", "list");
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();

    // Focus without a click: a click on a type-in opens it by itself.
    trigger.focus();
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

  test("Enter picks the highlighted row and closes; Escape closes", async () => {
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

  test("Tab walks the rows from a type-in and keeps the list open", async () => {
    const user = setupUser();
    render(<Harness />);
    const trigger = screen.getByRole("combobox", { name: "Fruit" });
    await user.click(trigger);
    await user.keyboard("{ArrowDown}");
    expect(highlighted()).toEqual(["Apple"]);

    await user.keyboard("{Tab}");
    expect(highlighted()).not.toEqual(["Apple"]);
    expect(trigger).toHaveAttribute("aria-expanded", "true");
    expect(trigger).toHaveFocus();
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

/** A button trigger over the grouped picker items, so the arrows reach the groups. */
function ButtonPickerHarness() {
  const [picked, setPicked] = useState("");
  return (
    <Dropdown>
      <Dropdown.Trigger asChild>
        <button type="button">Fruit</button>
      </Dropdown.Trigger>
      <Dropdown.Data
        items={ITEMS}
        label="Fruit"
        value={picked}
        onSelect={(option) => setPicked(option.value)}
      />
    </Dropdown>
  );
}

describe("Dropdown groups", () => {
  test("ArrowRight unfolds a title and enters it; ArrowLeft leaves and folds", async () => {
    const user = setupUser();
    render(<ButtonPickerHarness />);
    await user.click(screen.getByRole("button", { name: "Fruit" }));
    // Apple, then (Banana is disabled) the folded Citrus title.
    await user.keyboard("{ArrowDown}{ArrowDown}");
    const title = screen.getByRole("option", { name: /Citrus/ });
    expect(title).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("option", { name: "Lemon" })).toBeNull();

    await user.keyboard("{ArrowRight}");
    expect(title).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("option", { name: "Lemon" })).toBeInTheDocument();

    await user.keyboard("{ArrowRight}");
    expect(highlighted()).toEqual(["Lemon"]);

    await user.keyboard("{ArrowLeft}");
    expect(highlighted()).toEqual([]);
    expect(title).toHaveAttribute("aria-expanded", "true");

    await user.keyboard("{ArrowLeft}");
    expect(title).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("option", { name: "Lemon" })).toBeNull();
  });

  test("a type-in keeps the arrows for its caret", async () => {
    const user = setupUser();
    render(<Harness />);
    const trigger = screen.getByRole("combobox", { name: "Fruit" });
    await user.type(trigger, "l");
    await user.keyboard("{ArrowDown}");
    await user.keyboard("{ArrowLeft}");
    expect(highlighted()).toEqual(["Lemon"]);
  });
});

describe("Dropdown menu", () => {
  test("a button trigger toggles a menu, with menu semantics", async () => {
    const user = setupUser();
    render(<MenuHarness onAction={jest.fn()} onToggle={jest.fn()} />);
    const trigger = screen.getByRole("button", { name: "Actions" });
    expect(trigger).toHaveAttribute("aria-haspopup", "menu");
    expect(trigger).not.toHaveAttribute("role", "combobox");

    await user.click(trigger);
    expect(trigger).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("menu", { name: "Actions" })).toBeInTheDocument();
    expect(
      screen.getByRole("menuitem", { name: "Rename" })
    ).toBeInTheDocument();
    expect(
      screen.getByRole("menuitemcheckbox", { name: "Pinned" })
    ).toHaveAttribute("aria-checked", "false");

    await user.click(trigger);
    expect(trigger).toHaveAttribute("aria-expanded", "false");
  });

  test("an action closes the menu; a toggle flips and stays open", async () => {
    const user = setupUser();
    const onAction = jest.fn();
    const onToggle = jest.fn();
    render(<MenuHarness onAction={onAction} onToggle={onToggle} />);
    const trigger = screen.getByRole("button", { name: "Actions" });

    await user.click(trigger);
    await user.click(screen.getByRole("menuitemcheckbox", { name: "Pinned" }));
    expect(onToggle).toHaveBeenCalledWith(true);
    expect(trigger).toHaveAttribute("aria-expanded", "true");
    expect(
      screen.getByRole("menuitemcheckbox", { name: "Pinned" })
    ).toHaveAttribute("aria-checked", "true");

    await user.click(screen.getByRole("menuitem", { name: "Rename" }));
    expect(onAction).toHaveBeenCalledTimes(1);
    expect(trigger).toHaveAttribute("aria-expanded", "false");
  });

  test("a custom row is a keyboard stop and ArrowRight reaches its secondary control", async () => {
    const user = setupUser();
    const onSecondary = jest.fn();
    render(
      <MenuHarness
        onAction={jest.fn()}
        onToggle={jest.fn()}
        onSecondary={onSecondary}
      />
    );
    const trigger = screen.getByRole("button", { name: "Actions" });
    await user.click(trigger);
    await user.keyboard("{ArrowDown}{ArrowDown}{ArrowDown}");
    const custom = screen.getByRole("menuitem", { name: "Settings" });
    expect(custom).toHaveAttribute("data-highlighted", "true");
    expect(trigger).toHaveAttribute("aria-activedescendant", custom.id);

    await user.keyboard("{ArrowRight}");
    expect(onSecondary).toHaveBeenCalledTimes(1);
    expect(trigger).toHaveAttribute("aria-expanded", "true");
  });

  test("Tab closes a button-triggered menu and lets focus move on", async () => {
    const user = setupUser();
    render(<MenuHarness onAction={jest.fn()} onToggle={jest.fn()} />);
    const trigger = screen.getByRole("button", { name: "Actions" });
    await user.click(trigger);
    await user.keyboard("{ArrowDown}");
    expect(trigger).toHaveAttribute("aria-expanded", "true");

    await user.keyboard("{Tab}");
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    expect(trigger).not.toHaveFocus();
  });

  test("letters type ahead to the row they start", async () => {
    const user = setupUser();
    render(<MenuHarness onAction={jest.fn()} onToggle={jest.fn()} />);
    const trigger = screen.getByRole("button", { name: "Actions" });
    await user.click(trigger);
    await user.keyboard("p");
    expect(
      screen.getByRole("menuitemcheckbox", { name: "Pinned" })
    ).toHaveAttribute("data-interaction", "hover");
    expect(trigger).toHaveAttribute("aria-expanded", "true");
  });

  test("a menu rejects option rows at the type level", () => {
    const items: DropdownMenuItem[] = [
      // @ts-expect-error an option needs a picker (a `value`)
      { kind: "option", value: "apple", title: "Apple" },
    ];
    expect(items).toHaveLength(1);
  });
});
