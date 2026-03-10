import type { Meta, StoryObj } from "@storybook/react";
import React from "react";
import InputComboBox from "./InputComboBox";
import * as TooltipPrimitive from "@radix-ui/react-tooltip";

const meta: Meta<typeof InputComboBox> = {
  title: "refresh-components/inputs/InputComboBox",
  component: InputComboBox,
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
type Story = StoryObj<typeof InputComboBox>;

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
      <InputComboBox
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
      <InputComboBox
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
      <InputComboBox
        placeholder="Select a fruit (strict)"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        options={fruitOptions}
        strict
      />
    );
  },
};

export const WithPreselectedValue: Story = {
  render: function PreselectedStory() {
    const [value, setValue] = React.useState("cherry");
    return (
      <InputComboBox
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
    <InputComboBox
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
      <InputComboBox
        placeholder="Search fruits..."
        value={value}
        onChange={(e) => setValue(e.target.value)}
        options={fruitOptions}
        leftSearchIcon
      />
    );
  },
};

export const ErrorState: Story = {
  render: function ErrorStory() {
    const [value, setValue] = React.useState("invalid-value");
    return (
      <InputComboBox
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
      <InputComboBox
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
