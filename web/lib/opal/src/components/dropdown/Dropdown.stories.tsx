import { useState } from "react";
import type { Meta, StoryObj } from "@storybook/react-vite";
import { Dropdown, type DropdownItem } from "@opal/components";
import { Button, InputTypeIn } from "@opal/components";
import { SvgChevronDown } from "@opal/icons";

const meta: Meta<typeof Dropdown> = {
  title: "Components/Dropdown",
  component: Dropdown,
};
export default meta;

type Story = StoryObj<typeof Dropdown>;

const ITEMS: DropdownItem[] = [
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
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setOpen(true);
            }}
            onClick={() => setOpen(true)}
          />
        </Dropdown.Trigger>
        <Dropdown.Data
          items={ITEMS}
          label="Fruit"
          query={query}
          highlightExactQuery
          value={picked}
          onSelect={(option) => {
            setPicked(option.value);
            setQuery(option.title);
            setOpen(false);
          }}
        />
      </Dropdown>
    </div>
  );
}

/** A text input whose text filters the rows. */
export const TypeInTrigger: Story = { render: () => <TypeInDemo /> };

function ButtonDemo() {
  const [open, setOpen] = useState(false);
  const [picked, setPicked] = useState("");
  const title = ITEMS.flatMap((item) =>
    item.kind === "group" ? item.items : [item]
  ).find((option) => option.value === picked)?.title;
  return (
    <Dropdown open={open} onOpenChange={setOpen}>
      <Dropdown.Trigger asChild>
        <Button
          prominence="secondary"
          rightIcon={SvgChevronDown}
          onClick={() => setOpen((prev) => !prev)}
        >
          {title ?? "Pick a fruit"}
        </Button>
      </Dropdown.Trigger>
      <Dropdown.Data
        items={ITEMS}
        label="Fruit"
        search={{ placeholder: "Search" }}
        value={picked}
        onSelect={(option) => {
          setPicked(option.value);
          setOpen(false);
        }}
      />
    </Dropdown>
  );
}

/** A button trigger with the dropdown's own search field. */
export const ButtonTrigger: Story = { render: () => <ButtonDemo /> };
