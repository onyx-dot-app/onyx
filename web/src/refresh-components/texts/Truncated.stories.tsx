import type { Meta, StoryObj } from "@storybook/react";
import Truncated from "./Truncated";

const meta: Meta<typeof Truncated> = {
  title: "refresh-components/texts/Truncated",
  component: Truncated,
  tags: ["autodocs"],
};

export default meta;
type Story = StoryObj<typeof Truncated>;

export const ShortText: Story = {
  args: {
    children: "Short text that fits.",
    mainUiBody: true,
    text04: true,
  },
  decorators: [
    (Story) => (
      <div style={{ width: 300 }}>
        <Story />
      </div>
    ),
  ],
};

export const LongText: Story = {
  args: {
    children:
      "This is a very long piece of text that will definitely get truncated because it exceeds the width of the container and should show a tooltip on hover.",
    mainUiBody: true,
    text04: true,
  },
  decorators: [
    (Story) => (
      <div style={{ width: 200 }}>
        <Story />
      </div>
    ),
  ],
};

export const TooltipDisabled: Story = {
  args: {
    children:
      "Long text but tooltip is disabled so it won't appear even when truncated.",
    mainUiBody: true,
    text03: true,
    disable: true,
  },
  decorators: [
    (Story) => (
      <div style={{ width: 200 }}>
        <Story />
      </div>
    ),
  ],
};

export const CustomTooltipSide: Story = {
  args: {
    children:
      "Hover to see the tooltip appear on the right side instead of the default top.",
    mainUiBody: true,
    text04: true,
    side: "right",
  },
  decorators: [
    (Story) => (
      <div style={{ width: 200, paddingTop: 40 }}>
        <Story />
      </div>
    ),
  ],
};
