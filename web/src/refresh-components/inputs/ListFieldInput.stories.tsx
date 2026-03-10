import type { Meta, StoryObj } from "@storybook/react";
import React from "react";
import { ListFieldInput } from "./ListFieldInput";
import * as TooltipPrimitive from "@radix-ui/react-tooltip";

const meta: Meta<typeof ListFieldInput> = {
  title: "refresh-components/inputs/ListFieldInput",
  component: ListFieldInput,
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
type Story = StoryObj<typeof ListFieldInput>;

export const Default: Story = {
  render: function DefaultStory() {
    const [values, setValues] = React.useState<string[]>([]);
    return (
      <ListFieldInput
        values={values}
        onChange={setValues}
        placeholder="Type and press Enter..."
      />
    );
  },
};

export const WithValues: Story = {
  render: function WithValuesStory() {
    const [values, setValues] = React.useState([
      "admin@example.com",
      "user@example.com",
      "dev@example.com",
    ]);
    return (
      <ListFieldInput
        values={values}
        onChange={setValues}
        placeholder="Add email..."
      />
    );
  },
};

export const Disabled: Story = {
  render: () => (
    <ListFieldInput
      values={["locked-item"]}
      onChange={() => {}}
      placeholder="Cannot edit"
      disabled
    />
  ),
};

export const ErrorState: Story = {
  render: function ErrorStory() {
    const [values, setValues] = React.useState(["invalid"]);
    return (
      <ListFieldInput
        values={values}
        onChange={setValues}
        placeholder="Add value..."
        error
      />
    );
  },
};
