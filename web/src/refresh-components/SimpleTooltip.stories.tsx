import type { Meta, StoryObj } from "@storybook/react";
import SimpleTooltip from "./SimpleTooltip";

const meta: Meta<typeof SimpleTooltip> = {
  title: "refresh-components/SimpleTooltip",
  component: SimpleTooltip,
  tags: ["autodocs"],
  parameters: {
    layout: "centered",
  },
};

export default meta;
type Story = StoryObj<typeof SimpleTooltip>;

export const Default: Story = {
  args: {
    tooltip: "This is a tooltip",
    children: <button>Hover me</button>,
  },
};

export const SideVariants: Story = {
  render: () => (
    <div style={{ display: "flex", gap: 24, padding: 48 }}>
      {(["top", "right", "bottom", "left"] as const).map((side) => (
        <SimpleTooltip key={side} tooltip={`Tooltip on ${side}`} side={side}>
          <button>{side}</button>
        </SimpleTooltip>
      ))}
    </div>
  ),
};

export const Disabled: Story = {
  args: {
    tooltip: "You won't see this",
    disabled: true,
    children: <button>Tooltip disabled</button>,
  },
};

export const StringChild: Story = {
  render: () => (
    <SimpleTooltip>
      <span>String child auto-tooltips itself</span>
    </SimpleTooltip>
  ),
};
