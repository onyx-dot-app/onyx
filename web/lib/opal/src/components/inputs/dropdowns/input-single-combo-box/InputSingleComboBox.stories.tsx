import type { Meta, StoryObj } from "@storybook/react-vite";
import React from "react";
import { InputSingleComboBox } from "./components";
import * as TooltipPrimitive from "@radix-ui/react-tooltip";

const meta: Meta<typeof InputSingleComboBox> = {
  title: "opal/components/InputSingleComboBox",
  component: InputSingleComboBox,
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
type Story = StoryObj<typeof InputSingleComboBox>;

const fruitOptions = [
  { value: "apple", title: "Apple" },
  { value: "banana", title: "Banana" },
  { value: "cherry", title: "Cherry" },
  { value: "dragonfruit", title: "Dragonfruit" },
  { value: "elderberry", title: "Elderberry" },
];

export const Default: Story = {
  render: function DefaultStory() {
    const [value, setValue] = React.useState("");
    return (
      <InputSingleComboBox
        placeholder="Type or select..."
        value={value}
        onChange={(e) => setValue(e.target.value)}
        options={fruitOptions}
      />
    );
  },
};

export const StrictMode: Story = {
  render: function StrictStory() {
    const [value, setValue] = React.useState("");
    return (
      <InputSingleComboBox
        placeholder="Select a fruit (closed)"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        options={fruitOptions}
      />
    );
  },
};

export const WithPreselectedValue: Story = {
  render: function PreselectedStory() {
    const [value, setValue] = React.useState("cherry");
    return (
      <InputSingleComboBox
        placeholder="Select a fruit"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onValueChange={setValue}
        options={fruitOptions}
      />
    );
  },
};

export const Disabled: Story = {
  render: () => (
    <InputSingleComboBox
      placeholder="Cannot interact"
      value="banana"
      options={fruitOptions}
      disabled
    />
  ),
};

export const WithSearchIcon: Story = {
  render: function SearchIconStory() {
    const [value, setValue] = React.useState("");
    return (
      <InputSingleComboBox
        placeholder="Search fruits..."
        value={value}
        onChange={(e) => setValue(e.target.value)}
        options={fruitOptions}
        searchIcon
      />
    );
  },
};

export const ErrorState: Story = {
  render: function ErrorStory() {
    const [value, setValue] = React.useState("invalid-value");
    return (
      <InputSingleComboBox
        placeholder="Select a fruit"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        options={fruitOptions}
        isError
      />
    );
  },
};

export const WithOtherOptions: Story = {
  render: function OtherOptionsStory() {
    const [value, setValue] = React.useState("");
    return (
      <InputSingleComboBox
        placeholder="Search or select..."
        value={value}
        onChange={(e) => setValue(e.target.value)}
        options={fruitOptions}
        showOtherOptions
        separatorLabel="Other fruits"
      />
    );
  },
};
