import type { Meta, StoryObj } from "@storybook/react";
import React from "react";
import KeyValueInput from "./InputKeyValue";
import type { KeyValue } from "./InputKeyValue";
import * as TooltipPrimitive from "@radix-ui/react-tooltip";

const meta: Meta<typeof KeyValueInput> = {
  title: "refresh-components/inputs/InputKeyValue",
  component: KeyValueInput,
  tags: ["autodocs"],
  decorators: [
    (Story) => (
      <TooltipPrimitive.Provider>
        <div style={{ width: 400 }}>
          <Story />
        </div>
      </TooltipPrimitive.Provider>
    ),
  ],
};

export default meta;
type Story = StoryObj<typeof KeyValueInput>;

export const Default: Story = {
  render: function DefaultStory() {
    const [items, setItems] = React.useState<KeyValue[]>([
      { key: "", value: "" },
    ]);
    return (
      <KeyValueInput
        keyTitle="Key"
        valueTitle="Value"
        items={items}
        onChange={setItems}
      />
    );
  },
};

export const WithValues: Story = {
  render: function WithValuesStory() {
    const [items, setItems] = React.useState<KeyValue[]>([
      { key: "API_KEY", value: "sk-abc123" },
      { key: "BASE_URL", value: "https://api.example.com" },
    ]);
    return (
      <KeyValueInput
        keyTitle="Variable Name"
        valueTitle="Value"
        items={items}
        onChange={setItems}
      />
    );
  },
};

export const FixedLineMode: Story = {
  render: function FixedLineStory() {
    const [items, setItems] = React.useState<KeyValue[]>([
      { key: "Content-Type", value: "application/json" },
    ]);
    return (
      <KeyValueInput
        keyTitle="Header"
        valueTitle="Value"
        items={items}
        onChange={setItems}
        mode="fixed-line"
      />
    );
  },
};

export const KeyWideLayout: Story = {
  render: function KeyWideStory() {
    const [items, setItems] = React.useState<KeyValue[]>([
      { key: "Authorization", value: "Bearer token" },
    ]);
    return (
      <KeyValueInput
        keyTitle="Header"
        valueTitle="Value"
        items={items}
        onChange={setItems}
        layout="key-wide"
      />
    );
  },
};

export const Disabled: Story = {
  render: () => (
    <KeyValueInput
      keyTitle="Key"
      valueTitle="Value"
      items={[{ key: "LOCKED", value: "cannot-edit" }]}
      onChange={() => {}}
      disabled
    />
  ),
};

export const EmptyLineMode: Story = {
  render: function EmptyStory() {
    const [items, setItems] = React.useState<KeyValue[]>([]);
    return (
      <KeyValueInput
        keyTitle="Key"
        valueTitle="Value"
        items={items}
        onChange={setItems}
        mode="line"
      />
    );
  },
};

export const CustomAddLabel: Story = {
  render: function CustomLabelStory() {
    const [items, setItems] = React.useState<KeyValue[]>([
      { key: "", value: "" },
    ]);
    return (
      <KeyValueInput
        keyTitle="Name"
        valueTitle="Endpoint"
        items={items}
        onChange={setItems}
        addButtonLabel="Add Endpoint"
      />
    );
  },
};
