import type { Meta, StoryObj } from "@storybook/react";
import { ProgressBar } from "@opal/components";

const COLORS = ["blue", "green", "red", "purple"] as const;

const meta: Meta<typeof ProgressBar> = {
  title: "opal/components/ProgressBar",
  component: ProgressBar,
  tags: ["autodocs"],
};

export default meta;
type Story = StoryObj<typeof ProgressBar>;

export const Default: Story = {
  args: {
    value: 40,
    max: 100,
  },
  render: (args) => (
    <div className="w-80">
      <ProgressBar {...args} />
    </div>
  ),
};

export const AllColors: Story = {
  render: () => (
    <div className="flex flex-col gap-3 w-80">
      {COLORS.map((color) => (
        <ProgressBar key={color} value={60} max={100} color={color} />
      ))}
    </div>
  ),
};

export const Extremes: Story = {
  render: () => (
    <div className="flex flex-col gap-3 w-80">
      <ProgressBar value={0} max={100} />
      <ProgressBar value={13} max={100} />
      <ProgressBar value={100} max={100} />
    </div>
  ),
};
