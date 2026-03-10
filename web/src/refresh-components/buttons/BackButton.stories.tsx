import type { Meta, StoryObj } from "@storybook/react";
import BackButton from "./BackButton";
import * as TooltipPrimitive from "@radix-ui/react-tooltip";

const meta: Meta<typeof BackButton> = {
  title: "refresh-components/buttons/BackButton",
  component: BackButton,
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
type Story = StoryObj<typeof BackButton>;

export const Default: Story = {};

export const WithBehaviorOverride: Story = {
  args: {
    behaviorOverride: () => {
      console.log("Custom back behavior");
    },
  },
};
