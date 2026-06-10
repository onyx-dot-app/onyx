import type { Meta, StoryObj } from "@storybook/react";
import ContextGauge from "@/sections/chat/ContextGauge";

const meta: Meta<typeof ContextGauge> = {
  title: "Chat/Context Gauge",
  component: ContextGauge,
  tags: ["autodocs"],
  parameters: { layout: "centered" },
};

export default meta;
type Story = StoryObj<typeof ContextGauge>;

// Fill color crosses from theme-primary -> warning (>=70%) -> error (>=90%).
export const Low: Story = {
  args: {
    usage: { used_tokens: 38_400, max_input_tokens: 128_000 },
  },
};

export const Warning: Story = {
  args: {
    usage: { used_tokens: 96_000, max_input_tokens: 128_000 },
  },
};

export const Critical: Story = {
  args: {
    usage: { used_tokens: 122_000, max_input_tokens: 128_000 },
  },
};

// No usable ratio -> renders nothing.
export const Hidden: Story = {
  args: { usage: null },
};
