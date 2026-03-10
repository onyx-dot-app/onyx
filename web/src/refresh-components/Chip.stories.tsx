import type { Meta, StoryObj } from "@storybook/react";
import Chip from "./Chip";
import { SvgUser } from "@opal/icons";

const meta: Meta<typeof Chip> = {
  title: "refresh-components/Chip",
  component: Chip,
  tags: ["autodocs"],
};

export default meta;
type Story = StoryObj<typeof Chip>;

export const Default: Story = {
  args: {
    children: "Tag Name",
  },
};

export const WithIcon: Story = {
  args: {
    children: "John Doe",
    icon: SvgUser,
  },
};

export const Removable: Story = {
  args: {
    children: "Removable Tag",
    onRemove: () => alert("Removed!"),
  },
};

export const WithIconAndRemove: Story = {
  args: {
    children: "Jane Smith",
    icon: SvgUser,
    onRemove: () => alert("Removed!"),
  },
};
