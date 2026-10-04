import { useRef, useState } from "react";
import type { Meta, StoryObj } from "@storybook/react-vite";
import {
  Button,
  Dropdown,
  InputTypeIn,
  LineItemButton,
  type DropdownItem,
  type DropdownMenuItem,
  type DropdownOption,
  type DropdownView,
} from "@opal/components";
import {
  SvgChevronDown,
  SvgChevronLeft,
  SvgEdit,
  SvgMoreHorizontal,
  SvgSettings,
  SvgStar,
  SvgTrash,
} from "@opal/icons";

const meta: Meta<typeof Dropdown> = {
  title: "Components/Dropdown",
  component: Dropdown,
};
export default meta;

type Story = StoryObj<typeof Dropdown>;

const FRUIT: DropdownItem[] = [
  { kind: "option", value: "apple", title: "Apple" },
  { kind: "option", value: "banana", title: "Banana" },
  {
    kind: "group",
    title: "Citrus",
    foldable: true,
    items: [
      { kind: "option", value: "lemon", title: "Lemon" },
      { kind: "option", value: "lime", title: "Lime" },
      { kind: "option", value: "orange", title: "Orange", disabled: true },
    ],
  },
  {
    kind: "group",
    title: "Berries",
    items: [
      { kind: "option", value: "strawberry", title: "Strawberry" },
      { kind: "option", value: "blueberry", title: "Blueberry" },
    ],
  },
];

function TypeInDemo() {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [picked, setPicked] = useState("");
  return (
    <div style={{ width: 280 }}>
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
          items={FRUIT}
          label="Fruit"
          query={query}
          highlightExactQuery
          value={picked}
          onSelect={(option) => {
            setPicked(option.value);
            setQuery(option.title);
          }}
        />
      </Dropdown>
    </div>
  );
}

/** A text input whose text filters the rows: a picker. */
export const TypeInPicker: Story = { render: () => <TypeInDemo /> };

function ButtonPickerDemo() {
  const [picked, setPicked] = useState("");
  const title = FRUIT.flatMap((item) =>
    item.kind === "group" ? item.items : [item]
  )
    .filter((row): row is DropdownOption => row.kind === "option")
    .find((option) => option.value === picked)?.title;
  return (
    <Dropdown>
      <Dropdown.Trigger asChild>
        <Button prominence="secondary" rightIcon={SvgChevronDown}>
          {title ?? "Pick a fruit"}
        </Button>
      </Dropdown.Trigger>
      <Dropdown.Data
        items={FRUIT}
        label="Fruit"
        search={{ placeholder: "Search" }}
        value={picked}
        onSelect={(option) => setPicked(option.value)}
      />
    </Dropdown>
  );
}

/** A button trigger with the dropdown's own search field: a picker. */
export const ButtonPicker: Story = { render: () => <ButtonPickerDemo /> };

function MenuDemo() {
  const settingsRef = useRef<HTMLButtonElement>(null);
  const [pinned, setPinned] = useState(false);
  const [log, setLog] = useState<string[]>([]);
  const note = (text: string) => setLog((prev) => [...prev, text]);
  const items: DropdownMenuItem[] = [
    {
      kind: "action",
      id: "rename",
      title: "Rename",
      icon: SvgEdit,
      onSelect: () => note("rename"),
    },
    {
      kind: "toggle",
      id: "pin",
      title: "Pinned",
      description: "Keep at the top of the list",
      icon: SvgStar,
      checked: pinned,
      onCheckedChange: setPinned,
    },
    {
      kind: "custom",
      id: "settings",
      keywords: ["settings", "configure"],
      keepOpen: true,
      onActivate: () => note("settings: activate"),
      // ArrowRight hands the keyboard to the row's own control.
      onSecondary: () => settingsRef.current?.focus(),
      render: ({ highlighted, props }) => (
        <LineItemButton
          presentational
          selectVariant="select-heavy"
          interaction={highlighted ? "hover" : "rest"}
          rounding={2}
          icon={SvgSettings}
          title="Settings"
          description="A custom row with its own control"
          sizePreset="main-ui"
          variant="heading"
          rightChildren={
            <Button
              ref={settingsRef}
              icon={SvgSettings}
              size="sm"
              prominence="internal"
              aria-label="Settings"
              onClick={(e) => {
                e.stopPropagation();
                note("settings: button");
              }}
            />
          }
          {...props}
        />
      ),
    },
    {
      kind: "group",
      title: "Danger zone",
      items: [
        {
          kind: "action",
          id: "delete",
          title: "Delete",
          icon: SvgTrash,
          danger: true,
          onSelect: () => note("delete"),
        },
      ],
    },
  ];
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <Dropdown>
        <Dropdown.Trigger asChild>
          <Button
            icon={SvgMoreHorizontal}
            prominence="tertiary"
            aria-label="Actions"
          />
        </Dropdown.Trigger>
        <Dropdown.Data
          label="Actions"
          search={{ placeholder: "Search actions" }}
          items={items}
        />
      </Dropdown>
      <pre style={{ fontSize: 12 }}>{log.join("\n")}</pre>
    </div>
  );
}

/** A menu: actions, a toggle, a custom row and a danger group. */
export const Menu: Story = { render: () => <MenuDemo /> };

/** A menu whose rows lead to views that replace it in place. */
function ViewsDemo() {
  const [log, setLog] = useState<string[]>([]);
  const note = (text: string) => setLog((prev) => [...prev, text]);
  const back = (title: string): DropdownMenuItem => ({
    kind: "action",
    id: "back",
    title,
    icon: SvgChevronLeft,
    onSelect: (views) => views.pop(),
  });
  const skills: DropdownView = {
    key: "skills",
    search: { placeholder: "Search skills" },
    items: [
      back("Skills"),
      {
        kind: "action",
        id: "write",
        title: "Write",
        onSelect: () => note("write"),
      },
      {
        kind: "action",
        id: "review",
        title: "Review",
        onSelect: () => note("review"),
      },
      {
        kind: "action",
        id: "plan",
        title: "Plan",
        onSelect: () => note("plan"),
      },
    ],
  };
  const apps: DropdownView = {
    key: "apps",
    items: [
      back("Apps"),
      {
        kind: "action",
        id: "slack",
        title: "Slack",
        onSelect: () => note("slack"),
      },
      {
        kind: "action",
        id: "drive",
        title: "Drive",
        onSelect: () => note("drive"),
      },
    ],
  };
  const items: DropdownMenuItem[] = [
    {
      kind: "action",
      id: "rename",
      title: "Rename",
      icon: SvgEdit,
      onSelect: () => note("rename"),
    },
    {
      kind: "action",
      id: "skills",
      title: "Skills",
      opensView: true,
      onSelect: (views) => views.push(skills),
    },
    {
      kind: "action",
      id: "apps",
      title: "Apps",
      opensView: true,
      onSelect: (views) => views.push(apps),
    },
  ];
  return (
    <div className="flex flex-col gap-3">
      <Dropdown>
        <Dropdown.Trigger asChild>
          <Button
            icon={SvgMoreHorizontal}
            prominence="tertiary"
            aria-label="Actions"
          />
        </Dropdown.Trigger>
        <Dropdown.Data label="Actions" items={items} />
      </Dropdown>
      <pre className="text-xs">{log.join("\n")}</pre>
    </div>
  );
}

export const Views: Story = { render: () => <ViewsDemo /> };
