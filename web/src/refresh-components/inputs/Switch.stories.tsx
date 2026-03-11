import type { Meta, StoryObj } from "@storybook/react";
import Switch from "./Switch";
import * as TooltipPrimitive from "@radix-ui/react-tooltip";

const meta: Meta<typeof Switch> = {
  title: "refresh-components/inputs/Switch",
  component: Switch,
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
type Story = StoryObj<typeof Switch>;

export const Default: Story = {
  args: {},
};

export const Checked: Story = {
  args: {
    checked: true,
  },
};

export const Disabled: Story = {
  args: {
    disabled: true,
  },
};
