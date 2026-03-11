import type { Meta, StoryObj } from "@storybook/react";
import React from "react";
import InputChipField from "./InputChipField";
import type { ChipItem } from "./InputChipField";
import * as TooltipPrimitive from "@radix-ui/react-tooltip";

const meta: Meta<typeof InputChipField> = {
  title: "refresh-components/inputs/InputChipField",
  component: InputChipField,
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
type Story = StoryObj<typeof InputChipField>;

export const Default: Story = {
  render: function DefaultStory() {
    const [chips, setChips] = React.useState<ChipItem[]>([]);
    const [value, setValue] = React.useState("");

    return (
      <InputChipField
        chips={chips}
        onRemoveChip={(id) => setChips((c) => c.filter((ch) => ch.id !== id))}
        onAdd={(label) => {
          setChips((c) => [...c, { id: crypto.randomUUID(), label }]);
          setValue("");
        }}
        value={value}
        onChange={setValue}
        placeholder="Type and press Enter..."
      />
    );
  },
};

export const WithChips: Story = {
  render: function WithChipsStory() {
    const [chips, setChips] = React.useState<ChipItem[]>([
      { id: "1", label: "React" },
      { id: "2", label: "TypeScript" },
      { id: "3", label: "Tailwind" },
    ]);
    const [value, setValue] = React.useState("");

    return (
      <InputChipField
        chips={chips}
        onRemoveChip={(id) => setChips((c) => c.filter((ch) => ch.id !== id))}
        onAdd={(label) => {
          setChips((c) => [...c, { id: crypto.randomUUID(), label }]);
          setValue("");
        }}
        value={value}
        onChange={setValue}
        placeholder="Add tags..."
      />
    );
  },
};

export const Disabled: Story = {
  render: () => (
    <InputChipField
      chips={[
        { id: "1", label: "Locked" },
        { id: "2", label: "Tag" },
      ]}
      onRemoveChip={() => {}}
      onAdd={() => {}}
      value=""
      onChange={() => {}}
      placeholder="Disabled"
      disabled
    />
  ),
};

export const ErrorVariant: Story = {
  render: function ErrorStory() {
    const [chips, setChips] = React.useState<ChipItem[]>([
      { id: "1", label: "Invalid" },
    ]);
    const [value, setValue] = React.useState("");

    return (
      <InputChipField
        chips={chips}
        onRemoveChip={(id) => setChips((c) => c.filter((ch) => ch.id !== id))}
        onAdd={(label) => {
          setChips((c) => [...c, { id: crypto.randomUUID(), label }]);
          setValue("");
        }}
        value={value}
        onChange={setValue}
        placeholder="Add labels..."
        variant="error"
      />
    );
  },
};
