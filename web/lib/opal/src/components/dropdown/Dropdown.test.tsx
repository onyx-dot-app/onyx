import React, { useState } from "react";
import { render, screen } from "@tests/setup/test-utils";
import "@testing-library/jest-dom";
import userEvent from "@testing-library/user-event";
import { Dropdown, InputTypeIn } from "@opal/components";
import type {
  DropdownItem,
  DropdownMenuItem,
  DropdownOption,
  DropdownView,
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

    // Banana is disabled: the next stop is the folded Citrus title, which
    // is a button, not an option.
    await user.keyboard("{ArrowDown}");
    expect(highlighted()).toEqual([]);
    expect(screen.getByRole("button", { name: /Citrus/ })).toHaveAttribute(
      "data-interaction",
      "hover"
    );
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

  test("an open list takes Escape before a dialog's document listener", async () => {
    const user = setupUser();
    render(<Harness />);
    // A dialog listens for Escape on the document in the capture phase.
    const dialogEscape = jest.fn();
    const onDocumentKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") dialogEscape();
    };
    document.addEventListener("keydown", onDocumentKeyDown, true);
    try {
      const trigger = screen.getByRole("combobox", { name: "Fruit" });
      await user.click(trigger);
      await user.keyboard("{ArrowDown}");
      expect(trigger).toHaveAttribute("aria-expanded", "true");
      await user.keyboard("{Escape}");
      expect(trigger).toHaveAttribute("aria-expanded", "false");
      expect(dialogEscape).not.toHaveBeenCalled();
      // Closed, the key is the dialog's.
      await user.keyboard("{Escape}");
      expect(dialogEscape).toHaveBeenCalledTimes(1);
    } finally {
      document.removeEventListener("keydown", onDocumentKeyDown, true);
    }
  });

  test("the query filters the rows and opens folded groups to show matches", async () => {
    const user = setupUser();
    render(<Harness />);
    await user.type(screen.getByRole("combobox", { name: "Fruit" }), "li");
    expect(screen.getByRole("option", { name: "Lime" })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: "Apple" })).toBeNull();
    expect(screen.queryByRole("option", { name: "Strawberry" })).toBeNull();
  });

  test("a highlight follows its row when the query filters the list", async () => {
    const user = setupUser();
    const onSelect = jest.fn();
    render(<Harness onSelect={onSelect} />);
    const trigger = screen.getByRole("combobox", { name: "Fruit" });
    await user.click(trigger);
    // Apple, past disabled Banana to the Citrus title, unfold, Lemon, Lime.
    await user.keyboard("{ArrowDown}{ArrowDown}{Enter}{ArrowDown}{ArrowDown}");
    expect(highlighted()).toEqual(["Lime"]);

    // "li" keeps Lime and drops the rows before it; the highlight follows.
    await user.type(trigger, "li");
    expect(highlighted()).toEqual(["Lime"]);
    await user.keyboard("{Enter}");
    expect(onSelect).toHaveBeenCalledWith(
      expect.objectContaining({ value: "lime" })
    );
  });

  test("a highlight clears when its row filters out", async () => {
    const user = setupUser();
    render(<Harness />);
    const trigger = screen.getByRole("combobox", { name: "Fruit" });
    await user.click(trigger);
    await user.keyboard("{ArrowDown}");
    expect(highlighted()).toEqual(["Apple"]);

    await user.type(trigger, "straw");
    expect(highlighted()).toEqual([]);
    expect(trigger).not.toHaveAttribute("aria-activedescendant");
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
        {/* A combobox takes no name from its content. */}
        <button type="button" aria-label="Fruit">
          Fruit
        </button>
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

/** One list, two button triggers. */
function TwoTriggersHarness() {
  const [picked, setPicked] = useState("");
  return (
    <Dropdown>
      <Dropdown.Trigger asChild>
        <button type="button" aria-label="Left">
          Left
        </button>
      </Dropdown.Trigger>
      <Dropdown.Trigger asChild>
        <button type="button" aria-label="Right">
          Right
        </button>
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

describe("Dropdown triggers", () => {
  test("a click on another trigger toggles the list rather than reopening it", async () => {
    const user = setupUser();
    render(<TwoTriggersHarness />);
    // A button that triggers a picker keeps its role, and so its name.
    const left = screen.getByRole("button", { name: "Left" });
    const right = screen.getByRole("button", { name: "Right" });
    await user.click(left);
    expect(left).toHaveAttribute("aria-expanded", "true");

    // Inside, not outside: the second trigger closes the open list.
    await user.click(right);
    expect(right).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("listbox")).toBeNull();

    await user.click(right);
    expect(right).toHaveAttribute("aria-expanded", "true");
  });
});

describe("Dropdown pinned rows", () => {
  test("a pinned row stays while a search is on, in a group too", async () => {
    const user = setupUser();
    const items: DropdownItem[] = [
      { kind: "option", value: "all", title: "All", pinned: true },
      { kind: "option", value: "apple", title: "Apple" },
      {
        kind: "group",
        title: "More",
        items: [
          { kind: "option", value: "new", title: "New", pinned: true },
          { kind: "option", value: "pear", title: "Pear" },
        ],
      },
    ];
    render(<Harness items={items} />);
    await user.type(screen.getByRole("combobox", { name: "Fruit" }), "pe");
    expect(
      screen.getAllByRole("option").map((option) => option.textContent)
    ).toEqual(["All", "New", "Pear"]);
  });
});

describe("Dropdown groups", () => {
  test("ArrowRight unfolds a title and enters it", async () => {
    const user = setupUser();
    render(<ButtonPickerHarness />);
    await user.click(screen.getByRole("button", { name: "Fruit" }));
    // Apple, then (Banana is disabled) the folded Citrus title.
    await user.keyboard("{ArrowDown}{ArrowDown}");
    const title = screen.getByRole("button", { name: /Citrus/ });
    expect(title).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("option", { name: "Lemon" })).toBeNull();

    await user.keyboard("{ArrowRight}");
    expect(title).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("option", { name: "Lemon" })).toBeInTheDocument();

    await user.keyboard("{ArrowRight}");
    expect(highlighted()).toEqual(["Lemon"]);
  });

  test("a type-in keeps ArrowRight for its caret", async () => {
    const user = setupUser();
    render(<Harness />);
    const trigger = screen.getByRole("combobox", { name: "Fruit" });
    await user.type(trigger, "lem");
    // The Citrus title (open while searching) stays a plain stop.
    await user.keyboard("{ArrowDown}");
    const title = screen.getByRole("button", { name: /Citrus/ });
    expect(title).toHaveAttribute("data-interaction", "hover");
    await user.keyboard("{ArrowRight}");
    expect(title).toHaveAttribute("data-interaction", "hover");
    expect(highlighted()).toEqual([]);
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

// ---------------------------------------------------------------------------
// Views
// ---------------------------------------------------------------------------

interface ViewsHarnessProps {
  onRun: (id: string) => void;
  /** The Apps row pushes only when this is set, else it runs `auth`. */
  authed?: boolean;
  rootSearch?: boolean;
}

/**
 * A menu whose Skills row leads to a view with its own search and a Back
 * row, and whose Apps row decides at runtime whether to push a view.
 */
function ViewsHarness({
  onRun,
  authed = false,
  rootSearch,
}: ViewsHarnessProps) {
  const skills: DropdownView = {
    key: "skills",
    search: { placeholder: "Search skills" },
    items: [
      {
        kind: "action",
        id: "back",
        title: "Back",
        onSelect: (views) => views.pop(),
      },
      {
        kind: "action",
        id: "write",
        title: "Write",
        onSelect: () => onRun("write"),
      },
      {
        kind: "action",
        id: "review",
        title: "Review",
        onSelect: () => onRun("review"),
      },
      {
        kind: "action",
        id: "wrap",
        title: "Wrap up",
        onSelect: (views) =>
          views.push({
            key: "wrap",
            items: [
              {
                kind: "action",
                id: "back",
                title: "Back",
                onSelect: (nested) => nested.pop(),
              },
              {
                kind: "action",
                id: "extra",
                title: "Extra",
                onSelect: () => onRun("extra"),
              },
            ],
          }),
      },
    ],
  };
  const apps: DropdownView = {
    key: "apps",
    items: [
      {
        kind: "action",
        id: "slack",
        title: "Slack",
        onSelect: () => onRun("slack"),
      },
    ],
  };
  const items: DropdownMenuItem[] = [
    {
      kind: "action",
      id: "rename",
      title: "Rename",
      onSelect: () => onRun("rename"),
    },
    {
      // A row that leads to a page is the caller's: it pushes on Enter and
      // on ArrowRight, and renders its own chevron.
      kind: "custom",
      id: "skills",
      keywords: ["Skills"],
      onActivate: (views) => views.push(skills),
      onSecondary: (views) => views.push(skills),
      render: ({ highlighted, props }) => (
        <div data-interaction={highlighted ? "hover" : "rest"} {...props}>
          Skills
        </div>
      ),
    },
    {
      kind: "action",
      id: "apps",
      title: "Apps",
      onSelect: (views) => (authed ? views.push(apps) : onRun("auth")),
    },
  ];
  return (
    <Dropdown>
      <Dropdown.Trigger asChild>
        <button type="button">Actions</button>
      </Dropdown.Trigger>
      <Dropdown.Data
        label="Actions"
        items={items}
        search={rootSearch ? { placeholder: "Search actions" } : undefined}
      />
    </Dropdown>
  );
}

function menuItem(name: string) {
  return screen.getByRole("menuitem", { name });
}

describe("Dropdown views", () => {
  test("a row pushes a view over the rows and a row in it pops back", async () => {
    const user = setupUser();
    render(<ViewsHarness onRun={jest.fn()} />);
    const trigger = screen.getByRole("button", { name: "Actions" });
    await user.click(trigger);

    await user.click(menuItem("Skills"));
    expect(trigger).toHaveAttribute("aria-expanded", "true");
    expect(menuItem("Write")).toBeInTheDocument();
    expect(screen.queryByRole("menuitem", { name: "Rename" })).toBeNull();

    await user.click(menuItem("Back"));
    expect(trigger).toHaveAttribute("aria-expanded", "true");
    expect(menuItem("Rename")).toBeInTheDocument();
    expect(screen.queryByRole("menuitem", { name: "Write" })).toBeNull();
  });

  test("ArrowRight opens a page through onSecondary; Escape leaves the view, then closes", async () => {
    const user = setupUser();
    render(<ViewsHarness onRun={jest.fn()} />);
    const trigger = screen.getByRole("button", { name: "Actions" });
    await user.click(trigger);
    // Rename, then Skills.
    await user.keyboard("{ArrowDown}{ArrowDown}");
    expect(menuItem("Skills")).toHaveAttribute("data-interaction", "hover");

    await user.keyboard("{ArrowRight}");
    // The keyboard lands on the view's first row; its search field has focus.
    expect(menuItem("Back")).toHaveAttribute("data-interaction", "hover");
    expect(
      screen.getByRole("textbox", { name: "Search skills" })
    ).toHaveFocus();

    await user.keyboard("{Escape}");
    // Back at the root, on the row that led in, with focus on the trigger.
    expect(menuItem("Skills")).toHaveAttribute("data-interaction", "hover");
    expect(trigger).toHaveFocus();
    expect(trigger).toHaveAttribute("aria-expanded", "true");

    await user.keyboard("{Escape}");
    expect(trigger).toHaveAttribute("aria-expanded", "false");
  });

  test("a handler decides whether to push; a row that does not push closes as usual", async () => {
    const user = setupUser();
    const onRun = jest.fn();
    const { rerender } = render(<ViewsHarness onRun={onRun} />);
    const trigger = screen.getByRole("button", { name: "Actions" });
    await user.click(trigger);
    await user.click(menuItem("Apps"));
    expect(onRun).toHaveBeenCalledWith("auth");
    expect(trigger).toHaveAttribute("aria-expanded", "false");

    rerender(<ViewsHarness onRun={onRun} authed />);
    await user.click(trigger);
    await user.click(menuItem("Apps"));
    // Pushing keeps the list open, with no `keepOpen` needed.
    expect(trigger).toHaveAttribute("aria-expanded", "true");
    expect(menuItem("Slack")).toBeInTheDocument();
  });

  test("each view's search is its own and keeps its text while on the stack", async () => {
    const user = setupUser();
    render(<ViewsHarness onRun={jest.fn()} rootSearch />);
    await user.click(screen.getByRole("button", { name: "Actions" }));
    await user.type(
      screen.getByRole("textbox", { name: "Search actions" }),
      "sk"
    );
    expect(screen.queryByRole("menuitem", { name: "Rename" })).toBeNull();

    await user.click(menuItem("Skills"));
    const skillsSearch = screen.getByRole("textbox", { name: "Search skills" });
    expect(skillsSearch).toHaveValue("");
    expect(skillsSearch).toHaveFocus();
    await user.type(skillsSearch, "wr");
    expect(menuItem("Write")).toBeInTheDocument();
    expect(screen.queryByRole("menuitem", { name: "Review" })).toBeNull();

    // A view underneath another keeps its text until it is back on top.
    await user.click(menuItem("Wrap up"));
    expect(menuItem("Extra")).toBeInTheDocument();
    await user.click(menuItem("Back"));
    expect(screen.getByRole("textbox", { name: "Search skills" })).toHaveValue(
      "wr"
    );
    expect(menuItem("Write")).toBeInTheDocument();

    await user.keyboard("{Escape}");
    // The root's text survived the view, and its field has focus again.
    const rootSearch = screen.getByRole("textbox", { name: "Search actions" });
    expect(rootSearch).toHaveValue("sk");
    expect(rootSearch).toHaveFocus();
    expect(screen.queryByRole("menuitem", { name: "Rename" })).toBeNull();
  });

  test("closing the list resets it to the root", async () => {
    const user = setupUser();
    render(<ViewsHarness onRun={jest.fn()} />);
    const trigger = screen.getByRole("button", { name: "Actions" });
    await user.click(trigger);
    await user.click(menuItem("Skills"));
    expect(menuItem("Write")).toBeInTheDocument();

    await user.click(trigger);
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    await user.click(trigger);
    expect(menuItem("Rename")).toBeInTheDocument();
    expect(screen.queryByRole("menuitem", { name: "Write" })).toBeNull();
  });
});

/** A view in the registry, rebuilt every render around a toggle's state. */
function RegistryHarness() {
  const [pinned, setPinned] = useState(false);
  const prefs: DropdownView = {
    items: [
      {
        kind: "toggle",
        id: "pin",
        title: "Pinned",
        checked: pinned,
        onCheckedChange: setPinned,
      },
    ],
  };
  const items: DropdownMenuItem[] = [
    {
      kind: "action",
      id: "prefs",
      title: "Preferences",
      onSelect: (views) => views.push("prefs"),
    },
  ];
  return (
    <Dropdown>
      <Dropdown.Trigger asChild>
        <button type="button">Actions</button>
      </Dropdown.Trigger>
      <Dropdown.Data label="Actions" items={items} views={{ prefs }} />
    </Dropdown>
  );
}

describe("Dropdown view registry", () => {
  test("a view pushed by key shows its latest rows", async () => {
    const user = setupUser();
    render(<RegistryHarness />);
    await user.click(screen.getByRole("button", { name: "Actions" }));
    await user.click(menuItem("Preferences"));
    const pin = screen.getByRole("menuitemcheckbox", { name: "Pinned" });
    expect(pin).toHaveAttribute("aria-checked", "false");

    await user.click(pin);
    expect(
      screen.getByRole("menuitemcheckbox", { name: "Pinned" })
    ).toHaveAttribute("aria-checked", "true");
  });
});
