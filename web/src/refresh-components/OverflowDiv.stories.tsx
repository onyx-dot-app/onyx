import type { Meta, StoryObj } from "@storybook/react";
import OverflowDiv from "./OverflowDiv";

const meta: Meta<typeof OverflowDiv> = {
  title: "refresh-components/OverflowDiv",
  component: OverflowDiv,
  tags: ["autodocs"],
  parameters: {
    layout: "centered",
  },
};

export default meta;
type Story = StoryObj<typeof OverflowDiv>;

const sampleItems = Array.from({ length: 25 }, (_, i) => (
  <div key={i} className="p-2 border-b border-border-01">
    Sidebar item {i + 1}
  </div>
));

export const Default: Story = {
  args: {
    style: { width: 260, height: 300 },
    children: sampleItems,
  },
};

export const MaskDisabled: Story = {
  args: {
    disableMask: true,
    style: { width: 260, height: 300 },
    children: sampleItems,
  },
};

export const CustomHeight: Story = {
  args: {
    height: "4rem",
    style: { width: 260, height: 300 },
    children: sampleItems,
  },
};
