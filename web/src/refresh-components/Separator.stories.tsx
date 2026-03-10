import type { Meta, StoryObj } from "@storybook/react";
import Separator from "./Separator";

const meta: Meta<typeof Separator> = {
  title: "refresh-components/Separator",
  component: Separator,
  tags: ["autodocs"],
};

export default meta;
type Story = StoryObj<typeof Separator>;

export const Horizontal: Story = {
  decorators: [
    (Story) => (
      <div style={{ width: 400 }}>
        <div>Content above</div>
        <Story />
        <div>Content below</div>
      </div>
    ),
  ],
};

export const Vertical: Story = {
  args: {
    orientation: "vertical",
  },
  decorators: [
    (Story) => (
      <div style={{ display: "flex", alignItems: "center", height: 60 }}>
        <span>Left</span>
        <Story />
        <span>Right</span>
      </div>
    ),
  ],
};

export const NoPadding: Story = {
  args: {
    noPadding: true,
  },
  decorators: [
    (Story) => (
      <div style={{ width: 400 }}>
        <div>No padding above</div>
        <Story />
        <div>No padding below</div>
      </div>
    ),
  ],
};
