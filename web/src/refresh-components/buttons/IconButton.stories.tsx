import type { Meta, StoryObj } from "@storybook/react";
import IconButton from "./IconButton";
import { SvgSettings, SvgPlus, SvgX } from "@opal/icons";
import * as TooltipPrimitive from "@radix-ui/react-tooltip";

const meta: Meta<typeof IconButton> = {
  title: "refresh-components/buttons/IconButton",
  component: IconButton,
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
type Story = StoryObj<typeof IconButton>;

export const Default: Story = {
  args: {
    icon: SvgSettings,
  },
};

export const Variants: Story = {
  render: () => (
    <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
      <IconButton main icon={SvgSettings} />
      <IconButton action icon={SvgPlus} />
      <IconButton danger icon={SvgX} />
    </div>
  ),
};

export const Small: Story = {
  args: {
    icon: SvgSettings,
    small: true,
  },
};

export const WithTooltip: Story = {
  args: {
    icon: SvgSettings,
    tooltip: "Settings",
  },
};

export const Disabled: Story = {
  args: {
    icon: SvgSettings,
    disabled: true,
  },
};
