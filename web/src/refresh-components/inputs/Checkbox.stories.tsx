import type { Meta, StoryObj } from "@storybook/react";
import Checkbox from "./Checkbox";
import * as TooltipPrimitive from "@radix-ui/react-tooltip";

const meta: Meta<typeof Checkbox> = {
  title: "refresh-components/inputs/Checkbox",
  component: Checkbox,
  tags: ["autodocs"],
  decorators: [
    (Story) => (
      <TooltipPrimitive.Provider>
        <Story />
      </TooltipPrimitive.Provider>
    ),
  ],
};

export default meta;
type Story = StoryObj<typeof Checkbox>;

export const Default: Story = {
  args: {},
};

export const Checked: Story = {
  args: {
    checked: true,
  },
};

export const Indeterminate: Story = {
  args: {
    indeterminate: true,
  },
};

export const WithLabel: Story = {
  render: () => (
    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
      <Checkbox id="terms" />
      <label htmlFor="terms" style={{ cursor: "pointer" }}>
        Accept terms and conditions
      </label>
    </div>
  ),
};
