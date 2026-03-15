import type { Meta, StoryObj } from "@storybook/react";
import ScrollIndicatorDiv from "./ScrollIndicatorDiv";

const meta: Meta<typeof ScrollIndicatorDiv> = {
  title: "refresh-components/ScrollIndicatorDiv",
  component: ScrollIndicatorDiv,
  tags: ["autodocs"],
  parameters: {
    layout: "centered",
  },
};

export default meta;
type Story = StoryObj<typeof ScrollIndicatorDiv>;

const sampleItems = Array.from({ length: 30 }, (_, i) => (
  <div key={i} className="p-2 border-b border-border-01">
    Scrollable item {i + 1}
  </div>
));

export const GradientVariant: Story = {
  args: {
    variant: "gradient",
    style: { width: 300, height: 250 },
    children: sampleItems,
  },
};

export const ShadowVariant: Story = {
  args: {
    variant: "shadow",
    style: { width: 300, height: 250 },
    children: sampleItems,
  },
};

export const DisabledIndicators: Story = {
  args: {
    disableIndicators: true,
    style: { width: 300, height: 250 },
    children: sampleItems,
  },
};

export const WithBottomSpacing: Story = {
  args: {
    variant: "gradient",
    bottomSpacing: "2rem",
    style: { width: 300, height: 250 },
    children: sampleItems,
  },
};
