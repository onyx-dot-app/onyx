import type { Meta, StoryObj } from "@storybook/react-vite";
import React from "react";
import InputSingleSelect from "./InputSingleSelect";
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

export const Default: Story = {
  render: function DefaultStory() {
    const [value, setValue] = React.useState("");
    return (
      <InputSingleSelect
        placeholder="Type or select..."
        value={value}
        onChange={(e) => setValue(e.target.value)}
        options={fruitOptions}
      />
    );
  },
};

export const InputModeNoOptions: Story = {
  render: function InputModeStory() {
    const [value, setValue] = React.useState("");
    return (
      <InputSingleSelect
        placeholder="Type anything..."
        value={value}
        onChange={(e) => setValue(e.target.value)}
      />
    );
  },
};

export const StrictMode: Story = {
  render: function StrictStory() {
    const [value, setValue] = React.useState("");
    return (
      <InputSingleSelect
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
      <InputSingleSelect
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
    <InputSingleSelect
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
      <InputSingleSelect
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
      <InputSingleSelect
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
      <InputSingleSelect
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
