import type { Meta, StoryObj } from "@storybook/react-vite";
import React from "react";
import { InputList } from "@opal/components";
import * as TooltipPrimitive from "@radix-ui/react-tooltip";

const meta: Meta<typeof InputList> = {
  title: "opal/components/InputList",
  component: InputList,
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
type Story = StoryObj<typeof InputList>;

export const Default: Story = {
  render: function DefaultStory() {
    const [values, setValues] = React.useState<string[]>([]);
    return (
      <InputList
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
      <InputList
        values={values}
        onChange={setValues}
        placeholder="Add email..."
      />
    );
  },
};

export const Disabled: Story = {
  render: () => (
    <InputList
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
      <InputList
        values={values}
        onChange={setValues}
        placeholder="Add value..."
        error
      />
    );
  },
};
