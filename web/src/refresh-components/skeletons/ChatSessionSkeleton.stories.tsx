import type { Meta, StoryObj } from "@storybook/react";
import ChatSessionSkeleton from "./ChatSessionSkeleton";

const meta: Meta<typeof ChatSessionSkeleton> = {
  title: "refresh-components/Skeletons/ChatSessionSkeleton",
  component: ChatSessionSkeleton,
  tags: ["autodocs"],
  parameters: {
    layout: "padded",
  },
};

export default meta;
type Story = StoryObj<typeof ChatSessionSkeleton>;

export const Default: Story = {};

export const Multiple: Story = {
  render: () => (
    <div className="flex flex-col gap-1" style={{ width: 300 }}>
      <ChatSessionSkeleton />
      <ChatSessionSkeleton />
      <ChatSessionSkeleton />
    </div>
  ),
};
