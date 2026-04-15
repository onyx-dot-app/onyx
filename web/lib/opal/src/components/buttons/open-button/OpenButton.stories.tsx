import type { Meta, StoryObj } from "@storybook/react";
import { OpenButton } from "@opal/components";
import { Disabled as DisabledProvider } from "@opal/core";
import { SvgSettings } from "@opal/icons";
import * as TooltipPrimitive from "@radix-ui/react-tooltip";

const meta: Meta<typeof OpenButton> = {
  title: "opal/components/OpenButton",
  component: OpenButton,
  tags: ["autodocs"],
  decorators: [
    (Story) => (
      <TooltipPrimitive.Provider>
        <Story />
      </TooltipPrimitive.Provider>
    ),
  ],
};

export default meta;
type Story = StoryObj<typeof OpenButton>;

export const Default: Story = {
  args: {
    children: "Select option",
  },
};

export const WithIcon: Story = {
  args: {
    icon: SvgSettings,
    children: "Settings",
  },
};

export const Open: Story = {
  args: {
    interaction: "hover",
    children: "Open state",
  },
};

export const Foldable: Story = {
  args: {
    foldable: true,
    icon: SvgSettings,
    children: "Settings",
  },
};

export const FoldableDisabled: Story = {
  args: {
    foldable: true,
    icon: SvgSettings,
    children: "Settings",
  },
  decorators: [
    (Story) => (
      <DisabledProvider disabled>
        <Story />
      </DisabledProvider>
    ),
  ],
};

export const Sizes: Story = {
  render: () => (
    <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
      {(["lg", "md", "sm", "xs", "2xs"] as const).map((size) => (
        <OpenButton key={size} size={size}>
          {size}
        </OpenButton>
      ))}
    </div>
  ),
};

export const WithTooltip: Story = {
  args: {
    icon: SvgSettings,
    children: "Settings",
    tooltip: "Open settings",
    tooltipSide: "bottom",
  },
};
