import type { Meta, StoryObj } from "@storybook/react-vite";
import React from "react";
import { InputSingleSelect } from "./components";
import * as TooltipPrimitive from "@radix-ui/react-tooltip";

const meta: Meta<typeof InputSingleSelect> = {
  title: "opal/components/InputSingleSelect",
  component: InputSingleSelect,
  tags: ["autodocs"],
  decorators: [
    (Story) => (
      <TooltipPrimitive.Provider>
        <div style={{ width: 320 }}>
          <Story />
        </div>
      </TooltipPrimitive.Provider>
    ),
  ],
};

export default meta;
type Story = StoryObj<typeof InputSingleSelect>;

const fruitOptions = [
  { value: "apple", label: "Apple" },
  { value: "banana", label: "Banana" },
  { value: "cherry", label: "Cherry" },
  { value: "dragonfruit", label: "Dragonfruit" },
  { value: "elderberry", label: "Elderberry" },
];

const strategySections = [
  {
    options: [
      {
        value: "none",
        label: "Do not re-index",
        description: "Save the settings; existing documents are untouched.",
      },
    ],
  },
  {
    label: "Re-index options",
    options: [
      {
        value: "reindex",
        label: "Re-index all, then switch",
        description: "Keeps the current index live until the new one is ready.",
      },
      {
        value: "instant",
        label: "Switch, then re-index",
        description: "Clears the current index first.",
      },
    ],
  },
];

/** Nothing to type: the trigger only opens the full set. */
export const Default: Story = {
  render: function DefaultStory() {
    const [value, setValue] = React.useState("");
    return (
      <InputSingleSelect
        placeholder="Select a fruit"
        value={value}
        onValueChange={setValue}
        options={fruitOptions}
      />
    );
  },
};

/** Sections render with a titled Divider between them. */
export const WithSections: Story = {
  render: function WithSectionsStory() {
    const [value, setValue] = React.useState("");
    return (
      <InputSingleSelect
        placeholder="Choose a strategy"
        value={value}
        onValueChange={setValue}
        options={strategySections}
      />
    );
  },
};

/** With a default the select never empties: re-picking falls back to it. */
export const WithDefaultOption: Story = {
  render: function WithDefaultOptionStory() {
    const [value, setValue] = React.useState("");
    return (
      <InputSingleSelect
        defaultOption="reindex"
        value={value}
        onValueChange={setValue}
        options={strategySections}
      />
    );
  },
};
