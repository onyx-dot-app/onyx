import type { Meta, StoryObj } from "@storybook/react-vite";
import React from "react";
import { InputSingleSelect } from "./components";
import type { SelectOptions } from "@opal/components";
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
  { value: "apple", title: "Apple" },
  { value: "banana", title: "Banana" },
  { value: "cherry", title: "Cherry" },
  { value: "dragonfruit", title: "Dragonfruit" },
  { value: "elderberry", title: "Elderberry" },
];

const strategyOptions: SelectOptions = [
  {
    value: "none",
    title: "Do not re-index",
    description: "Save the settings; existing documents are untouched.",
  },
  {
    title: "Re-index options",
    options: [
      {
        value: "reindex",
        title: "Re-index all, then switch",
        description: "Keeps the current index live until the new one is ready.",
      },
      {
        value: "instant",
        title: "Switch, then re-index",
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
        options={strategyOptions}
      />
    );
  },
};

const providerOptions: SelectOptions = [
  {
    title: "OpenAI",
    foldable: true,
    options: [
      { value: "gpt-4o", title: "GPT-4o" },
      { value: "gpt-4.1", title: "GPT-4.1" },
      { value: "o3", title: "o3" },
    ],
  },
  {
    title: "Anthropic",
    foldable: true,
    options: [
      { value: "sonnet", title: "Claude Sonnet 4" },
      { value: "opus", title: "Claude Opus 4" },
    ],
  },
  {
    title: "Google",
    foldable: true,
    options: [{ value: "gemini", title: "Gemini 2.5 Pro" }],
  },
];

/** A search field at the top of the list filters the rows. */
export const Searchable: Story = {
  render: function SearchableStory() {
    const [value, setValue] = React.useState("");
    return (
      <InputSingleSelect
        search
        placeholder="Select a fruit"
        value={value}
        onValueChange={setValue}
        options={fruitOptions}
      />
    );
  },
};

/** Foldable dividers: the group holding the selection opens, the rest fold. */
export const FoldableDividers: Story = {
  render: function FoldableDividersStory() {
    const [value, setValue] = React.useState("sonnet");
    return (
      <InputSingleSelect
        search
        placeholder="Select a model"
        value={value}
        onValueChange={setValue}
        options={providerOptions}
      />
    );
  },
};

/** With a default the select never empties: a re-pick does nothing. */
export const WithDefaultOption: Story = {
  render: function WithDefaultOptionStory() {
    const [value, setValue] = React.useState("");
    return (
      <InputSingleSelect
        defaultOption="reindex"
        placeholder="Select an option"
        value={value}
        onValueChange={setValue}
        options={strategyOptions}
      />
    );
  },
};
