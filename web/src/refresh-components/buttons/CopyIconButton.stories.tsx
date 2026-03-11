import type { Meta, StoryObj } from "@storybook/react";
import CopyIconButton from "./CopyIconButton";
import * as TooltipPrimitive from "@radix-ui/react-tooltip";

const meta: Meta<typeof CopyIconButton> = {
  title: "refresh-components/buttons/CopyIconButton",
  component: CopyIconButton,
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
type Story = StoryObj<typeof CopyIconButton>;

export const Default: Story = {
  args: {
    getCopyText: () => "Copied text!",
  },
};

export const WithTooltip: Story = {
  args: {
    getCopyText: () => "Copied text!",
    tooltip: "Copy to clipboard",
  },
};
