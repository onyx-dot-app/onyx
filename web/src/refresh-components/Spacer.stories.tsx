import type { Meta, StoryObj } from "@storybook/react";
import Spacer from "./Spacer";

const meta: Meta<typeof Spacer> = {
  title: "refresh-components/Spacer",
  component: Spacer,
  tags: ["autodocs"],
  parameters: {
    layout: "centered",
  },
};

export default meta;
type Story = StoryObj<typeof Spacer>;

export const VerticalDefault: Story = {
  render: () => (
    <div className="flex flex-col items-start">
      <div className="p-2 bg-background-tint-03">Above</div>
      <Spacer />
      <div className="p-2 bg-background-tint-03">Below (1rem gap)</div>
    </div>
  ),
};

export const VerticalCustomRem: Story = {
  render: () => (
    <div className="flex flex-col items-start">
      <div className="p-2 bg-background-tint-03">Above</div>
      <Spacer vertical rem={3} />
      <div className="p-2 bg-background-tint-03">Below (3rem gap)</div>
    </div>
  ),
};

export const Horizontal: Story = {
  render: () => (
    <div className="flex flex-row items-center">
      <div className="p-2 bg-background-tint-03">Left</div>
      <Spacer horizontal rem={2} />
      <div className="p-2 bg-background-tint-03">Right (2rem gap)</div>
    </div>
  ),
};

export const PixelBased: Story = {
  render: () => (
    <div className="flex flex-col items-start">
      <div className="p-2 bg-background-tint-03">Above</div>
      <Spacer pixels={48} />
      <div className="p-2 bg-background-tint-03">Below (48px gap)</div>
    </div>
  ),
};
