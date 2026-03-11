import type { Meta, StoryObj } from "@storybook/react";
import ColorSwatch from "./ColorSwatch";

const meta: Meta<typeof ColorSwatch> = {
  title: "refresh-components/ColorSwatch",
  component: ColorSwatch,
  tags: ["autodocs"],
  parameters: {
    layout: "centered",
  },
};

export default meta;
type Story = StoryObj<typeof ColorSwatch>;

export const Light: Story = {
  args: {
    light: true,
  },
};

export const Dark: Story = {
  args: {
    dark: true,
  },
};

export const SideBySide: Story = {
  render: () => (
    <div className="flex gap-4 items-center">
      <ColorSwatch light />
      <ColorSwatch dark />
    </div>
  ),
};
