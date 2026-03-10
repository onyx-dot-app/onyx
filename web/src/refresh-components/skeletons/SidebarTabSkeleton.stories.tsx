import type { Meta, StoryObj } from "@storybook/react";
import SidebarTabSkeleton from "./SidebarTabSkeleton";

const meta: Meta<typeof SidebarTabSkeleton> = {
  title: "refresh-components/Skeletons/SidebarTabSkeleton",
  component: SidebarTabSkeleton,
  tags: ["autodocs"],
  parameters: {
    layout: "padded",
  },
};

export default meta;
type Story = StoryObj<typeof SidebarTabSkeleton>;

export const Default: Story = {};

export const NarrowText: Story = {
  args: {
    textWidth: "w-1/3",
  },
};

export const WideText: Story = {
  args: {
    textWidth: "w-full",
  },
};

export const Multiple: Story = {
  render: () => (
    <div className="flex flex-col gap-1" style={{ width: 260 }}>
      <SidebarTabSkeleton textWidth="w-3/4" />
      <SidebarTabSkeleton textWidth="w-1/2" />
      <SidebarTabSkeleton textWidth="w-2/3" />
      <SidebarTabSkeleton textWidth="w-1/3" />
    </div>
  ),
};
