import type { Meta, StoryObj } from "@storybook/react";
import ShadowDiv from "./ShadowDiv";

const meta: Meta<typeof ShadowDiv> = {
  title: "refresh-components/ShadowDiv",
  component: ShadowDiv,
  tags: ["autodocs"],
  parameters: {
    layout: "centered",
  },
};

export default meta;
type Story = StoryObj<typeof ShadowDiv>;

const sampleItems = Array.from({ length: 30 }, (_, i) => (
  <div key={i} className="p-2 border-b border-border-01">
    Scrollable item {i + 1}
  </div>
));

export const Default: Story = {
  args: {
    className: "max-h-[250px]",
    style: { width: 300 },
    children: sampleItems,
  },
};

export const BottomOnly: Story = {
  args: {
    bottomOnly: true,
    className: "max-h-[250px]",
    style: { width: 300 },
    children: sampleItems,
  },
};

export const TopOnly: Story = {
  args: {
    topOnly: true,
    className: "max-h-[250px]",
    style: { width: 300 },
    children: sampleItems,
  },
};

export const CustomShadowHeight: Story = {
  args: {
    shadowHeight: "3rem",
    className: "max-h-[250px]",
    style: { width: 300 },
    children: sampleItems,
  },
};
