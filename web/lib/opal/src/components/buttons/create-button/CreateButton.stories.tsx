import type { Meta, StoryObj } from "@storybook/react";
import CreateButton from "./components";
import * as TooltipPrimitive from "@radix-ui/react-tooltip";

const meta: Meta<typeof CreateButton> = {
  title: "opal/buttons/CreateButton",
  component: CreateButton,
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
type Story = StoryObj<typeof CreateButton>;

export const Default: Story = {};

export const CustomLabel: Story = {
  args: {
    children: "New Document",
  },
};

export const Disabled: Story = {
  args: {
    disabled: true,
  },
};

export const AllVariants: Story = {
  render: () => (
    <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
      <CreateButton />
      <CreateButton>New Document</CreateButton>
      <CreateButton disabled />
    </div>
  ),
};
