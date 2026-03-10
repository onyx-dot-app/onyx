import type { Meta, StoryObj } from "@storybook/react";
import CreateButton from "./CreateButton";
import * as TooltipPrimitive from "@radix-ui/react-tooltip";

const meta: Meta<typeof CreateButton> = {
  title: "refresh-components/buttons/CreateButton",
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

export const RightIcon: Story = {
  args: {
    rightIcon: true,
    children: "Add Item",
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
      <CreateButton rightIcon>Add Item</CreateButton>
      <CreateButton disabled />
    </div>
  ),
};
