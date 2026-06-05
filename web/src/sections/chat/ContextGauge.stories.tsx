import type { Meta, StoryObj } from "@storybook/react";
import ContextGauge from "@/sections/chat/ContextGauge";

const meta: Meta<typeof ContextGauge> = {
  title: "Chat/Context Gauge",
  component: ContextGauge,
  tags: ["autodocs"],
  decorators: [
    (Story) => (
      <div className="p-4">
        <Story />
      </div>
    ),
  ],
};

export default meta;
type Story = StoryObj<typeof ContextGauge>;

// Fill color crosses from theme-primary -> warning (>=70%) -> error (>=90%).
export const Low: Story = {
  args: {
    usage: { used_tokens: 38_400, max_input_tokens: 128_000, is_baseline: false },
  },
};

export const Warning: Story = {
  args: {
    usage: { used_tokens: 96_000, max_input_tokens: 128_000, is_baseline: false },
  },
};

export const Critical: Story = {
  args: {
    usage: { used_tokens: 122_000, max_input_tokens: 128_000, is_baseline: false },
  },
};

// Empty chat: only the system-prompt baseline is counted.
export const Baseline: Story = {
  args: {
    usage: { used_tokens: 1_200, max_input_tokens: 128_000, is_baseline: true },
  },
};

// No usable ratio -> renders nothing.
export const Hidden: Story = {
  args: { usage: null },
};
