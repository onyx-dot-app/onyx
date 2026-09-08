import type { Meta, StoryObj } from "@storybook/react-vite";
import EnabledCount from "@/lib/tools/components/EnabledCount";

const meta: Meta<typeof EnabledCount> = {
  title: "tools/EnabledCount",
  component: EnabledCount,
  tags: ["autodocs"],
  parameters: {
    layout: "centered",
  },
};

export default meta;
type Story = StoryObj<typeof EnabledCount>;

export const Default: Story = {
  args: {
    enabledCount: 5,
    totalCount: 12,
  },
};

export const AllEnabled: Story = {
  args: {
    enabledCount: 8,
    totalCount: 8,
  },
};

export const NoneEnabled: Story = {
  args: {
    enabledCount: 0,
    totalCount: 15,
  },
};

export const SingleItem: Story = {
  args: {
    enabledCount: 1,
    totalCount: 1,
  },
};
