import type { Meta, StoryObj } from "@storybook/react";
import type { Decorator } from "@storybook/react";
import * as TooltipPrimitive from "@radix-ui/react-tooltip";
import { Tooltip } from "@opal/components/tooltip/components";
import { Button } from "@opal/components/buttons/button/components";
import { Card } from "@opal/components";

const withTooltipProvider: Decorator = (Story) => (
  <TooltipPrimitive.Provider>
    <Story />
  </TooltipPrimitive.Provider>
);

const meta: Meta<typeof Tooltip> = {
  title: "opal/components/Tooltip",
  component: Tooltip,
  tags: ["autodocs"],
  decorators: [withTooltipProvider],
};

export default meta;
type Story = StoryObj<typeof Tooltip>;

export const Default: Story = {
  render: () => (
    <Tooltip tooltip="This is a tooltip">
      <Button prominence="secondary">Hover me</Button>
    </Tooltip>
  ),
};

export const Sides: Story = {
  render: () => (
    <div className="flex gap-8 items-center py-16 px-32">
      {(["top", "right", "bottom", "left"] as const).map((side) => (
        <Tooltip key={side} tooltip={`Tooltip on ${side}`} side={side}>
          <Button prominence="secondary" size="sm">
            {side}
          </Button>
        </Tooltip>
      ))}
    </div>
  ),
};

export const OnCard: Story = {
  render: () => (
    <Tooltip tooltip="Card tooltip appears on hover">
      <Card border="solid" padding="md">
        <p className="text-sm">Hover this card</p>
      </Card>
    </Tooltip>
  ),
};

export const NoTooltip: Story = {
  name: "No tooltip (passthrough)",
  render: () => (
    <Tooltip tooltip={undefined}>
      <Button prominence="secondary">No tooltip</Button>
    </Tooltip>
  ),
};
