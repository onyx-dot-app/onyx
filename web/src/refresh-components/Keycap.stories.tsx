import type { Meta, StoryObj } from "@storybook/react";
import Keycap from "@/refresh-components/Keycap";

const meta: Meta<typeof Keycap> = {
  title: "refresh-components/Keycap",
  component: Keycap,
  tags: ["autodocs"],
  args: {
    children: "esc",
  },
};

export default meta;
type Story = StoryObj<typeof Keycap>;

/** Resting keycap used in inline keyboard hints. */
export const Default: Story = {};

/** Filled state — a hot danger fill for active shortcut hints. */
export const Filled: Story = {
  args: {
    filled: true,
  },
};

export const Glyphs: Story = {
  render: () => (
    <div className="flex items-center gap-1">
      <Keycap>↵</Keycap>
      <Keycap>⌫</Keycap>
      <Keycap>esc</Keycap>
    </div>
  ),
};
