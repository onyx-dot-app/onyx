import type { Meta, StoryObj } from "@storybook/react";
import * as TooltipPrimitive from "@radix-ui/react-tooltip";
import { CopyButton } from "./components";

const meta: Meta<typeof CopyButton> = {
  title: "opal/Buttons/CopyButton",
  component: CopyButton,
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
type Story = StoryObj<typeof CopyButton>;

const getCopyText = () => "Hello, world!";

export const IconOnly: Story = {
  args: { getCopyText },
};

export const WithLabel: Story = {
  args: {
    getCopyText,
    children: "Copy",
  },
};

export const CustomTooltip: Story = {
  args: {
    getCopyText,
    tooltip: "Copy API key",
  },
};

export const PrimaryProminence: Story = {
  args: {
    getCopyText,
    children: "Copy link",
    prominence: "primary",
  },
};

export const SmallSize: Story = {
  args: {
    getCopyText,
    size: "sm",
  },
};
