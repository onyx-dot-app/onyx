import type { Meta, StoryObj } from "@storybook/react";
import ThinkingCard from "@/app/craft/components/ThinkingCard";

const THINKING_CONTENT = `Inspecting the current Craft session state and tracing the packet flow.

The stream contains a thought chunk before the final answer, so the UI keeps a quiet row in the transcript.

Next step: preserve the row as collapsed context while letting the user expand it if they want the details.`;

const meta: Meta<typeof ThinkingCard> = {
  title: "Apps/Craft/Messages/Thinking Card",
  component: ThinkingCard,
  tags: ["autodocs"],
  render: (args) => (
    <ThinkingCard
      key={`${args.isStreaming ? "live" : "complete"}-${
        args.defaultOpen ? "open" : "closed"
      }`}
      {...args}
    />
  ),
  decorators: [
    (Story) => (
      <div className="w-[640px]">
        <Story />
      </div>
    ),
  ],
  args: {
    content: THINKING_CONTENT,
    defaultOpen: false,
  },
};

export default meta;
type Story = StoryObj<typeof ThinkingCard>;

export const LiveCollapsed: Story = {
  args: {
    isStreaming: true,
  },
};

export const LiveExpanded: Story = {
  args: {
    isStreaming: true,
    defaultOpen: true,
  },
};

export const CompletedCollapsed: Story = {
  args: {
    isStreaming: false,
  },
};

export const CompletedExpanded: Story = {
  args: {
    isStreaming: false,
    defaultOpen: true,
  },
};
