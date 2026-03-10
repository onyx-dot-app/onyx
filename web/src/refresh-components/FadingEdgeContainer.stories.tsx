import type { Meta, StoryObj } from "@storybook/react";
import FadingEdgeContainer from "./FadingEdgeContainer";

const meta: Meta<typeof FadingEdgeContainer> = {
  title: "refresh-components/FadingEdgeContainer",
  component: FadingEdgeContainer,
  tags: ["autodocs"],
  parameters: {
    layout: "centered",
  },
};

export default meta;
type Story = StoryObj<typeof FadingEdgeContainer>;

const sampleItems = Array.from({ length: 20 }, (_, i) => (
  <div key={i} className="p-2 border-b border-border-01">
    Item {i + 1}
  </div>
));

export const BottomFade: Story = {
  args: {
    direction: "bottom",
    className: "max-h-[200px] overflow-y-auto",
    children: sampleItems,
  },
};

export const TopFade: Story = {
  args: {
    direction: "top",
    className: "max-h-[200px] overflow-y-auto",
    children: sampleItems,
  },
};

export const CustomFadeHeight: Story = {
  args: {
    direction: "bottom",
    className: "max-h-[200px] overflow-y-auto",
    fadeClassName: "h-16",
    children: sampleItems,
  },
};
